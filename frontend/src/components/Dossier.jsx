import { useEffect, useRef, useState } from "react";
import EvidenceMap from "./EvidenceMap.jsx";
import { streamScreening } from "../lib/api.js";
import { bandLabel, facts } from "../lib/format.js";

/**
 * One supplier's dossier, laid out as a bento rather than a stack.
 *
 * Sizes follow importance instead of a uniform grid: the map spans the full width and is
 * the largest thing on screen, because the evidence here is spatial; reasoning and score
 * sit side by side beneath it at different widths; the ledger runs full width at the
 * bottom, where you go only when you want to verify something.
 */
export default function Dossier({ supplierId }) {
  const [steps, setSteps] = useState([]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [paced, setPaced] = useState(true);
  const [running, setRunning] = useState(false);
  const stopRef = useRef(null);

  const run = (withPacing) => {
    stopRef.current?.();
    setSteps([]);
    setResult(null);
    setError(null);
    setRunning(true);
    stopRef.current = streamScreening(supplierId, {
      pace: withPacing ? 550 : 0,
      onStep: (s) => setSteps((prev) => [...prev, s]),
      onResult: setResult,
      onError: setError,
      onDone: () => setRunning(false),
    });
  };

  useEffect(() => {
    run(paced);
    return () => stopRef.current?.();
    // Toggling the pacing mid-stream would restart it; the Re-run button does that.
  }, [supplierId]);

  const blocked = result?.blocked;

  return (
    <div className="dossier">
      <section className="pane a-map">
        <h2>
          Evidence map
          <small>{result?.supplier || supplierId}</small>
        </h2>
        {!result && <div className="map-empty">Screening…</div>}
        {blocked && (
          <div className="map-empty">
            Geometry cannot be mapped — it did not pass validation.
            <br />
            <span style={{ color: "var(--nogo)" }}>{result.problems?.[0] || "invalid geometry"}</span>
          </div>
        )}
        {result && !blocked && result.map && <EvidenceMap layers={result.map} />}
      </section>

      <section className="pane a-reason">
        <h2>
          Agent reasoning
          <small>
            <label style={{ display: "inline-flex", gap: 5, alignItems: "center", marginRight: 10 }}>
              <input type="checkbox" checked={paced} onChange={(e) => setPaced(e.target.checked)} />
              paced
            </label>
            <button onClick={() => run(paced)} disabled={running}>
              {running ? "Running…" : "Re-run"}
            </button>
          </small>
        </h2>
        {error && <div className="empty" style={{ color: "var(--nogo)" }}>{error}</div>}
        {!steps.length && !error && <div className="empty">Starting…</div>}
        {steps.map((s) => (
          <div key={s.index} className={`step ${s.status}${s.phase === "branch" ? " branch" : ""}`}>
            <div className="dot" />
            <div style={{ minWidth: 0 }}>
              <div className="title">{s.title}</div>
              {s.detail && <div className="detail">{s.detail}</div>}
              <div className="meta">{s.phase} · {s.elapsed_ms} ms</div>
            </div>
          </div>
        ))}
        {paced && (
          <div className="note">
            Steps are real; the display is paced for legibility. Each shows its true elapsed time.
          </div>
        )}
      </section>

      <section className="pane a-score">
        <h2>Assessment</h2>
        <div className="pad">
          {!result && <div style={{ color: "var(--muted)", fontSize: 12.5 }}>Screening…</div>}
          {blocked && <BlockedScore result={result} />}
          {result && !blocked && <Score a={result.assessment} />}
        </div>
        {blocked && <BlockedDds result={result} />}
        {result && !blocked && <Dds dds={result.dds} />}
      </section>

      <section className="pane a-ledger">
        <h2>
          Evidence ledger
          <small>{result?.evidence ? `${result.evidence.evidence_count} claims, each with a source` : ""}</small>
        </h2>
        {!result && <div className="empty">Screening…</div>}
        {result?.evidence && <Ledger ledger={result.evidence} />}
      </section>
    </div>
  );
}

function Score({ a }) {
  if (!a) return null;
  return (
    <>
      <div className="scorewrap">
        <div className="score">{a.score}</div>
        <div>
          <span className={`chip ${a.recommendation}`}>{bandLabel(a.recommendation)}</span>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 5 }}>
            Deterministic rubric — not a model.
          </div>
        </div>
      </div>
      {a.components.map((c) => (
        <div key={c.dimension} className="comp-row">
          <div className="comp-head">
            <span className="dim">{c.dimension}</span>
            <span className="val">−{c.penalty} / {c.max_penalty}</span>
          </div>
          <div className="bar2">
            <span style={{ width: `${((c.penalty / (c.max_penalty || 1)) * 100).toFixed(1)}%` }} />
          </div>
          {c.reasons.length > 0 && (
            <ul className="reasons">{c.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          )}
        </div>
      ))}
      {a.hard_gates.length > 0 && (
        <div className="gate">
          <b>HARD GATES — SCORE CAPPED AT 59</b>
          {a.hard_gates.map((g, i) => <div key={i}>• {g}</div>)}
        </div>
      )}
    </>
  );
}

function BlockedScore({ result }) {
  return (
    <>
      <div className="scorewrap">
        <div className="score" style={{ color: "var(--blocked)" }}>—</div>
        <div>
          <span className="chip BLOCKED">BLOCKED</span>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 5 }}>
            Not assessable. Geometry gates every later step.
          </div>
        </div>
      </div>
      <div className="gate">
        <b>WHY IT STOPPED</b>
        <ul style={{ margin: "4px 0 0", paddingLeft: 16 }}>
          {(result.problems || []).map((p, i) => <li key={i}>{p}</li>)}
        </ul>
      </div>
    </>
  );
}

function BlockedDds({ result }) {
  return (
    <div className="gap">
      <code>GEOMETRY_UNUSABLE</code>
      <div className="req">{result.required_action || "Request a valid WGS84 polygon."}</div>
    </div>
  );
}

function Dds({ dds }) {
  if (!dds) return null;
  if (dds.issued) {
    return (
      <div className="gap">
        <code>ISSUABLE</code>
        <div className="req">Negligible-risk conclusion supported by the evidence.</div>
        <div className="why">Still requires review and signature by an authorised human.</div>
      </div>
    );
  }
  return (
    <>
      <div className="note">Not issuable — {dds.gaps.length} gap(s). A request list, not a rejection.</div>
      {dds.gaps.map((g, i) => (
        <div key={i} className="gap">
          <code>{g.code}</code>
          <div className="req">{g.requirement}</div>
          <div className="why">{g.why}</div>
        </div>
      ))}
    </>
  );
}

function Ledger({ ledger }) {
  return (
    <>
      {ledger.evidence.map((e) => {
        const rows = facts(e.artifact);
        return (
          <details key={e.claim_id} className="ev">
            <summary>
              {e.claim}
              <span className="src">{e.source} · {e.claim_id}</span>
            </summary>
            {rows.length > 0 && (
              <dl className="facts">
                {rows.map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            )}
            <details className="raw">
              <summary>Raw artifact (JSON)</summary>
              <pre>{JSON.stringify(e.artifact, null, 2)}</pre>
            </details>
          </details>
        );
      })}
    </>
  );
}
