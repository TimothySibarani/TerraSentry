import { useMemo, useState } from "react";

/**
 * Evidence map — deliberately no mapping library.
 *
 * The view has a fixed extent (one concession and its immediate surroundings), so slippy
 * map machinery buys nothing, and a CDN dependency is exactly what dies when the demo
 * room's wifi does. This is Web Mercator arithmetic and SVG, and it works offline.
 *
 * Layers, bottom to top: dated satellite composites revealed by a swipe, tree-cover loss
 * overlay, the concession polygon, adjacent parcels, and fire hotspots sized by radiative
 * power. Imagery is optional — with no cached composite the vector layers still draw,
 * which is the normal state until the Sentinel pipeline lands.
 */

const R = 6378137;
const mercX = (lon) => (R * lon * Math.PI) / 180;
const mercY = (lat) => {
  const phi = (Math.max(-85.05, Math.min(85.05, lat)) * Math.PI) / 180;
  return R * Math.log(Math.tan(Math.PI / 4 + phi / 2));
};

function ringsOf(feature) {
  const g = feature?.type === "Feature" ? feature.geometry : feature;
  if (!g) return [];
  if (g.type === "Polygon") return g.coordinates;
  if (g.type === "MultiPolygon") return g.coordinates.flat();
  return [];
}

export default function EvidenceMap({ layers }) {
  const [swipe, setSwipe] = useState(0.5);
  const [showLoss, setShowLoss] = useState(true);
  const [showHotspots, setShowHotspots] = useState(true);

  const geo = useMemo(() => {
    const polys = [layers?.plot, ...(layers?.adjacent || [])].filter(Boolean);
    if (!polys.length) return null;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const f of polys) {
      for (const ring of ringsOf(f)) {
        for (const [lon, lat] of ring) {
          const x = mercX(lon), y = mercY(lat);
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
    }
    // Pad so the plot never touches the frame edge.
    const padX = (maxX - minX) * 0.08 || 100;
    const padY = (maxY - minY) * 0.08 || 100;
    const ext = { minX: minX - padX, maxX: maxX + padX, minY: minY - padY, maxY: maxY + padY };

    const W = 1000;
    const H = Math.max(360, Math.round((W * (ext.maxY - ext.minY)) / (ext.maxX - ext.minX)));
    const sx = (lon) => ((mercX(lon) - ext.minX) / (ext.maxX - ext.minX)) * W;
    const sy = (lat) => H - ((mercY(lat) - ext.minY) / (ext.maxY - ext.minY)) * H;
    const path = (f) =>
      ringsOf(f)
        .map((ring) => "M" + ring.map(([lon, lat]) => `${sx(lon).toFixed(1)},${sy(lat).toFixed(1)}`).join("L") + "Z")
        .join(" ");

    return { ext, W, H, sx, sy, path };
  }, [layers]);

  if (!geo) return <div className="map-empty">No geometry to display.</div>;

  const { ext, W, H, sx, sy, path } = geo;
  const scenes = (layers.imagery || []).slice(0, 2);
  const hasImagery = scenes.length === 2;
  const frp = (v) => 3 + Math.min(9, Math.sqrt(Math.max(0, v || 0)) * 1.6);

  const place = (scene) => {
    const [w, s, e, n] = scene.bounds;
    const x = ((mercX(w) - ext.minX) / (ext.maxX - ext.minX)) * W;
    const x2 = ((mercX(e) - ext.minX) / (ext.maxX - ext.minX)) * W;
    const y = H - ((mercY(n) - ext.minY) / (ext.maxY - ext.minY)) * H;
    const y2 = H - ((mercY(s) - ext.minY) / (ext.maxY - ext.minY)) * H;
    return { x, y, width: x2 - x, height: y2 - y };
  };

  return (
    <>
      <div className="map-frame">
        <svg viewBox={`0 0 ${W} ${H}`} className="map-svg" preserveAspectRatio="xMidYMid meet"
             role="img" aria-label="Concession boundary with tree-cover loss and fire hotspots">
          <defs>
            <clipPath id="swipeClip">
              <rect x="0" y="0" width={W * swipe} height={H} />
            </clipPath>
            <pattern id="hatch" width="7" height="7" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
              <line x1="0" y1="0" x2="0" y2="7" className="map-hatch" strokeWidth="2.5" opacity="0.55" />
            </pattern>
          </defs>

          {hasImagery ? (
            <>
              <image href={scenes[1].url} {...place(scenes[1])} preserveAspectRatio="none" />
              <image href={scenes[0].url} {...place(scenes[0])} preserveAspectRatio="none"
                     clipPath="url(#swipeClip)" />
            </>
          ) : (
            <>
              <rect width={W} height={H} className="map-ground" />
              <text x={W / 2} y={26} textAnchor="middle" className="map-note">
                no cached satellite composite — run scripts/fetch_imagery.py
              </text>
            </>
          )}

          {showLoss && layers.loss_overlay && (
            <image href={layers.loss_overlay.url} {...place(layers.loss_overlay)}
                   preserveAspectRatio="none" opacity="0.75" />
          )}

          {(layers.adjacent || []).map((f, i) => (
            <path key={i} d={path(f)} className="map-adjacent" />
          ))}

          <path d={path(layers.plot)} className="map-plot-halo" />
          <path d={path(layers.plot)} className="map-plot" />

          {showHotspots && (
            <>
              {(layers.hotspots_buffer || []).map((h, i) => (
                <circle key={`b${i}`} cx={sx(h.lon).toFixed(1)} cy={sy(h.lat).toFixed(1)}
                        r={frp(h.frp).toFixed(1)} className="map-hs-buffer">
                  <title>{`${h.acq_date} · buffer · FRP ${h.frp}`}</title>
                </circle>
              ))}
              {(layers.hotspots_inside || []).map((h, i) => (
                <circle key={`i${i}`} cx={sx(h.lon).toFixed(1)} cy={sy(h.lat).toFixed(1)}
                        r={frp(h.frp).toFixed(1)}
                        className={String(h.confidence).toLowerCase() === "h" ? "map-hs-high" : "map-hs"}>
                  <title>{`${h.acq_date} · inside plot · FRP ${h.frp}`}</title>
                </circle>
              ))}
            </>
          )}
        </svg>
      </div>

      <div className="map-controls">
        {hasImagery ? (
          <label className="map-swipe">
            <span>{scenes[0].date}</span>
            <input type="range" min="0" max="100" value={swipe * 100}
                   aria-label="Reveal the earlier satellite composite"
                   onChange={(e) => setSwipe(e.target.value / 100)} />
            <span>{scenes[1].date}</span>
          </label>
        ) : (
          <span className="map-hint">Swipe comparison appears once two composites are cached.</span>
        )}
        <label>
          <input type="checkbox" checked={showLoss} onChange={(e) => setShowLoss(e.target.checked)} />
          loss overlay
        </label>
        <label>
          <input type="checkbox" checked={showHotspots} onChange={(e) => setShowHotspots(e.target.checked)} />
          hotspots
        </label>
      </div>

      <div className="map-legend">
        <span><i className="k-plot" />concession</span>
        <span><i className="k-adj" />adjacent parcel</span>
        <span><i className="k-hs-high" />hotspot, high confidence</span>
        <span><i className="k-hs" />hotspot</span>
        <span><i className="k-hs-buf" />hotspot outside plot</span>
      </div>
    </>
  );
}
