import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { HourlyBudget, readBoundedBody, BodyTimeoutError } from '../src/hourly-budget.ts';

function storage(db) {
  return {
    sql: { exec(query, ...params) {
      const statement=db.prepare(query);
      const rows=query.startsWith('SELECT') ? statement.all(...params) : (statement.run(...params), []);
      return {one() { assert.equal(rows.length,1); return rows[0]; }};
    }},
    transactionSync(fn) {db.exec('BEGIN IMMEDIATE');try {const out=fn();db.exec('COMMIT');return out;} catch(error){db.exec('ROLLBACK');throw error;}}
  };
}

test('500 reservations persist across recreated objects and expire on a rolling hour',()=>{
  const db=new DatabaseSync(':memory:');const store=storage(db);
  for(let i=0;i<500;i++) assert.equal(new HourlyBudget(store).reserve(1_000_000+i*600).allowed,true);
  assert.deepEqual(new HourlyBudget(store).reserve(1_300_000),{allowed:false,remaining:0,retryAfter:3300,reason:"hourly"});
  assert.deepEqual(new HourlyBudget(store).reserve(4_600_000),{allowed:true,remaining:0,retryAfter:0,reason:"allowed"});
  assert.equal(db.prepare('SELECT COUNT(*) AS count FROM calc_hourly_attempts_v1').get().count,500);
  db.close();
});

test('parallel callers cannot reserve more than the shared budget',async()=>{
  const db=new DatabaseSync(':memory:');const store=storage(db);
  const results=await Promise.all(Array.from({length:510},async()=>new HourlyBudget(store).reserve(1_000_000)));
  assert.equal(results.filter(r=>r.allowed).length,500);db.close();
});

test('storage failure fails closed',()=>{
  const db=new DatabaseSync(':memory:');const b=new HourlyBudget(storage(db));db.close();
  assert.throws(()=>b.reserve(1_000_000));
});

test('bounded body accepts limit and rejects oversized streaming bodies',async()=>{
  for(const size of [0,65536,65537]) {
    const request=new Request('https://example.test/mcp',{method:'POST',body:new Uint8Array(size)});
    const result=await readBoundedBody(request);
    if(size>65536) assert.equal(result,null);else assert.equal(result.byteLength,size);
  }
});

test('slow request body times out and cancels the stream',async()=>{
  let cancelled=false;
  const stream=new ReadableStream({cancel(){cancelled=true;}});
  const request=new Request('https://example.test/mcp',{method:'POST',body:stream,duplex:'half'});
  await assert.rejects(readBoundedBody(request,10),BodyTimeoutError);
  assert.equal(cancelled,true);
});

test('provider cooldown survives recreation and cannot be shortened',()=>{
  const db=new DatabaseSync(':memory:');const store=storage(db);const first=new HourlyBudget(store);
  first.observeCooldown(2221,1_000_000);first.observeCooldown(10,1_000_000);
  assert.deepEqual(new HourlyBudget(store).reserve(1_300_000),{allowed:false,remaining:500,retryAfter:1921,reason:'provider'});
  assert.equal(new HourlyBudget(store).reserve(3_221_000).allowed,true);
  db.close();
});
