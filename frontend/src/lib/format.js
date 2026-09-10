export const BANDS = ["GO", "CONDITIONAL", "ESCALATE", "NO_GO", "BLOCKED"];

export const BAND_COLOR = {
  GO: "var(--go)",
  CONDITIONAL: "var(--conditional)",
  ESCALATE: "var(--escalate)",
  NO_GO: "var(--nogo)",
  BLOCKED: "var(--blocked)",
};

/** "NO_GO" reads as shouting in a table cell; "NO-GO" does not. */
export const bandLabel = (b) => String(b || "").replace("_", "-");

export const fmt = (n) => (n ?? 0).toLocaleString("en-US");

export const label = (k) =>
  String(k).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

/**
 * Flatten an evidence artifact into readable key/value pairs.
 *
 * Raw JSON is the right thing for an auditor and the wrong thing on a projector, so the
 * panel shows this first and keeps the untouched artifact one disclosure deeper.
 */
export function facts(artifact, limit = 8) {
  const out = [];
  const walk = (obj, prefix = "") => {
    for (const [k, v] of Object.entries(obj || {})) {
      if (out.length >= limit || v === null || v === undefined || v === "") continue;
      if (Array.isArray(v)) {
        if (v.length && typeof v[0] !== "object") {
          out.push([label(prefix + k), v.slice(0, 3).join(", ") + (v.length > 3 ? ` +${v.length - 3} more` : "")]);
        } else if (v.length) {
          out.push([label(prefix + k), `${v.length} item(s)`]);
        }
      } else if (typeof v === "object") {
        walk(v, k + " ");
      } else if (typeof v === "boolean") {
        out.push([label(prefix + k), v ? "yes" : "no"]);
      } else {
        out.push([label(prefix + k), String(v)]);
      }
    }
  };
  walk(artifact);
  return out;
}
