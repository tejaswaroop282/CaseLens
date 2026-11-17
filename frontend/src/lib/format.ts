// Display helpers. All times are UTC.

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 16)} UTC`;
}

export function fmtTime(iso: string | null | undefined): string {
  return iso ? new Date(iso).toISOString().slice(11, 16) : "—";
}

export function fmtWindow(start: string, end: string): string {
  const s = new Date(start), e = new Date(end);
  const sameDay = s.toISOString().slice(0, 10) === new Date(e.getTime() - 1).toISOString().slice(0, 10);
  const midnight = (d: Date) => d.toISOString().slice(11, 16) === "00:00";
  if (sameDay) return `${s.toISOString().slice(0, 10)} · ${fmtTime(start)}–${fmtTime(end)} UTC`;
  if (midnight(s) && midnight(e)) return `${s.toISOString().slice(0, 10)} → ${e.toISOString().slice(0, 10)}`;   // whole days
  return `${fmtDateTime(start)} → ${fmtDateTime(end)}`;
}

export function fmtPct(x: number | null | undefined, digits = 1): string {
  return x == null ? "—" : `${(x * 100).toFixed(digits)}%`;
}

export function fmtNum(x: number): string {
  return Number.isInteger(x) ? x.toLocaleString("en-US") : x.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

export const directionLabel = (d: "out" | "in" | null | undefined) =>
  d === "out" ? "Fan-out" : d === "in" ? "Fan-in" : "Unsupported";

export const verdictLabel: Record<string, string> = {
  likely_legitimate: "Likely legitimate",
  needs_review: "Needs review",
  likely_suspicious: "Likely suspicious",
};

export const decisionLabel: Record<string, string> = { dismiss: "Dismissed", escalate: "Escalated", need_info: "Needs info" };

/** "c_fatf_cyber_enabled_fraud_2023_0065_001" -> { doc: "fatf cyber enabled fraud 2023", page: 65 } */
export function parseChunkId(id: string): { doc: string; page: number | null } {
  const m = /^c_(.+)_(\d{4})_(\d{3})$/.exec(id);
  return m ? { doc: m[1].replace(/_/g, " "), page: Number(m[2]) } : { doc: id, page: null };
}
