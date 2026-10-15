export type Dataset = "opportunities" | "exclusions" | "entities";
export function dataFreshness(kind: Dataset, fileDate: string | null | undefined, now = new Date()) {
  const threshold = kind === "entities" ? 40 * 24 : kind === "exclusions" ? 36 : 30;
  const timestamp = fileDate && /^\d{4}-\d{2}-\d{2}$/.test(fileDate) ? Date.parse(fileDate + "T00:00:00Z") : NaN;
  const valid = Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === fileDate;
  const age = valid ? Math.max(0, (now.getTime() - timestamp) / 3_600_000) : null;
  const stale = age === null || age > threshold;
  return {
    stale, file_age_hours: age === null ? null : Math.round(age * 100) / 100,
    stale_after_hours: threshold,
    freshness_basis: "Source file date at 00:00 UTC; posting time is not stored, so age is conservative and is not based on load time.",
    notes: !stale ? [] : [age === null
      ? `SAM.gov ${kind} freshness is unavailable because no valid source file date is loaded. Confirm current information on SAM.gov.`
      : `STALE SAM.gov ${kind} data: the ${fileDate} public file is older than ${kind === "entities" ? "40 days" : `${threshold} hours`}. Refresh may be delayed; confirm current information on SAM.gov.`],
  };
}
export function noMatchSummary(fileDate: string | null | undefined) {
  return `No record matched these filters in ${fileDate ? `the ${fileDate} public file` : "a loaded public file"}. This is not a clearance or eligibility determination; confirm on SAM.gov.`;
}
export function entityNoMatchSummary(fileDate: string | null | undefined) {
  return `${noMatchSummary(fileDate)} SAM.gov lets registrants hide their record from public view, and those records are not in the public file, so no match does not mean the entity is unregistered. Confirm on SAM.gov with federal access, or ask the vendor for its UEI.`;
}
