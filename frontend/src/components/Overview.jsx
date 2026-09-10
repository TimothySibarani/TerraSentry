import { BANDS, BAND_COLOR, bandLabel, fmt } from "../lib/format.js";

/**
 * The canvas at rest.
 *
 * Two questions get answered here that a scrolling list cannot answer at all: how is the
 * whole base doing, and where is the trouble concentrated. The rail is for working
 * through the queue; this is for comprehending the base.
 *
 * The matrix is the part that scales. A rail listing 500 suppliers is an endless scroll
 * and tells you nothing in aggregate, but 500 cells fit on one screen and the shape of
 * the problem is visible immediately -- including when a single cooperative is carrying
 * most of it, which a flat list actively hides.
 */
export default function Overview({ data, onSelect, selected }) {
  const t = data.totals;
  const total = t.suppliers || 1;

  return (
    <div className="overview">
      <h1>{data.mill?.name || "Supply base"}</h1>
      <p>
        {t.suppliers} suppliers screened against the EUDR rubric, covering{" "}
        {fmt(t.volume_m3_month)} m³ per month. The queue on the left is what still needs a
        human; the matrix below is everyone.
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

      <h2 className="ovh">Every supplier</h2>
      <p className="ovsub">
        One cell each, coloured by band and grouped by who they supply through. Ringed
        cells need a decision. Click any cell to open its dossier.
      </p>
      <div className="matrix">
        {data.groups.map((g) => (
          <div key={g.id} className="mgroup">
            <div className="mlabel">
              <span className="gn">{g.name}</span>
              <span className="gc">
                {g.supplier_count} · {fmt(g.volume_m3_month)} m³
              </span>
            </div>
            <div className="mcells">
              {g.suppliers.map((r) => (
                <button
                  key={r.supplier_id}
                  type="button"
                  className={`cell ${r.band}${["ESCALATE", "NO_GO", "BLOCKED"].includes(r.band) ? " flagged" : ""}`}
                  aria-current={selected === r.supplier_id}
                  aria-label={`${r.legal_name}, ${bandLabel(r.band)}${r.score === null ? "" : `, score ${r.score}`}`}
                  title={`${r.legal_name} — ${bandLabel(r.band)}${r.score === null ? "" : ` · ${r.score}`}\n${r.reason}`}
                  onClick={() => onSelect(r.supplier_id)}
                />
              ))}
            </div>
          </div>
        ))}
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
