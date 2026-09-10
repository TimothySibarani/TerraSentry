import { useCallback, useEffect, useMemo, useState } from "react";
import Dossier from "./Dossier.jsx";
import Overview from "./Overview.jsx";
import { getPortfolio } from "../lib/api.js";
import { BANDS, bandLabel, fmt } from "../lib/format.js";

/**
 * The workstation shell: a persistent rail beside a canvas.
 *
 * Selecting a supplier used to be a page navigation, which meant losing the queue and
 * your place in it. Here the rail stays put and only the canvas changes, while the URL
 * still tracks the selection — so a supplier is still linkable and the browser Back
 * button still does what it looks like it does.
 */
export default function Workstation() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getPortfolio(controller.signal)
      .then(setData)
      .catch((e) => e.name !== "AbortError" && setError(e.message));
    return () => controller.abort();
  }, []);

  // URL is the source of truth for selection, so Back, Forward and a pasted link all
  // behave the same way.
  useEffect(() => {
    const read = () => setSelected(new URLSearchParams(window.location.search).get("id"));
    read();
    window.addEventListener("popstate", read);
    return () => window.removeEventListener("popstate", read);
  }, []);

  const select = useCallback((id) => {
    const url = id ? `${window.location.pathname}?id=${encodeURIComponent(id)}` : window.location.pathname;
    window.history.pushState({ id }, "", url);
    setSelected(id);
  }, []);

  const needle = filter.trim().toLowerCase();
  const match = useCallback(
    (r) => !needle || r.legal_name.toLowerCase().includes(needle) || r.supplier_id.toLowerCase().includes(needle),
    [needle]
  );
  const groups = useMemo(
    () =>
      (data?.groups || [])
        .map((g) => ({ ...g, suppliers: g.suppliers.filter(match) }))
        .filter((g) => g.suppliers.length),
    [data, match]
  );
  const exceptions = useMemo(() => (data?.exceptions || []).filter(match), [data, match]);

  const t = data?.totals;

  return (
    <div className="shell">
      <div className="bar">
        <span className="mark">Terra<em>Sentry</em></span>
        {t && (
          <div className="figs">
            <Fig n={t.screened} label="screened" />
            <Fig n={t.exceptions} label="need a decision" tone="alert" />
            <Fig n={t.needs_documents} label="awaiting documents" tone="warn" />
            <Fig n={`${t.volume_covered_pct}%`} label="volume with issuable DDS" />
          </div>
        )}
        <div className="spacer" />
        {selected && <button onClick={() => select(null)}>Close</button>}
      </div>

      <nav className="rail" aria-label="Work queue and supply base">
        {error && <div className="empty" style={{ color: "var(--nogo)" }}>{error}</div>}
        {!data && !error && <div className="empty">Screening the supply base…</div>}

        {data && (
          <>
            <div className="filter">
              <input
                type="search"
                value={filter}
                placeholder="Filter by name or id"
                aria-label="Filter suppliers by name or id"
                onChange={(e) => setFilter(e.target.value)}
              />
            </div>

            <h3>
              Needs a decision
              <span>{exceptions.length}</span>
            </h3>
            {exceptions.length === 0 && (
              <div className="railempty">
                {needle ? "No match in the queue." : "Queue is clear."}
              </div>
            )}
            {exceptions.map((r) => (
              <QueueItem key={r.supplier_id} r={r} active={selected === r.supplier_id} onSelect={select} showWhy />
            ))}

            <h3>
              Supply base
              <span>{groups.reduce((n, g) => n + g.suppliers.length, 0)}</span>
            </h3>
            {groups.length === 0 && needle && (
              <div className="railempty">Nothing matches “{filter}”.</div>
            )}
            {groups.map((g) => (
              <details key={g.id} className="grp" open={g.exceptions > 0 || Boolean(needle)}>
                <summary>
                  <span className={`bd ${g.worst_band}`} />
                  <span className="gn">{g.name}</span>
                  <span className="gc">{g.supplier_count}</span>
                </summary>
                {g.suppliers.map((r) => (
                  <QueueItem key={r.supplier_id} r={r} active={selected === r.supplier_id} onSelect={select} />
                ))}
              </details>
            ))}
          </>
        )}
      </nav>

      <main className="canvas">
        {selected ? (
          <Dossier key={selected} supplierId={selected} />
        ) : data ? (
          <Overview data={data} onSelect={select} selected={selected} />
        ) : null}
      </main>

      <div className="status">
        <span><b>Tree cover</b> Hansen GFC · cutoff 2020-12-31</span>
        <span><b>Fire</b> NASA FIRMS VIIRS_SNPP_SP</span>
        <span><b>Entities</b> synthetic registry, not a live feed</span>
        <span><b>Rubric</b> deterministic, no model</span>
        {data && <span><b>Screened</b> {data.generated_at.replace("T", " ").replace("+00:00", "Z")}</span>}
      </div>
    </div>
  );
}

function Fig({ n, label, tone = "" }) {
  return (
    <span className={`fig ${tone}`}>
      <b>{n}</b>
      {label}
    </span>
  );
}

function QueueItem({ r, active, onSelect, showWhy = false }) {
  return (
    <button
      type="button"
      className="q"
      aria-current={active}
      aria-label={`${r.legal_name}, ${bandLabel(r.band)}${r.score === null ? "" : `, score ${r.score}`}`}
      onClick={() => onSelect(r.supplier_id)}
    >
      <span className="qtop">
        <span className={`bd ${r.band}`} />
        <span className="qname">{r.legal_name}</span>
        <span className="qscore">{r.score === null ? "—" : r.score}</span>
      </span>
      {showWhy && <span className="qwhy">{r.reason}</span>}
      <span className="qid">{r.supplier_id}</span>
    </button>
  );
}

export { BANDS, fmt };
