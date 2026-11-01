// GSA's aggregations computed from the copy's values, the way Elasticsearch
// computes them, with one decision of James's (2026-10-31): percentiles are
// true values (the floor(q*n)-th sorted price), not TDigest estimates.
//
// Prices are float32 (GSA's index type); the copy stores each as its float32
// value widened to a double, so every number here is exact before arithmetic.
import {PyFloat, floatRepr, type Py} from "./pyjson.ts";

/** A distinct value and how many records have it. Prices come sorted ascending. */
export type Counted = [value: number, count: number];

/** ES writes NaN and infinities as strings ("NaN"); other doubles as numbers. */
const double = (x: number): Py => (Number.isNaN(x) ? "NaN" : !Number.isFinite(x) ? (x > 0 ? "Infinity" : "-Infinity") : new PyFloat(x));

/** x = mantissa * 2**exponent exactly. */
function decompose(x: number): [bigint, number] {
  if (x === 0) return [0n, 0];
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const hi = view.getUint32(0);
  const lo = view.getUint32(4);
  const biased = (hi >>> 20) & 0x7ff;
  let mantissa = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  let exponent = -1074;
  if (biased) {
    mantissa |= 1n << 52n;
    exponent = biased - 1075;
  }
  while (mantissa && !(mantissa & 1n)) {
    mantissa >>= 1n;
    exponent++;
  }
  return [hi >>> 31 ? -mantissa : mantissa, exponent];
}

/** The exact sum of count * term for (mantissa, exponent) terms, rounded once to the nearest double. */
function exactSum(terms: [bigint, number, number][]): number {
  if (!terms.length) return 0;
  const low = Math.min(...terms.map(t => t[1]));
  let total = 0n;
  for (const [mantissa, exponent, count] of terms) total += mantissa * BigInt(count) << BigInt(exponent - low);
  // Number(bigint) rounds to nearest, ties to even; a power-of-two scale is exact.
  return low >= 0 ? Number(total) * 2 ** low : Number(total) / 2 ** -low;
}

/** extended_stats (sigma 2) on the prices. Elasticsearch adds values and their
 * squares with Kahan summation; the float32 squares are exact in a double, so
 * the exactly rounded sums are what it gets (every recorded answer agrees). */
export function extendedStats(prices: Counted[], sigma: number): Record<string, Py> {
  const count = prices.reduce((n, [, c]) => n + c, 0);
  if (!count) {
    const none = {upper: null, lower: null, upper_population: null, lower_population: null, upper_sampling: null, lower_sampling: null};
    return {count: 0, min: null, max: null, avg: null, sum: new PyFloat(0), sum_of_squares: null, variance: null, variance_population: null,
      variance_sampling: null, std_deviation: null, std_deviation_population: null, std_deviation_sampling: null, std_deviation_bounds: none};
  }
  const parts = prices.map(([value, c]) => [...decompose(value), c] as [bigint, number, number]);
  const sum = exactSum(parts);
  const sumOfSqrs = exactSum(parts.map(([m, e, c]) => [m * m, 2 * e, c]));
  const avg = sum / count;
  // InternalExtendedStats: variance = (sumOfSqrs - sum*sum/count) / count (or count - 1), floored at 0.
  const varPop = varianceFloor((sumOfSqrs - ((sum * sum) / count)) / count);
  const sampling = varianceFloor((sumOfSqrs - ((sum * sum) / count)) / (count - 1));
  const sdPop = Math.sqrt(varPop);
  const sdSamp = Math.sqrt(sampling);
  return {
    count,
    min: new PyFloat(prices[0][0]),
    max: new PyFloat(prices[prices.length - 1][0]),
    avg: double(avg),
    sum: double(sum),
    sum_of_squares: double(sumOfSqrs),
    variance: double(varPop),
    variance_population: double(varPop),
    variance_sampling: double(sampling),
    std_deviation: double(sdPop),
    std_deviation_population: double(sdPop),
    std_deviation_sampling: double(sdSamp),
    std_deviation_bounds: {
      upper: double(avg + (sdPop * sigma)),
      lower: double(avg - (sdPop * sigma)),
      upper_population: double(avg + (sdPop * sigma)),
      lower_population: double(avg - (sdPop * sigma)),
      upper_sampling: double(avg + (sdSamp * sigma)),
      lower_sampling: double(avg - (sdSamp * sigma)),
    },
  };
}

/** `variance < 0 ? 0 : variance` (NaN stays NaN, as in Java). */
const varianceFloor = (variance: number) => (variance < 0 ? 0 : variance);

/** Percentiles as true values: for percent q of n sorted prices, the one at
 * 0-based index min(n - 1, floor(q * n / 100)). This equals GSA's TDigest
 * answers on small sets (n = 1, 2, 3, 15, 24 in the fixtures); on larger sets
 * GSA's estimates differ and drift between calls. Keys as Elasticsearch writes them ("10.0"). */
export function percentiles(prices: Counted[], percents: number[]): Record<string, Py> {
  const n = prices.reduce((sum, [, c]) => sum + c, 0);
  const values: Record<string, Py> = {};
  for (const q of percents) {
    let value: Py = null;
    if (n) {
      const index = Math.min(n - 1, Math.floor((q * n) / 100));
      let seen = 0;
      for (const [price, c] of prices) {
        seen += c;
        if (index < seen) {
          value = new PyFloat(price);
          break;
        }
      }
    }
    values[floatRepr(q)] = value;
  }
  return {values};
}

/** A terms aggregation from exact counts: most records first, then key
 * ascending by code point (Elasticsearch compares UTF-8 bytes), the top `size`
 * buckets, the rest counted in sum_other_doc_count. One copy, so the error bound is 0. */
export function terms(entries: [string, number][], size: number, total?: number): Record<string, Py> {
  const sorted = [...entries].sort((a, b) => b[1] - a[1] || codePointCompare(a[0], b[0]));
  const top = sorted.slice(0, size);
  const all = total ?? entries.reduce((sum, [, c]) => sum + c, 0);
  return {
    doc_count_error_upper_bound: 0,
    sum_other_doc_count: all - top.reduce((sum, [, c]) => sum + c, 0),
    buckets: top.map(([key, doc_count]) => ({key, doc_count})),
  };
}

export function codePointCompare(a: string, b: string): number {
  if (a === b) return 0;
  const x = [...a];
  const y = [...b];
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const d = x[i].codePointAt(0)! - y[i].codePointAt(0)!;
    if (d) return d;
  }
  return x.length - y.length;
}

// ---------- variable_width_histogram ----------
//
// Elasticsearch 7.10's VariableWidthHistogramAggregator on one shard, fed the
// prices in ascending order, then InternalVariableWidthHistogram's final
// reduce. GSA's index has 5 shards fed in index order, so on large result sets
// its buckets differ (a measured tolerance); while no shard holds more than
// 450 prices each price starts its own bucket either way, and the answers
// agree exactly (every recorded fixture, up to n = 91).

interface Cluster {
  min: number;
  max: number;
  centroid: number;
  size: number;
}

/** One shard's buckets (collection, then buildAggregations). */
function collect(values: Float64Array, shardSize: number, initialBuffer: number): Cluster[] {
  const clusters: Cluster[] = [];
  let avgBucketDistance = 0;
  const updateAvg = () => {
    avgBucketDistance = (clusters[clusters.length - 1].centroid - clusters[0].centroid) / (clusters.length - 1);
  };
  const add = (i: number, value: number) => {
    const c = clusters[i];
    c.max = Math.max(c.max, value);
    c.min = Math.min(c.min, value);
    c.centroid = ((c.centroid * c.size) + value) / (c.size + 1);
    c.size += 1;
  };
  // MergeBucketsPhase's constructor: the buffered values, sorted, in runs of docsPerBucket.
  const bucketBuffered = (buffer: Float64Array) => {
    const numBuckets = Math.floor((shardSize * 3) / 4); // mergePhaseInitialBucketCount
    const sorted = Float64Array.from(buffer).sort();
    const docsPerBucket = Math.ceil(sorted.length / numBuckets);
    let ord = 0;
    for (let i = 0; i < sorted.length; i++) {
      if (ord === clusters.length) clusters.push({min: sorted[i], max: sorted[i], centroid: sorted[i], size: 1});
      else add(ord, sorted[i]);
      if ((i + 1) % docsPerBucket === 0) ord += 1;
    }
    if (sorted.length > 1) updateAvg();
  };
  /** BinarySearcher.search: the index of the centroid closest to value. */
  const nearest = (value: number): number => {
    let from = 0;
    let to = clusters.length - 1;
    const compare = (i: number) => Math.sign(clusters[i].centroid - value);
    const distance = (i: number) => Math.abs(clusters[i].centroid - value);
    const closest = (a: number, b: number) => (distance(a) < distance(b) ? a : b);
    while (from < to) {
      const mid = (from + to) >>> 1;
      const result = compare(mid);
      if (result === 0) return mid;
      if (result < 0) {
        if (mid < to && compare(mid + 1) > 0) return closest(mid, mid + 1);
        if (mid === to) return mid;
        from = mid + 1;
      } else {
        if (mid > from && compare(mid - 1) < 0) return closest(mid, mid - 1);
        if (mid === 0) return mid;
        to = mid - 1;
      }
    }
    return from;
  };
  const buffered = values.length < initialBuffer ? values : values.subarray(0, initialBuffer);
  bucketBuffered(buffered);
  for (let i = buffered.length; i < values.length; i++) {
    const value = values[i];
    let ord = nearest(value);
    const distance = Math.abs(clusters[ord].centroid - value);
    if (distance > 2 * avgBucketDistance && clusters.length < shardSize) {
      // A distant value starts a cluster, kept in centroid order.
      clusters.push({min: value, max: value, centroid: value, size: 1});
      if (value > clusters[ord].centroid) ord += 1;
      clusters.splice(ord, 0, clusters.pop()!);
      updateAvg();
    } else {
      add(ord, value);
      if (ord === 0 || ord === clusters.length - 1) updateAvg();
    }
  }
  // Shards return buckets ordered by centroid.
  return clusters.map(c => ({...c})).sort((a, b) => a.centroid - b.centroid);
}

/** reduceBucket: buckets merged in list order (doc counts, bounds, weighted centroid). */
function reduceBucket(buckets: Cluster[]): Cluster {
  let size = 0;
  let min = Infinity;
  let max = -Infinity;
  let sum = 0;
  for (const b of buckets) {
    size += b.size;
    min = Math.min(min, b.min);
    max = Math.max(max, b.max);
    sum += b.size * b.centroid;
  }
  return {min, max, centroid: sum / size, size};
}

/** mergeBucketsWithPlan: each range of adjacent buckets replaced by one (merged last to first, as Java removes them). */
function mergeWithPlan(buckets: Cluster[], plan: [number, number][]): Cluster[] {
  const out = [...buckets];
  for (let p = plan.length - 1; p >= 0; p--) {
    const [start, end] = plan[p];
    if (start === end) continue;
    const toMerge: Cluster[] = [];
    for (let i = end; i > start; i--) toMerge.push(...out.splice(i, 1));
    toMerge.push(out[start]);
    out[start] = reduceBucket(toMerge);
  }
  return out;
}

/** variable_width_histogram buckets ({min, key, max, doc_count}) for prices sorted ascending. */
export function histogram(prices: Counted[], {buckets: target, shardSize, initialBuffer}: {buckets: number; shardSize: number; initialBuffer: number}): Py[] {
  const n = prices.reduce((sum, [, c]) => sum + c, 0);
  if (!n) return [];
  const values = new Float64Array(n);
  let at = 0;
  for (const [value, c] of prices) values.fill(value, at, (at += c));
  const shard = collect(values, shardSize, initialBuffer);
  // reduceBuckets: buckets with the same centroid become one.
  let reduced: Cluster[] = [];
  let run: Cluster[] = [];
  for (const b of shard) {
    if (run.length && b.centroid !== run[0].centroid) {
      reduced.push(reduceBucket(run));
      run = [];
    }
    run.push(b);
  }
  if (run.length) reduced.push(reduceBucket(run));
  // mergeBucketsIfNeeded: plan merges of the two closest centroids until `target` remain.
  const ranges = reduced.map((b, i) => ({start: i, end: i, centroid: b.centroid, size: b.size}));
  while (ranges.length > target) {
    let closest = 0;
    let smallest = Infinity;
    for (let i = 0; i < ranges.length - 1; i++) {
      const distance = ranges[i + 1].centroid - ranges[i].centroid;
      if (distance < smallest) {
        closest = i;
        smallest = distance;
      }
    }
    const [a, b] = [ranges[closest], ranges[closest + 1]];
    a.start = Math.min(a.start, b.start);
    a.end = Math.max(a.end, b.end);
    if (a.size + b.size > 0) {
      a.centroid = ((a.centroid * a.size) + (b.centroid * b.size)) / (a.size + b.size);
      a.size += b.size;
    }
    ranges.splice(closest + 1, 1);
  }
  reduced = mergeWithPlan(reduced, ranges.map(r => [r.start, r.end]));
  // The final reduce: merge buckets with the same min, then split overlaps at the midpoint.
  const sameMin: [number, number, number][] = reduced.map((b, i) => [i, i, b.min]);
  for (let i = 0; i < sameMin.length - 1;) {
    if (sameMin[i][2] === sameMin[i + 1][2]) {
      sameMin[i][1] = sameMin[i + 1][1];
      sameMin.splice(i + 1, 1);
    } else i++;
  }
  reduced = mergeWithPlan(reduced, sameMin.map(([s, e]) => [s, e]));
  for (let i = 1; i < reduced.length; i++) {
    if (reduced[i].min < reduced[i - 1].max) {
      reduced[i].min = (reduced[i - 1].max + reduced[i].min) / 2;
      reduced[i - 1].max = reduced[i].min;
    }
  }
  return reduced.map(b => ({min: new PyFloat(b.min), key: new PyFloat(b.centroid), max: new PyFloat(b.max), doc_count: b.size}));
}
