import { BANDS, BAND_COLOR, bandLabel, fmt } from "../lib/format.js";

/**
 * The canvas at rest.
 *
 * With nothing selected the useful question is how the whole base is doing, not what is
 * in any particular row — so the distribution gets to be large and the figures get room,
 * instead of being compressed into another grid of identical tiles.
 */
export default function Overview({ data }) {
  const t = data.totals;
  const total = t.suppliers || 1;

  return (
    <div className="overview">
      <h1>{data.mill?.name || "Supply base"}</h1>
      <p>
        {t.suppliers} suppliers screened against the EUDR rubric, covering{" "}
        {fmt(t.volume_m3_month)} m³ per month. Pick anything in the rail to open its
        dossier; the queue on the left is what still needs a human.
      </p>

      <div className="dist">
        {BANDS.filter((b) => data.bands[b]).map((b) => (
          <div key={b} className={b} style={{ width: `${(data.bands[b] / total) * 100}%` }}
               title={`${bandLabel(b)}: ${data.bands[b]}`}>
            {data.bands[b]}
          </div>
        ))}
      </div>
      <div className="distkey">
        {BANDS.map((b) => (
          <span key={b}>
            <i className="bd" style={{ background: BAND_COLOR[b] }} />
            {bandLabel(b)} {data.bands[b] || 0}
          </span>
        ))}
      </div>

      <div className="bigstats">
        <Stat n={t.exceptions} label="need a decision now" />
        <Stat n={t.needs_documents} label="waiting on a document from the supplier" />
        <Stat n={`${t.volume_covered_pct}%`} label="of volume with an issuable statement" />
        <Stat n={t.smallholders} label="smallholder plots" />
        <Stat n={t.point_rule_plots} label="under 4 ha — a GPS point, not a polygon, under Article 9" />
      </div>
    </div>
  );
}

function Stat({ n, label }) {
  return (
    <div className="bigstat">
      <div className="n">{n}</div>
      <div className="l">{label}</div>
    </div>
  );
}
