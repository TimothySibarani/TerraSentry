import { useState } from "react";
import { BANDS, BAND_COLOR, bandLabel, fmt } from "../lib/format.js";

/**
 * Charts for the supply base.
 *
 * Two decisions worth stating, because both are easy to get wrong:
 *
 * 1. Loss and fire are NOT plotted together. They are hectares and detections — different
 *    units — and a dual axis would invent a relationship the data does not state. They
 *    are aligned small multiples on a shared year axis instead, so a reader can see that
 *    2023 spikes in both without the chart claiming one caused the other.
 *
 * 2. Every chart has a table underneath it. A bar you can only read by pixel-length is
 *    not evidence, and this is a compliance tool.
 */

const PAD = { l: 40, r: 10, t: 8, b: 20 };

export function YearBars({ title, unit, data, years, format = (v) => v }) {
  const [hover, setHover] = useState(null);

  const values = years.map((y) => data[y] || 0);
  const max = Math.max(...values, 1);
  const W = 420;
  const H = 132;
  const plotW = W - PAD.l - PAD.r;
  const plotH = H - PAD.t - PAD.b;
  const slot = plotW / Math.max(years.length, 1);
  // Thin marks: cap the width so bars stay bars. Letting them grow with the container
  // turns a five-year series into a row of blocks and reads as decoration.
  const barW = Math.min(26, Math.max(6, slot - 6));
  const peak = values.indexOf(Math.max(...values));

  return (
    <figure className="chart">
      <figcaption>
        {title} <span>{unit}</span>
      </figcaption>
      <div className="chartbody">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}, ${unit}, by year`}>
          {/* Recessive axis: one baseline, no grid cage. */}
          <line x1={PAD.l} y1={PAD.t + plotH} x2={W - PAD.r} y2={PAD.t + plotH} className="axis" />
          <text x={PAD.l - 6} y={PAD.t + 8} className="tick" textAnchor="end">{format(max)}</text>
          <text x={PAD.l - 6} y={PAD.t + plotH} className="tick" textAnchor="end">0</text>

          {years.map((y, i) => {
            const v = data[y] || 0;
            const h = (v / max) * plotH;
            const x = PAD.l + i * slot + (slot - barW) / 2;
            const yTop = PAD.t + plotH - h;
            return (
              <g key={y}
                 onMouseEnter={() => setHover({ year: y, value: v })}
                 onMouseLeave={() => setHover(null)}>
                {/* Hit target larger than the mark. */}
                <rect x={PAD.l + i * slot} y={PAD.t} width={slot} height={plotH} className="hit" />
                {/* Clamp only enough to keep a non-zero value visible. A larger floor
                    would make 2.1 and 4.6 render identically, which is a chart telling a
                    small lie to look tidier. The tooltip and the table carry the exact
                    figures; the bars carry the shape. */}
                <rect x={x} y={yTop} width={barW} height={Math.max(h, v > 0 ? 1.5 : 0)}
                      rx={h > 6 ? 3 : 1} className={`bar${hover?.year === y ? " on" : ""}`} />
                <text x={x + barW / 2} y={H - 6} className="tick" textAnchor="middle">{y}</text>
                {/* Label the peak only. A number on every bar is noise. */}
                {i === peak && v > 0 && (
                  <text x={x + barW / 2} y={yTop - 4} className="peak" textAnchor="middle">{format(v)}</text>
                )}
              </g>
            );
          })}
        </svg>
        {hover && (
          <div className="tip">
            <b>{hover.year}</b> {format(hover.value)} {unit}
          </div>
        )}
      </div>
      {max > 0 && values.filter((v) => v > 0).length > 1 && (
        <p className="chartnote">
          {years[peak]} accounts for{" "}
          {Math.round((values[peak] / values.reduce((a, b) => a + b, 0)) * 100)}% of the
          period. Exact figures in the table.
        </p>
      )}
      <details className="tbl">
        <summary>Table</summary>
        <table>
          <thead><tr><th>Year</th><th>{unit}</th></tr></thead>
          <tbody>
            {years.map((y) => <tr key={y}><td>{y}</td><td>{format(data[y] || 0)}</td></tr>)}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

export function VolumeByBand({ volume }) {
  const [hover, setHover] = useState(null);
  const total = BANDS.reduce((n, b) => n + (volume[b] || 0), 0) || 1;

  return (
    <figure className="chart wide">
      <figcaption>
        Monthly volume by band <span>m³</span>
      </figcaption>
      <div className="chartbody">
        <div className="vbar" onMouseLeave={() => setHover(null)}>
          {BANDS.filter((b) => volume[b]).map((b) => (
            <div
              key={b}
              className={`vseg ${b}`}
              style={{ width: `${((volume[b] || 0) / total) * 100}%`, background: BAND_COLOR[b] }}
              onMouseEnter={() => setHover(b)}
              title={`${bandLabel(b)}: ${fmt(volume[b])} m³`}
            />
          ))}
        </div>
        {hover && (
          <div className="tip">
            <b>{bandLabel(hover)}</b> {fmt(volume[hover])} m³ ·{" "}
            {((volume[hover] / total) * 100).toFixed(1)}%
          </div>
        )}
      </div>
      <p className="chartnote">
        Coverage is volume-weighted, so a handful of large suppliers move it far more than
        a long tail of smallholders does.
      </p>
      <details className="tbl">
        <summary>Table</summary>
        <table>
          <thead><tr><th>Band</th><th>m³/month</th><th>Share</th></tr></thead>
          <tbody>
            {BANDS.filter((b) => volume[b]).map((b) => (
              <tr key={b}>
                <td><i className="bd" style={{ background: BAND_COLOR[b] }} /> {bandLabel(b)}</td>
                <td>{fmt(volume[b])}</td>
                <td>{((volume[b] / total) * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
