/* TerraSentry evidence map — dependency-free.
 *
 * Deliberately not Leaflet. This view has a fixed extent (one concession and its
 * immediate surroundings), so the slippy-map machinery buys nothing, and a CDN
 * dependency is exactly what dies when the demo room wifi does. Everything here is
 * ~300 lines of SVG and Web Mercator arithmetic that works with the network unplugged.
 *
 * What it draws, bottom to top:
 *   1. satellite composites (pre-rendered PNGs, two dates, revealed by a swipe slider)
 *   2. tree-cover loss overlay
 *   3. the concession polygon
 *   4. the inward boundary buffer — where attribution is ambiguous
 *   5. adjacent parcels, highlighted when the ownership branch fires
 *   6. fire hotspots, radius by FRP, colour by inside/outside
 *
 * Imagery is optional. With no cached scenes the map still draws every vector layer,
 * which is what the demo runs on until the Sentinel pipeline lands.
 */

(function (global) {
  "use strict";

  const R = 6378137;

  // -- Web Mercator ------------------------------------------------------
  const merc = {
    x: (lon) => R * (lon * Math.PI) / 180,
    y: (lat) => {
      const phi = (Math.max(-85.05, Math.min(85.05, lat)) * Math.PI) / 180;
      return R * Math.log(Math.tan(Math.PI / 4 + phi / 2));
    },
  };

  function coordsOf(geojson) {
    const g = geojson.type === "Feature" ? geojson.geometry : geojson;
    if (g.type === "Polygon") return g.coordinates;
    if (g.type === "MultiPolygon") return g.coordinates.flat();
    return [];
  }

  function boundsOf(features) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    features.forEach((f) => {
      coordsOf(f).forEach((ring) =>
        ring.forEach(([lon, lat]) => {
          const x = merc.x(lon), y = merc.y(lat);
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        })
      );
    });
    return { minX, minY, maxX, maxY };
  }

  // -- renderer ----------------------------------------------------------

  class EvidenceMap {
    /**
     * @param {HTMLElement} host container element
     * @param {object} layers  pipeline result `.map`
     */
    constructor(host, layers) {
      this.host = host;
      this.layers = layers;
      this.swipe = 0.5;
      this.showLoss = true;
      this.showHotspots = true;
      this.render();
    }

    render() {
      const L = this.layers;
      const polys = [L.plot, ...(L.adjacent || [])].filter(Boolean);
      if (!polys.length) {
        this.host.innerHTML = '<div class="map-empty">No geometry to display.</div>';
        return;
      }

      // Pad the extent so the plot does not touch the frame edge.
      const b = boundsOf(polys);
      const padX = (b.maxX - b.minX) * 0.08 || 100;
      const padY = (b.maxY - b.minY) * 0.08 || 100;
      const ext = {
        minX: b.minX - padX, maxX: b.maxX + padX,
        minY: b.minY - padY, maxY: b.maxY + padY,
      };

      const W = 1000;
      const H = Math.max(360, Math.round((W * (ext.maxY - ext.minY)) / (ext.maxX - ext.minX)));
      const sx = (lon) => ((merc.x(lon) - ext.minX) / (ext.maxX - ext.minX)) * W;
      const sy = (lat) => H - ((merc.y(lat) - ext.minY) / (ext.maxY - ext.minY)) * H;
      this._proj = { sx, sy, W, H, ext };

      const scenes = (L.imagery || []).slice(0, 2);
      const hasImagery = scenes.length === 2;

      const ringPath = (feature) =>
        coordsOf(feature)
          .map((ring) => "M" + ring.map(([lon, lat]) => `${sx(lon).toFixed(1)},${sy(lat).toFixed(1)}`).join("L") + "Z")
          .join(" ");

      const svg = [];
      svg.push(`<svg viewBox="0 0 ${W} ${H}" class="map-svg" preserveAspectRatio="xMidYMid meet">`);
      svg.push(`<defs>
        <clipPath id="swipeClip"><rect id="swipeRect" x="0" y="0" width="${W * this.swipe}" height="${H}"/></clipPath>
        <pattern id="hatch" width="7" height="7" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
          <line x1="0" y1="0" x2="0" y2="7" stroke="#f0b429" stroke-width="2.5" opacity="0.55"/>
        </pattern>
      </defs>`);

      // 1 & 2. imagery, newest underneath, cutoff-date composite revealed by the swipe
      if (hasImagery) {
        const [before, after] = scenes;
        svg.push(this._image(after, ext, W, H, ""));
        svg.push(this._image(before, ext, W, H, ' clip-path="url(#swipeClip)"'));
      } else {
        svg.push(`<rect width="${W}" height="${H}" fill="#0b1a14"/>`);
        svg.push(`<text x="${W / 2}" y="26" text-anchor="middle" class="map-note">
          no cached satellite composite — run scripts/fetch_imagery.py</text>`);
      }

      // 3. loss overlay
      if (this.showLoss && L.loss_overlay) {
        svg.push(this._image(L.loss_overlay, ext, W, H, ' opacity="0.75"'));
      }

      // 4. adjacent parcels
      (L.adjacent || []).forEach((f) => {
        svg.push(`<path d="${ringPath(f)}" class="map-adjacent"/>`);
      });

      // 5. the plot, plus the inward buffer where boundary attribution is ambiguous
      svg.push(`<path d="${ringPath(L.plot)}" class="map-plot-halo"/>`);
      svg.push(`<path d="${ringPath(L.plot)}" class="map-plot"/>`);

      // 6. hotspots
      if (this.showHotspots) {
        const frpR = (frp) => 3 + Math.min(9, Math.sqrt(Math.max(0, frp || 0)) * 1.6);
        (L.hotspots_buffer || []).forEach((h) => {
          svg.push(`<circle cx="${sx(h.lon).toFixed(1)}" cy="${sy(h.lat).toFixed(1)}"
            r="${frpR(h.frp).toFixed(1)}" class="map-hs-buffer"><title>${h.acq_date} · buffer · FRP ${h.frp}</title></circle>`);
        });
        (L.hotspots_inside || []).forEach((h) => {
          const cls = String(h.confidence).toLowerCase() === "h" ? "map-hs-high" : "map-hs";
          svg.push(`<circle cx="${sx(h.lon).toFixed(1)}" cy="${sy(h.lat).toFixed(1)}"
            r="${frpR(h.frp).toFixed(1)}" class="${cls}"><title>${h.acq_date} · inside plot · FRP ${h.frp}</title></circle>`);
        });
      }

      svg.push(`</svg>`);

      this.host.innerHTML = `
        <div class="map-frame">${svg.join("")}</div>
        <div class="map-controls">
          ${hasImagery
            ? `<label class="map-swipe">
                 <span>${this._label(scenes[0])}</span>
                 <input type="range" min="0" max="100" value="${this.swipe * 100}" id="mapSwipe">
                 <span>${this._label(scenes[1])}</span>
               </label>`
            : `<span class="map-hint">Swipe comparison appears once two composites are cached.</span>`}
          <label><input type="checkbox" id="mapLoss" ${this.showLoss ? "checked" : ""}> loss overlay</label>
          <label><input type="checkbox" id="mapHs" ${this.showHotspots ? "checked" : ""}> hotspots</label>
        </div>
        <div class="map-legend">
          <span><i class="k-plot"></i>concession</span>
          <span><i class="k-adj"></i>adjacent parcel</span>
          <span><i class="k-hs-high"></i>hotspot, high confidence</span>
          <span><i class="k-hs"></i>hotspot</span>
          <span><i class="k-hs-buf"></i>hotspot outside plot</span>
        </div>`;

      this._bind();
    }

    _image(scene, ext, W, H, extra) {
      // Place the PNG by its geographic bounds rather than assuming it fills the frame.
      const [w, s, e, n] = scene.bounds;
      const x = ((merc.x(w) - ext.minX) / (ext.maxX - ext.minX)) * W;
      const x2 = ((merc.x(e) - ext.minX) / (ext.maxX - ext.minX)) * W;
      const y = H - ((merc.y(n) - ext.minY) / (ext.maxY - ext.minY)) * H;
      const y2 = H - ((merc.y(s) - ext.minY) / (ext.maxY - ext.minY)) * H;
      return `<image href="${scene.url}" x="${x.toFixed(1)}" y="${y.toFixed(1)}"
        width="${(x2 - x).toFixed(1)}" height="${(y2 - y).toFixed(1)}"
        preserveAspectRatio="none"${extra}/>`;
    }

    _label(scene) {
      return scene && scene.date ? scene.date : "scene";
    }

    _bind() {
      const swipe = this.host.querySelector("#mapSwipe");
      if (swipe) {
        swipe.addEventListener("input", (e) => {
          this.swipe = e.target.value / 100;
          const rect = this.host.querySelector("#swipeRect");
          if (rect) rect.setAttribute("width", this._proj.W * this.swipe);
        });
      }
      const loss = this.host.querySelector("#mapLoss");
      if (loss) loss.addEventListener("change", (e) => { this.showLoss = e.target.checked; this.render(); });
      const hs = this.host.querySelector("#mapHs");
      if (hs) hs.addEventListener("change", (e) => { this.showHotspots = e.target.checked; this.render(); });
    }
  }

  global.RimbaMap = { EvidenceMap };
})(window);
