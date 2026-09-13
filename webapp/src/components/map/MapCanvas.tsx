import { useCallback, useEffect, useRef } from "react";

import { aqiColor } from "@/lib/aqi";
import {
  DELHI,
  dividerLat,
  hexLerp,
  hotspotRadius,
  makeProjector,
  type MapLayers,
  type MapStyleId,
} from "@/lib/mapgeo";
import type { IndustryRecord, PlumeVectorsResponse, StationReading } from "@/lib/types";
import { classifyIndustryTier } from "@/lib/types";

/**
 * Offline renderer — a self-contained Canvas schematic used when the browser is
 * offline (or the operator forces it), so the map keeps working with zero tile
 * requests. It evolves the prototype's plume-map draw loop (projection, graticule,
 * Punjab/Haryana divider, Delhi rings, 850 hPa trajectories + FRP-scaled hotspots,
 * wind arrow) and adds the three toggleable overlays the online map has: the AQI
 * heat surface, per-station "plume" glow markers, and click-to-select hit-testing.
 *
 * There is no basemap offline, so this is explicitly a schematic — StationMap
 * labels it as such. Positions are a linear lon/lat projection into the frame.
 */

const ASPECT_FALLBACK = 470 / 760;
const PULSE_MS = 2600;

interface MapCanvasProps {
  stations: StationReading[];
  plume: PlumeVectorsResponse | null;
  industries?: IndustryRecord[];
  layers: MapLayers;
  style: MapStyleId;
  cursor: number;
  selectedUid: string | null;
  onSelect: (uid: string | null) => void;
  /** rAF pulse on markers/hotspots; false under reduced motion. */
  animate: boolean;
}

interface StyleInk {
  top: string;
  bot: string;
  grid: number;
  ink: string;
  sub: string;
}

// Offline has no imagery, so each style is a distinct schematic tint, not tiles.
const STYLE_INK: Record<MapStyleId, StyleInk> = {
  dark: { top: "#0C1620", bot: "#0A1119", grid: 0.1, ink: "rgba(140,163,182,0.35)", sub: "rgba(140,163,182,0.5)" },
  satellite: { top: "#0A1118", bot: "#070D13", grid: 0.07, ink: "rgba(140,163,182,0.26)", sub: "rgba(140,163,182,0.4)" },
  streets: { top: "#141F2A", bot: "#0F1A24", grid: 0.14, ink: "rgba(160,180,198,0.42)", sub: "rgba(160,180,198,0.55)" },
  terrain: { top: "#0E1A15", bot: "#0A130E", grid: 0.11, ink: "rgba(150,175,160,0.34)", sub: "rgba(150,175,160,0.5)" },
};

/** "#RRGGBB" → "rgba(r,g,b,a)". Non-hex input is returned unchanged. */
function hexToRgba(hex: string, alpha: number): string {
  if (hex[0] !== "#" || hex.length < 7) return hex;
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

interface ProjectedPoint {
  uid: string;
  x: number;
  y: number;
}

export function MapCanvas({
  stations,
  plume,
  industries = [],
  layers,
  style,
  cursor,
  selectedUid,
  onSelect,
  animate,
}: MapCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const ptsRef = useRef<ProjectedPoint[]>([]);

  // Latest props for the click handler (which is stable across renders).
  const stateRef = useRef({ stations, onSelect });
  stateRef.current = { stations, onSelect };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const ink = STYLE_INK[style];
    const uv: [number, number] | null = plume
      ? plume.wind_series[cursor] ?? [plume.wind_850hpa_u, plume.wind_850hpa_v]
      : null;

    const paint = (phase: number) => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = canvas.clientWidth || 760;
      const h = canvas.clientHeight || w * ASPECT_FALLBACK;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const { x: X, y: Y } = makeProjector(w, h);

      // ── background ──────────────────────────────────────────────────────
      const bg = ctx.createLinearGradient(0, 0, 0, h);
      bg.addColorStop(0, ink.top);
      bg.addColorStop(1, ink.bot);
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, w, h);

      // ── graticule at integer degrees ────────────────────────────────────
      ctx.strokeStyle = `rgba(140,163,182,${ink.grid})`;
      ctx.fillStyle = ink.ink;
      ctx.lineWidth = 1;
      ctx.font = "9px 'IBM Plex Mono', monospace";
      for (let lon = Math.ceil(73.6); lon <= 78.4; lon++) {
        ctx.beginPath();
        ctx.moveTo(X(lon), 0);
        ctx.lineTo(X(lon), h);
        ctx.stroke();
        ctx.fillText(`${lon}°E`, X(lon) + 3, h - 5);
      }
      for (let lat = Math.ceil(27.9); lat <= 31.7; lat++) {
        ctx.beginPath();
        ctx.moveTo(0, Y(lat));
        ctx.lineTo(w, Y(lat));
        ctx.stroke();
        ctx.fillText(`${lat}°N`, 3, Y(lat) - 3);
      }

      // ── Punjab / Haryana divider ────────────────────────────────────────
      ctx.strokeStyle = "rgba(140,163,182,0.28)";
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(X(73.6), Y(dividerLat(73.6)));
      ctx.lineTo(X(78.4), Y(dividerLat(78.4)));
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = ink.sub;
      ctx.font = "10px 'IBM Plex Mono', monospace";
      ctx.fillText("PUNJAB", X(74.2), Y(dividerLat(74.2)) - 8);
      ctx.fillText("HARYANA", X(75.6), Y(dividerLat(75.6)) + 16);

      // ── Delhi distance rings (100 / 200 / 300 km) ───────────────────────
      const kmToLon = 1 / (111 * Math.cos((DELHI.lat * Math.PI) / 180));
      const cx = X(DELHI.lon);
      const cy = Y(DELHI.lat);
      ctx.strokeStyle = "rgba(140,163,182,0.16)";
      ctx.lineWidth = 1;
      for (const km of [100, 200, 300]) {
        const rx = ((km * kmToLon) / (78.4 - 73.6)) * w;
        const ry = (km / 111 / (31.7 - 27.9)) * h;
        ctx.beginPath();
        ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
        ctx.stroke();
      }

      // ── AQI heat surface (interpolated blobs, sorted so worst sits on top) ─
      if (layers.heatmap && stations.length) {
        ctx.save();
        const sorted = [...stations].sort((a, b) => a.aqi - b.aqi);
        for (const s of sorted) {
          const x = X(s.lon);
          const y = Y(s.lat);
          const rad = 52;
          const col = aqiColor(s.aqi);
          const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
          g.addColorStop(0, hexToRgba(col, 0.5));
          g.addColorStop(1, hexToRgba(col, 0));
          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.arc(x, y, rad, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.restore();
      }

      // ── plume trajectories + fire hotspots ──────────────────────────────
      if (layers.fires && plume) {
        for (const pl of plume.plumes) {
          const tr = pl.trajectory;
          if (tr.length < 2) continue;
          for (let i = 1; i < tr.length; i++) {
            const t = i / (tr.length - 1);
            ctx.strokeStyle = `rgba(242,137,47,${(0.12 + t * 0.5).toFixed(3)})`;
            ctx.lineWidth = 1.4;
            ctx.beginPath();
            ctx.moveTo(X(tr[i - 1][1]), Y(tr[i - 1][0]));
            ctx.lineTo(X(tr[i][1]), Y(tr[i][0]));
            ctx.stroke();
          }
          const cp = tr[Math.min(cursor, tr.length - 1)];
          if (cp) {
            ctx.fillStyle = "rgba(233,240,246,0.85)";
            ctx.beginPath();
            ctx.arc(X(cp[1]), Y(cp[0]), 2, 0, Math.PI * 2);
            ctx.fill();
          }
        }

        const halo = 0.28 + (animate ? 0.12 * Math.sin(phase * Math.PI * 2) : 0);
        for (const hs of plume.hotspots) {
          const r = hotspotRadius(hs.frp_mw);
          const col = hexLerp("#F2892F", "#E8503C", Math.min(1, hs.frp_mw / 90));
          ctx.beginPath();
          ctx.fillStyle = col;
          ctx.globalAlpha = halo;
          ctx.arc(X(hs.lon), Y(hs.lat), r + 3, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = 0.9;
          ctx.beginPath();
          ctx.arc(X(hs.lon), Y(hs.lat), r, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = 1;
        }
      }

      // ── stations: "plume" glow + dot, selection ring, hit-test points ────
      const pts: ProjectedPoint[] = [];
      if (layers.stations) {
        const grow = animate ? 1 + 0.1 * Math.sin(phase * Math.PI * 2) : 1;
        for (const s of stations) {
          const x = X(s.lon);
          const y = Y(s.lat);
          pts.push({ uid: s.uid, x, y });
          const col = aqiColor(s.aqi);
          const glowR = (9 + (Math.min(500, s.aqi) / 500) * 20) * grow;

          const g = ctx.createRadialGradient(x, y, 0, x, y, glowR);
          g.addColorStop(0, hexToRgba(col, 0.5));
          g.addColorStop(1, hexToRgba(col, 0));
          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.arc(x, y, glowR, 0, Math.PI * 2);
          ctx.fill();

          const selected = s.uid === selectedUid;
          if (selected) {
            ctx.strokeStyle = "#E9F0F6";
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.arc(x, y, 10 * grow, 0, Math.PI * 2);
            ctx.stroke();
          }
          ctx.fillStyle = col;
          ctx.strokeStyle = "rgba(233,240,246,0.9)";
          ctx.lineWidth = 1;
          ctx.beginPath();
        }
      }
      ptsRef.current = pts;

      // ── Delhi-Only Industrial Facilities (3-Stage Pollution Tiers) ────
      if (layers.industries && industries && industries.length > 0) {
        for (const ind of industries) {
          const ix = X(ind.longitude);
          const iy = Y(ind.latitude);
          const tierInfo = classifyIndustryTier(ind);

          // Soft ambient glow for Tier 1
          if (tierInfo.tier === 1) {
            ctx.fillStyle = `${tierInfo.color}40`;
            ctx.beginPath();
            ctx.arc(ix, iy, 7, 0, Math.PI * 2);
            ctx.fill();
          }

          // Factory marker
          ctx.fillStyle = tierInfo.color;
          ctx.strokeStyle = tierInfo.tier === 1 ? "#ffffff" : "rgba(255,255,255,0.7)";
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(ix, iy, tierInfo.tier === 1 ? 4 : 3, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
        }
      }

      // ── Delhi marker ────────────────────────────────────────────────────
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(Math.PI / 4);
      ctx.fillStyle = "#E9F0F6";
      ctx.fillRect(-4, -4, 8, 8);
      ctx.restore();
      ctx.fillStyle = "#E9F0F6";
      ctx.font = "600 10px 'IBM Plex Mono', monospace";
      ctx.fillText("DELHI", cx + 9, cy + 3);

      // ── 850 hPa wind arrow (points where the wind blows) ────────────────
      if (uv) {
        const [u, v] = uv;
        const spd = Math.hypot(u, v);
        const ax = w - 66;
        const ay = 34;
        const len = Math.min(40, 8 + spd * 3.2);
        const nx = spd > 0.01 ? u / spd : 0;
        const ny = spd > 0.01 ? -v / spd : 0;
        const ex = ax + nx * len;
        const ey = ay + ny * len;
        ctx.strokeStyle = "#9FC93C";
        ctx.fillStyle = "#9FC93C";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(ex, ey);
        ctx.stroke();
        const ang = Math.atan2(ey - ay, ex - ax);
        ctx.beginPath();
        ctx.moveTo(ex, ey);
        ctx.lineTo(ex - 7 * Math.cos(ang - 0.4), ey - 7 * Math.sin(ang - 0.4));
        ctx.lineTo(ex - 7 * Math.cos(ang + 0.4), ey - 7 * Math.sin(ang + 0.4));
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = "rgba(140,163,182,0.7)";
        ctx.font = "9px 'IBM Plex Mono', monospace";
        ctx.fillText("850 hPa", ax - 18, ay + 24);
      }
    };

    let raf = 0;
    const start = performance.now();
    const loop = (ts: number) => {
      paint(animate ? ((ts - start) / PULSE_MS) % 1 : 0);
      if (animate) raf = requestAnimationFrame(loop);
    };
    loop(start);

    const ro = new ResizeObserver(() => paint(animate ? ((performance.now() - start) / PULSE_MS) % 1 : 0));
    ro.observe(canvas);

    return () => {
      if (raf) cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [stations, plume, layers, style, cursor, selectedUid, animate]);

  // Nearest-station hit test (CSS px; projected points share the same space).
  const onClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    let best: string | null = null;
    let bestD = 16 * 16;
    for (const p of ptsRef.current) {
      const dx = p.x - px;
      const dy = p.y - py;
      const d = dx * dx + dy * dy;
      if (d < bestD) {
        bestD = d;
        best = p.uid;
      }
    }
    stateRef.current.onSelect(best);
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="map__canvas"
      width={760}
      height={470}
      onClick={onClick}
      role="img"
      aria-label="Offline schematic map of the Delhi-NCR station network and stubble-transport domain. Click a station marker to inspect it."
    />
  );
}
