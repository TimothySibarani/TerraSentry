import { useEffect, useState } from "react";
import { BANDS, BAND_COLOR, bandLabel, fmt } from "../lib/format.js";
import { getPortfolio } from "../lib/api.js";

/**
 * The supply base: totals, risk distribution, exception queue, and the full base grouped
 * by aggregator.
 *
 * This is the home screen on purpose. Nobody reviews suppliers one at a time -- a mill
 * with hundreds of smallholders works by exception, and the single-supplier view is the
 * drill-down, not the entry point.
 */
export default function PortfolioView() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getPortfolio(controller.signal)
      .then(setData)
      .catch((e) => e.name !== "AbortError" && setError(e.message))
      .finally(() => setLoading(false));
    return () => controller.abort();
  };

  useEffect(load, []);

  if (loading && !data) return <div className="empty">Screening the supply base…</div>;
  if (error) return <div className="empty" style={{ color: "var(--bad)" }}>{error}</div>;
  if (!data) return null;

  const t = data.totals;
  const total = t.suppliers || 1;

  return (
    <div className="wrap">
      <div className="kpis">
        <Kpi n={t.screened} label="suppliers screened" tone="good" />
        <Kpi n={t.exceptions} label="need a decision now" tone={t.exceptions ? "bad" : "good"} />
        <Kpi n={t.needs_documents} label="waiting on documents" tone={t.needs_documents ? "warn" : "good"} />
        <Kpi n={`${t.volume_covered_pct}%`} label="of volume with an issuable DDS"
             tone={t.volume_covered_pct > 80 ? "good" : "warn"} />
        <Kpi n={t.smallholders} label="smallholder plots" />
        <Kpi n={t.point_rule_plots} label="under 4 ha — GPS point rule, no polygon required" />
      </div>

      <section>
        <h2>
          Risk distribution
          <small>screened {data.generated_at.replace("T", " ").replace("+00:00", " UTC")}</small>
        </h2>
        <div className="body">
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
                <i style={{ background: BAND_COLOR[b] }} />
                {bandLabel(b)} {data.bands[b] || 0}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section>
        <h2>Needs a decision <small>escalate · no-go · blocked</small></h2>
        {data.exceptions.length ? (
          <SupplierTable rows={data.exceptions} withAction />
        ) : (
          <div className="empty" style={{ color: "var(--accent)" }}>
            Nothing needs a decision. Every exception is cleared.
          </div>
        )}
      </section>

      <section>
        <h2>Supply base <small>{data.groups.length} groups</small></h2>
        {data.groups.map((g) => (
          <details key={g.id} className="grp" open={g.exceptions > 0}>
            <summary>
              <span className="gname">{g.name}</span>
              <span className={`pill ${g.worst_band}`}>{bandLabel(g.worst_band)}</span>
              <span className="spacer" />
              <span className="gmeta">
                {g.supplier_count} suppliers · {fmt(g.volume_m3_month)} m³
                {g.exceptions ? <> · <b style={{ color: "var(--bad)" }}>{g.exceptions} exception(s)</b></> : null}
              </span>
            </summary>
            <SupplierTable rows={g.suppliers} />
          </details>
        ))}
        <div className="note">
          Everything here is screened by the deterministic rubric — free, and milliseconds per
          supplier. Only ambiguous cases go to the agent, which is what keeps a base of hundreds
          affordable.
        </div>
      </section>
    </div>
  );
}

function Kpi({ n, label, tone = "" }) {
  return (
    <div className={`kpi ${tone}`}>
      <div className="n">{n}</div>
      <div className="l">{label}</div>
    </div>
  );
}

function SupplierTable({ rows, withAction = false }) {
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr>
            <th>Supplier</th>
            <th>Band</th>
            <th className="num">Score</th>
            <th className="num">Area</th>
            <th className="num">m³/mo</th>
            <th>{withAction ? "Why / what to do" : "Finding"}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <SupplierRow key={r.supplier_id} r={r} withAction={withAction} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SupplierRow({ r, withAction }) {
  const href = `/supplier/?id=${encodeURIComponent(r.supplier_id)}`;
  const open = () => { window.location.href = href; };

  return (
    <tr
      className="row"
      tabIndex={0}
      role="button"
      // A row that only answers to a mouse does not exist for keyboard or screen-reader
      // users, so it announces its own state and responds to Enter and Space.
      aria-label={`${r.legal_name}, ${bandLabel(r.band)}${r.score === null ? "" : `, score ${r.score}`}. Open assessment.`}
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      }}
    >
      <td>
        {r.legal_name}
        {r.tier === "smallholder" && <span className="tag">smallholder</span>}
        {r.geolocation_requirement === "point" && <span className="tag">GPS point</span>}
        <div className="sid">{r.supplier_id}</div>
      </td>
      <td><span className={`pill ${r.band}`}>{bandLabel(r.band)}</span></td>
      <td className="num">{r.score === null ? "—" : r.score}</td>
      <td className="num">{r.area_ha === null ? "—" : `${fmt(Math.round(r.area_ha))} ha`}</td>
      <td className="num">{fmt(r.volume_m3_month)}</td>
      <td className="reason">
        {r.reason}
        {withAction && r.action !== "None" && (
          <div style={{ marginTop: 4, color: "var(--flag)" }}>→ {r.action}</div>
        )}
      </td>
    </tr>
  );
}
