import { useCallback, useMemo, useRef } from "react";
import { Pause, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import { PanelMessage } from "@/components/ui/panel-message";
import { Readouts } from "@/components/Readouts";
import { Skeleton } from "@/components/ui/skeleton";
import type { Cursor } from "@/hooks/useCursor";
import type { Panel } from "@/hooks/useForecastData";
import { aqiColor } from "@/lib/aqi";
import { int, leadLabel } from "@/lib/format";
import type { ForecastResponse, HourlyForecast } from "@/lib/types";
import { useTranslation } from "@/i18n";

// ── Geometry (viewBox units) ──────────────────────────────────────────────────
const W = 1200;
const H = 476;
const PAD_L = 54;
const PAD_R = 14;
const CS_TOP = 20; // altitude = ALT_MAX
const CS_BOTTOM = 352; // altitude = 0 (ground)
const RIB_TOP = 374;
const RIB_BOTTOM = 460;
const ALT_MAX = 2800; // m — headroom above deep afternoon mixing (~2.4 km)
const PLOT_W = W - PAD_L - PAD_R;

const ALT_GRID = [500, 1000, 1500, 2000, 2500];
const HOUR_TICKS = [0, 12, 24, 36, 48, 60, 72];

function xAt(i: number, n: number): number {
  return PAD_L + (n > 1 ? i / (n - 1) : 0) * PLOT_W;
}
function yAlt(alt: number): number {
  const f = Math.max(0, Math.min(1, alt / ALT_MAX));
  return CS_BOTTOM - f * (CS_BOTTOM - CS_TOP);
}
function yAqi(a: number): number {
  const f = Math.max(0, Math.min(1, a / 500));
  return RIB_BOTTOM - f * (RIB_BOTTOM - RIB_TOP);
}

/** Severity colour of a lid from the hour's ΔT; null below the threshold. */
function lidColor(dt: number): string | null {
  if (dt <= 0.2) return null;
  if (dt < 2) return "var(--aqi-3)";
  if (dt < 4) return "var(--aqi-4)";
  return "var(--aqi-5)";
}

interface AtmosphereProps {
  forecast: Panel<ForecastResponse>;
  hour: HourlyForecast | null;
  cursor: Cursor;
}

export function Atmosphere({ forecast, hour, cursor }: AtmosphereProps) {
  const { t } = useTranslation();
  const svgRef = useRef<SVGSVGElement>(null);
  const hours = forecast.data?.forecast_hours ?? [];
  const n = hours.length;
  const slotW = n > 0 ? PLOT_W / n : PLOT_W;

  // ── Static layer: everything that depends only on the series, memoised so
  //    scrubbing never rebuilds it (the cursor layer re-renders alone). ──────
  const staticLayer = useMemo(() => {
    if (n === 0) return null;

    const pts = hours.map((hr, i) => ({
      x: xAt(i, n),
      yc: yAlt(hr.pbl_height_m), // coupled (post-feedback) mixing top
      ym: yAlt(hr.pbl_height_met_m || hr.pbl_height_m), // unperturbed met top
      aqi: hr.aqi,
      dt: hr.inversion_delta_t,
      pm: hr.sub_indices.find((s) => s.pollutant === "PM2.5")?.concentration ?? 0,
    }));
    const first = pts[0];
    const last = pts[n - 1];

    const coupledTop = pts.map((p) => `L ${p.x.toFixed(1)},${p.yc.toFixed(1)}`).join(" ");
    const metTop = pts.map((p) => `L ${p.x.toFixed(1)},${p.ym.toFixed(1)}`).join(" ");

    // Slab = the coupled mixed layer (ground → coupled top).
    const slabPath = `M ${first.x.toFixed(1)},${CS_BOTTOM} ${coupledTop} L ${last.x.toFixed(1)},${CS_BOTTOM} Z`;
    // Residual = the layer you would have had without aerosol (ground → met top).
    const residPath = `M ${first.x.toFixed(1)},${CS_BOTTOM} ${metTop} L ${last.x.toFixed(1)},${CS_BOTTOM} Z`;
    // Suppression sliver = met top (upper) down to coupled top (lower). THE mark.
    const coupledRev = pts
      .slice()
      .reverse()
      .map((p) => `L ${p.x.toFixed(1)},${p.yc.toFixed(1)}`)
      .join(" ");
    const suppPath = `M ${first.x.toFixed(1)},${first.ym.toFixed(1)} ${metTop} ${coupledRev} Z`;

    const metLine = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)},${p.ym.toFixed(1)}`).join(" ");

    return (
      <>
        {/* grid */}
        <g className="c-grid">
          {ALT_GRID.map((alt) => {
            const y = yAlt(alt);
            return (
              <g key={alt}>
                <line x1={PAD_L} y1={y} x2={W - PAD_R} y2={y} />
                <text x={PAD_L - 8} y={y + 3} textAnchor="end">
                  {alt}
                </text>
              </g>
            );
          })}
          <text x={PAD_L - 8} y={CS_BOTTOM + 3} textAnchor="end">
            0 m
          </text>
        </g>

        {/* residual (would-be) layer, faint */}
        <g className="c-resid">
          <path d={residPath} fill="url(#g-resid)" />
        </g>

        {/* haze columns, density ∝ PM2.5, clipped implicitly to the coupled slab */}
        <g className="c-haze">
          {pts.map((p, i) => {
            const a = Math.max(0, Math.min(0.5, p.pm / 320));
            if (a < 0.02) return null;
            const warm = Math.min(1, p.pm / 340);
            const r = Math.round(150 + warm * 70);
            const g = Math.round(150 - warm * 30);
            const b = Math.round(150 - warm * 90);
            return (
              <rect
                key={i}
                x={p.x - slotW / 2}
                y={p.yc}
                width={slotW + 0.6}
                height={CS_BOTTOM - p.yc}
                fill={`rgba(${r},${g},${b},${a.toFixed(3)})`}
              />
            );
          })}
        </g>

        {/* suppression sliver — depth removed by aerosol */}
        <g className="c-supp">
          <path d={suppPath} fill="url(#p-supp)" stroke="var(--aqi-3)" strokeOpacity="0.35" strokeWidth="0.75" />
        </g>

        {/* coupled mixed-layer body */}
        <g className="c-slab">
          <path d={slabPath} fill="url(#g-slab)" />
        </g>

        {/* met-model depth, dashed */}
        <g className="c-met">
          <path d={metLine} fill="none" stroke="var(--mist-dim)" strokeWidth="1.1" strokeDasharray="5 4" />
        </g>

        {/* inversion caps — a coloured lid at the coupled top where ΔT > 0 */}
        <g className="c-inv">
          {pts.map((p, i) => {
            const c = lidColor(p.dt);
            if (!c) return null;
            return (
              <line
                key={i}
                x1={p.x - slotW / 2}
                y1={p.yc}
                x2={p.x + slotW / 2}
                y2={p.yc}
                stroke={c}
                strokeWidth="2.4"
                strokeLinecap="butt"
              />
            );
          })}
        </g>

        {/* AQI ribbon on the shared x-axis */}
        <g className="c-ribbon">
          {pts.map((p, i) => {
            const y = yAqi(p.aqi);
            const bw = Math.max(1, slotW - 1);
            return (
              <rect key={i} x={p.x - bw / 2} y={y} width={bw} height={RIB_BOTTOM - y} fill={aqiColor(p.aqi)} opacity={0.92} />
            );
          })}
          <line x1={PAD_L} y1={RIB_BOTTOM} x2={W - PAD_R} y2={RIB_BOTTOM} stroke="var(--hairline-2)" />
        </g>

        {/* x-axis hour labels */}
        <g className="c-axis">
          {HOUR_TICKS.map((hh) => {
            const idx = Math.min(n - 1, hh);
            const x = xAt(idx, n);
            return (
              <text key={hh} x={x} y={H - 4} textAnchor={hh === 0 ? "start" : hh >= 72 ? "end" : "middle"}>
                {hh === 0 ? "now" : `+${hh}`}
              </text>
            );
          })}
        </g>
      </>
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forecast.data, n, slotW]);

  // ── Cursor layer: cheap, re-renders every scrub tick. ─────────────────────
  const curX = xAt(cursor.cursor, n);
  const curPt = hours[cursor.cursor] ?? null;
  const curYc = curPt ? yAlt(curPt.pbl_height_m) : CS_TOP;
  const aqiValNow = curPt ? curPt.aqi : 0;
  const leftPct = (curX / W) * 100;
  const topPct = (curYc / H) * 100;

  const ariaText = curPt
    ? `hour ${leadLabel(cursor.cursor)}, AQI ${int(curPt.aqi)}, ${curPt.category}`
    : `hour ${cursor.cursor}`;

  // ── Pointer scrubbing ─────────────────────────────────────────────────────
  const scrubTo = useCallback(
    (clientX: number) => {
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      if (rect.width === 0) return;
      const vbX = ((clientX - rect.left) / rect.width) * W;
      const t = (vbX - PAD_L) / PLOT_W;
      cursor.setFromRatio(t);
    },
    [cursor],
  );

  const onPointerDown = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      e.currentTarget.setPointerCapture(e.pointerId);
      scrubTo(e.clientX);
    },
    [scrubTo],
  );
  const onPointerMove = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      if (e.currentTarget.hasPointerCapture(e.pointerId)) scrubTo(e.clientX);
    },
    [scrubTo],
  );

  const loading = forecast.status === "loading" && n === 0;
  const errored = forecast.status === "error" && n === 0;

  return (
    <section className="section section--atmos" aria-labelledby="atmos-h">
      <div className="section__head">
        <div>
          <p className="eyebrow">the signal</p>
          <h2 className="section__h" id="atmos-h">
            {t("atmosphere.title")}
          </h2>
          <p className="section__lede">
            {t("atmosphere.subtitle")}
          </p>
        </div>

        <div className="transport">
          <Button variant="solid" aria-pressed={cursor.playing} onClick={cursor.toggle}>
            {cursor.playing ? <Pause className="btn__icon" aria-hidden="true" /> : <Play className="btn__icon" aria-hidden="true" />}
            <span>{cursor.playing ? "Stop" : "Sweep 72 h"}</span>
          </Button>
          <Button onClick={cursor.goNow}>Now</Button>
        </div>
      </div>

      <figure className="atmos">
        <div className="atmos__legend">
          <span className="lg lg--slab">mixed layer</span>
          <span className="lg lg--supp">removed by aerosol</span>
          <span className="lg lg--met">met-model depth</span>
          <span className="lg lg--inv">inversion</span>
        </div>

        {errored ? (
          <PanelMessage tone="warn">
            <b>Forecast unavailable.</b> The coupled column could not be solved and no sample could be
            loaded.
          </PanelMessage>
        ) : loading ? (
          <Skeleton style={{ width: "100%", aspectRatio: `${W} / ${H}`, borderRadius: 4 }} />
        ) : (
          <div className="atmos__stage" id="stage">
            <svg
              ref={svgRef}
              className="chart"
              viewBox={`0 0 ${W} ${H}`}
              preserveAspectRatio="xMidYMid meet"
              role="slider"
              tabIndex={0}
              aria-labelledby="atmos-h"
              aria-valuemin={0}
              aria-valuemax={Math.max(0, n - 1)}
              aria-valuenow={cursor.cursor}
              aria-valuetext={ariaText}
              onKeyDown={cursor.onKeyDown}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              style={{ touchAction: "pan-y" }}
            >
              <defs>
                <linearGradient id="g-slab" x1="0" y1="1" x2="0" y2="0">
                  <stop offset="0%" stopColor="#6E8598" stopOpacity="0.55" />
                  <stop offset="55%" stopColor="#6E8598" stopOpacity="0.22" />
                  <stop offset="100%" stopColor="#6E8598" stopOpacity="0.05" />
                </linearGradient>
                <linearGradient id="g-resid" x1="0" y1="1" x2="0" y2="0">
                  <stop offset="0%" stopColor="#4A5C6D" stopOpacity="0.20" />
                  <stop offset="100%" stopColor="#4A5C6D" stopOpacity="0" />
                </linearGradient>
                <pattern id="p-supp" width="7" height="7" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
                  <line x1="0" y1="0" x2="0" y2="7" stroke="#E8B21A" strokeWidth="1.5" strokeOpacity="0.55" />
                </pattern>
              </defs>

              {staticLayer}

              {/* cursor */}
              <g className="c-cursor">
                <line x1={curX} y1={CS_TOP} x2={curX} y2={RIB_BOTTOM} />
                <circle cx={curX} cy={curYc} r={4} />
                <circle cx={curX} cy={yAqi(aqiValNow)} r={3} />
              </g>
            </svg>

            <div
              className="atmos__tip"
              style={{ left: `${leftPct}%`, top: `${topPct}%` }}
              aria-hidden="true"
            >
              <b>{curPt ? int(curPt.aqi) : "—"}</b> <span>{leadLabel(cursor.cursor)}</span>
            </div>
          </div>
        )}

        <figcaption className="atmos__cap">
          Drag anywhere on the field, or use <kbd>←</kbd> <kbd>→</kbd> to step an hour, <kbd>PgUp</kbd>{" "}
          <kbd>PgDn</kbd> for six. Every reading on this page follows the cursor.
        </figcaption>
      </figure>

      {/* Cursor-driven readouts live inside this section, as in the prototype, so
          they inherit the section's horizontal inset. */}
      <Readouts hour={hour} loading={forecast.status === "loading"} />
    </section>
  );
}
