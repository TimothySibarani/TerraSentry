import { useEffect, useRef, useState } from "react";
import EvidenceMap from "./EvidenceMap.jsx";
import { streamScreening } from "../lib/api.js";
import { bandLabel, facts } from "../lib/format.js";

/**
 * One supplier's dossier, streamed live.
 *
 * Reached from a portfolio row, with the supplier id in the URL so the page can be
 * bookmarked and shared -- the previous single-page panel could not be linked to at all.
 */
export default function SupplierDetail({ supplierId }) {
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
    // Re-running on a pacing change would restart the stream mid-demo; the button does that.
  }, [supplierId]);

  const blocked = result?.blocked;

  return (
    <main>
      <div className="col">
        <section>
          <h2>
            Evidence map
            <small>
              <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input type="checkbox" checked={paced} onChange={(e) => setPaced(e.target.checked)} />
                paced
              </label>
            </small>
          </h2>
          {!result && <div className="map-empty">Running…</div>}
          {blocked && (
            <div className="map-empty">
              Geometry cannot be mapped — it did not pass validation.
              <br />
              <span style={{ color: "var(--bad)" }}>{result.problems?.[0] || "invalid geometry"}</span>
            </div>
          )}
          {result && !blocked && result.map && <EvidenceMap layers={result.map} />}
        </section>

        <section>
          <h2>
            Agent reasoning
            <small>
              <button className="ghost" onClick={() => run(paced)} disabled={running}>
                {running ? "Running…" : "Re-run"}
              </button>
            </small>
          </h2>
          {error && <div className="empty" style={{ color: "var(--bad)" }}>{error}</div>}
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
              Steps are real; the display is paced for legibility. Each step shows its true
              elapsed time.
            </div>
          )}
        </section>
      </div>

      <div className="col">
        <section>
          <h2>Risk assessment</h2>
          <div className="body">
            {!result && <div className="empty" style={{ padding: "8px 0" }}>No run yet.</div>}
            {blocked && <BlockedScore result={result} />}
            {result && !blocked && <Score a={result.assessment} />}
          </div>
        </section>

        <section>
          <h2>Due diligence statement</h2>
          {!result && <div className="empty">No run yet.</div>}
          {blocked && <BlockedDds result={result} />}
          {result && !blocked && <Dds dds={result.dds} />}
        </section>

        <section>
          <h2>
            Evidence ledger{" "}
            <small>{result?.evidence ? `(${result.evidence.evidence_count})` : ""}</small>
          </h2>
          {!result && <div className="empty">No run yet.</div>}
          {result?.evidence && <Ledger ledger={result.evidence} />}
          <div className="note">
            Every claim carries a source and a raw artifact. Claims without one are rejected
            before the dossier is issued.
          </div>
        </section>
      </div>
    </main>
  );
}

function Score({ a }) {
  if (!a) return null;
  return (
    <>
      <div className="scorewrap">
        <div className="score">{a.score}</div>
        <div>
          <span className={`pill ${a.recommendation}`}>{bandLabel(a.recommendation)}</span>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
            Computed by the deterministic rubric — not by a model.
          </div>
        </div>
      </div>
      <div className="comp">
        {a.components.map((c) => (
          <div key={c.dimension} className="comp-row">
            <div className="comp-head">
              <span className="dim">{c.dimension}</span>
              <span className="val">−{c.penalty} / {c.max_penalty}</span>
            </div>
            <div className="bar">
              <span style={{ width: `${((c.penalty / (c.max_penalty || 1)) * 100).toFixed(1)}%` }} />
            </div>
            {c.reasons.length > 0 && (
              <ul className="reasons">{c.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
            )}
          </div>
        ))}
      </div>
      {a.hard_gates.length > 0 && (
        <div className="gate">
          <b>HARD GATES APPLIED — SCORE CAPPED AT 59</b>
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
        <div className="score" style={{ color: "var(--bad)" }}>—</div>
        <div>
          <span className="pill BLOCKED">BLOCKED</span>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
            No score computed. Geometry gates every later step, so nothing downstream can be
            trusted.
          </div>
        </div>
      </div>
      <div className="gate">
        <b>WHY THE ASSESSMENT STOPPED</b>
        <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
          {(result.problems || []).map((p, i) => <li key={i}>{p}</li>)}
        </ul>
      </div>
    </>
  );
}

function BlockedDds({ result }) {
  return (
    <>
      <div className="body" style={{ paddingBottom: 4 }}>
        <div style={{ color: "var(--bad)", fontWeight: 700, marginBottom: 4 }}>
          Not issuable — assessment blocked
        </div>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          A statement cannot be drafted without a usable plot geometry.
        </div>
      </div>
      <div className="gap">
        <code>GEOMETRY_UNUSABLE</code>
        <div className="req">{result.required_action || "Request a valid WGS84 polygon."}</div>
      </div>
    </>
  );
}

function Dds({ dds }) {
  if (!dds) return null;
  if (dds.issued) {
    return (
      <>
        <div className="body">
          <div style={{ color: "var(--accent)", fontWeight: 700, marginBottom: 6 }}>Draft issuable</div>
          <div style={{ fontSize: 13.5, color: "var(--muted)" }}>
            Negligible-risk conclusion supported by the evidence. Still requires review and
            signature by an authorised human.
          </div>
        </div>
        <details className="ev">
          <summary>TRACES-aligned statement (JSON)</summary>
          <pre>{JSON.stringify(dds.statement, null, 2)}</pre>
        </details>
      </>
    );
  }
  return (
    <>
      <div className="body" style={{ paddingBottom: 4 }}>
        <div style={{ color: "var(--flag)", fontWeight: 700, marginBottom: 4 }}>
          Not issuable — {dds.gaps.length} gap(s)
        </div>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          A request list procurement can act on, not a rejection letter.
        </div>
      </div>
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
