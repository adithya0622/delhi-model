import { useMemo, useState } from "react";
import {
  Wind,
  Activity,
  Factory,
  Sun,
  Flame,
  Sparkles,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { PanelMessage } from "@/components/ui/panel-message";
import { DailyForecastStrip } from "@/components/DailyForecastStrip";
import type { Panel } from "@/hooks/useForecastData";
import { aqiToCategory, categoryColor, pollutantSubIndex } from "@/lib/aqi";
import type {
  AqiCategory,
  CityAggregateResponse,
  ConsensusResponse,
  ForecastResponse,
  HourlyForecast,
  Pollutant,
} from "@/lib/types";
import { useTranslation } from "@/i18n";

type ViewHorizon = "24h" | "48h" | "72h";

interface PollutantMeta {
  id: string;
  chemical: Pollutant;
  name: string;
  subtitle: string;
  unit: string;
  themeColor: string;
  gradientId: string;
  icon: typeof Wind;
}

const POLLUTANT_CONFIGS: PollutantMeta[] = [
  {
    id: "pm25",
    chemical: "PM2.5",
    name: "PM2.5 Forecast",
    subtitle: "Fine Particulate Matter (≤ 2.5 µm)",
    unit: "µg/m³",
    themeColor: "#38bdf8",
    gradientId: "grad-pm25",
    icon: Wind,
  },
  {
    id: "pm10",
    chemical: "PM10",
    name: "PM10 Forecast",
    subtitle: "Coarse Particulate Matter (≤ 10 µm)",
    unit: "µg/m³",
    themeColor: "#2dd4bf",
    gradientId: "grad-pm10",
    icon: Activity,
  },
  {
    id: "no2",
    chemical: "NO2",
    name: "NO₂ Forecast",
    subtitle: "Nitrogen Dioxide (Combustion / Vehicular)",
    unit: "µg/m³",
    themeColor: "#f43f5e",
    gradientId: "grad-no2",
    icon: Factory,
  },
  {
    id: "o3",
    chemical: "O3",
    name: "O₃ Forecast",
    subtitle: "Tropospheric Ozone (Photochemical Smog)",
    unit: "µg/m³",
    themeColor: "#eab308",
    gradientId: "grad-o3",
    icon: Sun,
  },
  {
    id: "so2",
    chemical: "SO2",
    name: "SO₂ Forecast",
    subtitle: "Sulfur Dioxide (Industrial / Thermal Power)",
    unit: "µg/m³",
    themeColor: "#a855f7",
    gradientId: "grad-so2",
    icon: Flame,
  },
  {
    id: "co",
    chemical: "CO",
    name: "CO Forecast",
    subtitle: "Carbon Monoxide (Incomplete Combustion)",
    unit: "mg/m³",
    themeColor: "#ec4899",
    gradientId: "grad-co",
    icon: Sparkles,
  },
];

function formatVal(species: Pollutant, val: number): string {
  if (species === "CO") {
    return val.toFixed(2);
  }
  if (val < 10) {
    return val.toFixed(1);
  }
  return String(Math.round(val));
}

interface PollutantForecastsProps {
  forecast?: Panel<ForecastResponse>;
  hour?: HourlyForecast | null;
  cursor?: number;
  consensus?: ConsensusResponse | null;
  cityAggregate?: CityAggregateResponse | null;
}

export function PollutantForecasts({
  forecast,
  hour,
  cursor = 0,
  consensus,
  cityAggregate,
}: PollutantForecastsProps) {
  const { t } = useTranslation();
  const [horizon, setHorizon] = useState<ViewHorizon>("72h");
  const [hoveredIdx, setHoveredIdx] = useState<{ [key: string]: number | null }>({});

  const forecastData = forecast?.data;
  const hours = forecastData?.forecast_hours ?? [];
  const isLoading = forecast?.status === "loading" && hours.length === 0 && !cityAggregate;
  const isError = forecast?.status === "error" && hours.length === 0 && !cityAggregate;

  // Compute all cards strictly derived from live city aggregate & prognostic forecast
  const cards = useMemo(() => {
    const isLiveNow = cursor === 0;
    const hour0 = hours[0] ?? hour;
    const currentHour = hour ?? hour0;

    return POLLUTANT_CONFIGS.map((config) => {
      // 1. Current value displayed at the top of the card (Single source of truth from Hero / City Aggregate)
      const aggDetail = cityAggregate?.sub_indices?.[config.chemical];
      const currentSub = currentHour?.sub_indices.find((s) => s.pollutant === config.chemical);
      const hour0Sub = hour0?.sub_indices.find((s) => s.pollutant === config.chemical);

      let currentVal = 0;
      let currentSubIndex = 0;

      if (isLiveNow && aggDetail != null) {
        currentVal = aggDetail.conc;
        currentSubIndex = aggDetail.index;
      } else if (currentSub) {
        currentVal = currentSub.concentration;
        currentSubIndex = currentSub.sub_index;
      } else if (consensus?.metrics) {
        const m = consensus.metrics;
        if (config.chemical === "PM2.5") currentVal = m.pm25;
        else if (config.chemical === "PM10") currentVal = m.pm10;
        else if (config.chemical === "NO2") currentVal = m.no2 ?? 0;
        else if (config.chemical === "O3") currentVal = m.o3 ?? 0;
        else if (config.chemical === "SO2") currentVal = m.so2 ?? 0;
        else if (config.chemical === "CO") currentVal = m.co ?? 0;
        currentSubIndex = pollutantSubIndex(config.chemical, currentVal);
      } else if (hour0Sub) {
        currentVal = hour0Sub.concentration;
        currentSubIndex = hour0Sub.sub_index;
      }

      const currentCategory = aqiToCategory(currentSubIndex);

      // 2. Generate spline series points according to the active hourly horizon view
      interface SeriesPoint {
        label: string;
        fullTime: string;
        value: number;
        subIndex: number;
        category: AqiCategory;
      }

      const series: SeriesPoint[] = [];

      let checkpoints: number[] = [];
      if (horizon === "24h") {
        checkpoints = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24];
      } else if (horizon === "48h") {
        checkpoints = [0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48];
      } else {
        // Full 72h horizon
        checkpoints = [0, 6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 71];
      }

      checkpoints.forEach((hIdx) => {
        let val: number;
        if (hIdx === 0) {
          val = currentVal;
        } else {
          const validIdx = Math.min(hIdx, Math.max(0, hours.length - 1));
          const ptHour = hours[validIdx];
          const ptSub = ptHour?.sub_indices.find((s) => s.pollutant === config.chemical);
          val = (ptSub && ptSub.concentration > 0) ? ptSub.concentration : (currentVal > 0 ? currentVal : (ptSub?.concentration ?? 0));
        }

        const sIndex = pollutantSubIndex(config.chemical, val);
        const label = hIdx === 0 ? "Now" : `+${hIdx}h`;

        series.push({
          label,
          fullTime: `Horizon +${hIdx}h`,
          value: Number(val.toFixed(config.chemical === "CO" ? 2 : 1)),
          subIndex: sIndex,
          category: aqiToCategory(sIndex),
        });
      });

      // Compute statistics from series
      const values = series.map((s) => s.value);
      const maxVal = Math.max(...values);
      const minVal = Math.min(...values);
      const avgVal = values.reduce((a, b) => a + b, 0) / (values.length || 1);

      // Find peak point in series
      const peakPoint = series.find((s) => s.value === maxVal) || series[0];
      const nextPeakDay = peakPoint.label;
      const nextPeakVal = maxVal;

      // % change vs starting baseline
      const baseline = series[0]?.value || 1;
      const diffPct = Math.round(((maxVal - baseline) / baseline) * 100);
      const pctPositive = diffPct >= 0;

      return {
        ...config,
        current: currentVal,
        currentSubIndex,
        category: currentCategory,
        catColor: categoryColor(currentCategory),
        pctChange: Math.abs(diffPct),
        pctPositive,
        highest: maxVal,
        lowest: minVal,
        average: avgVal,
        nextPeakDay,
        nextPeakVal,
        series,
      };
    });
  }, [hours, horizon, hour, cursor, cityAggregate, consensus]);

  const renderSplineChart = (pol: (typeof cards)[0]) => {
    const rawData = pol.series;
    if (rawData.length < 2) return null;

    const width = 560;
    const height = 135;
    const padX = 28;
    const padYTop = 26;
    const padYBottom = 24;

    const values = rawData.map((d) => d.value);
    const min = Math.min(...values) * 0.85;
    const max = Math.max(...values) * 1.15 || 1;
    const range = max - min || 1;

    const coords = rawData.map((d, i) => {
      const x = padX + (i / (rawData.length - 1)) * (width - padX * 2);
      const y = height - padYBottom - ((d.value - min) / range) * (height - padYTop - padYBottom);
      return {
        x,
        y,
        val: d.value,
        label: d.label,
        fullTime: d.fullTime,
        category: d.category,
        subIndex: d.subIndex,
      };
    });

    let pathD = `M ${coords[0].x},${coords[0].y}`;
    for (let i = 0; i < coords.length - 1; i++) {
      const p0 = coords[i];
      const p1 = coords[i + 1];
      const cx = (p0.x + p1.x) / 2;
      pathD += ` C ${cx},${p0.y} ${cx},${p1.y} ${p1.x},${p1.y}`;
    }

    const areaD = `${pathD} L ${coords[coords.length - 1].x},${height - padYBottom} L ${coords[0].x},${height - padYBottom} Z`;

    return (
      <div style={{ position: "relative", width: "100%", height: "140px", marginTop: "0.75rem" }}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          style={{ width: "100%", height: "100%", overflow: "visible" }}
          aria-hidden="true"
        >
          <defs>
            <linearGradient id={pol.gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={pol.themeColor} stopOpacity="0.4" />
              <stop offset="100%" stopColor={pol.themeColor} stopOpacity="0.0" />
            </linearGradient>
            <filter id={`glow-${pol.id}`} x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="2.5" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>

          {/* Area Fill */}
          <path d={areaD} fill={`url(#${pol.gradientId})`} />

          {/* Spline Line */}
          <path
            d={pathD}
            fill="none"
            stroke={pol.themeColor}
            strokeWidth="2.5"
            filter={`url(#glow-${pol.id})`}
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Data Points and Labels */}
          {coords.map((pt, i) => {
            const isHovered = hoveredIdx[pol.id] === i;
            return (
              <g
                key={i}
                onMouseEnter={() => setHoveredIdx((prev) => ({ ...prev, [pol.id]: i }))}
                onMouseLeave={() => setHoveredIdx((prev) => ({ ...prev, [pol.id]: null }))}
                style={{ cursor: "pointer" }}
              >
                {/* Floating Value Text */}
                <text
                  x={pt.x}
                  y={pt.y - 9}
                  textAnchor="middle"
                  fill={isHovered ? "#ffffff" : pol.themeColor}
                  fontSize="10px"
                  fontFamily="var(--mono)"
                  fontWeight={isHovered ? "bold" : "600"}
                >
                  {formatVal(pol.chemical, pt.val)}
                </text>

                {/* Outer halo point */}
                <circle
                  cx={pt.x}
                  cy={pt.y}
                  r={isHovered ? 6 : 3.5}
                  fill="#0e131f"
                  stroke={pol.themeColor}
                  strokeWidth={isHovered ? 2.5 : 2}
                  style={{ transition: "all 0.15s ease" }}
                />

                {/* X-axis Day/Hour Label */}
                <text
                  x={pt.x}
                  y={height - 3}
                  textAnchor="middle"
                  fill="var(--mist-faint)"
                  fontSize="9px"
                  fontFamily="var(--sans)"
                >
                  {pt.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    );
  };

  return (
    <section
      className="section"
      id="pollutant-forecast"
      aria-labelledby="pol-fc-h"
      style={{
        padding: "1.2rem var(--pad) 3rem",
        marginTop: 0,
        borderBottom: "none",
      }}
    >
      <div
        className="section__head"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          flexWrap: "wrap",
          gap: "1.2rem",
          marginBottom: "1.25rem",
        }}
      >
        <div>
          <p className="eyebrow" style={{ color: "var(--mist-dim)", marginBottom: "0.25rem" }}>
            multi-pollutant dispersion outlook
          </p>
          <h2
            className="section__h"
            id="pol-fc-h"
            style={{
              fontSize: "clamp(2.1rem, 3.8vw, 3.0rem)",
              fontWeight: 600,
              letterSpacing: "-0.03em",
              color: "var(--bone)",
              margin: "0.15rem 0 0.4rem 0",
              lineHeight: 1.15,
            }}
          >
            {t("forecast.title")}
          </h2>
          <p
            className="section__lede"
            style={{
              fontSize: "0.95rem",
              color: "var(--mist)",
              maxWidth: "70ch",
              lineHeight: 1.5,
              margin: 0,
            }}
          >
            {t("forecast.subtitle")}
          </p>
        </div>

        {/* Horizon Toggle */}
        <div className="map__ctrlRow" role="group" aria-label="Hourly forecast horizon view" style={{ marginBottom: "0.2rem" }}>
          <button
            type="button"
            className="btn btn--solid map__ctrlBtn"
            aria-pressed={horizon === "24h"}
            onClick={() => setHorizon("24h")}
          >
            Next 24h
          </button>
          <button
            type="button"
            className="btn btn--solid map__ctrlBtn"
            aria-pressed={horizon === "48h"}
            onClick={() => setHorizon("48h")}
          >
            Next 48h
          </button>
          <button
            type="button"
            className="btn btn--solid map__ctrlBtn"
            aria-pressed={horizon === "72h"}
            onClick={() => setHorizon("72h")}
          >
            Full 72h
          </button>
        </div>
      </div>

      {/* 7-Day Predictable Daily AQI Outlook Strip */}
      <div style={{ marginTop: "1rem" }}>
        <DailyForecastStrip
          forecast={forecastData}
          hours={hours}
          consensus={consensus}
          cityAggregate={cityAggregate}
        />
      </div>

      {isLoading && (
        <div className="pollutant-cards-grid">
          {POLLUTANT_CONFIGS.map((p) => (
            <div
              key={p.id}
              style={{
                background: "linear-gradient(145deg, #131826, #0e121d)",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: "12px",
                padding: "1.4rem",
              }}
            >
              <Skeleton style={{ height: "30px", width: "60%", marginBottom: "1rem" }} />
              <Skeleton style={{ height: "48px", width: "40%", marginBottom: "1rem" }} />
              <Skeleton style={{ height: "135px", width: "100%" }} />
            </div>
          ))}
        </div>
      )}

      {isError && (
        <div style={{ marginTop: "1.5rem" }}>
          <PanelMessage tone="warn">
            Prognostic pollutant forecast unavailable. Showing fallback state.
          </PanelMessage>
        </div>
      )}

      {cards.length > 0 && (
        <div className="pollutant-cards-grid">
          {cards.map((pol) => {
            const Icon = pol.icon;
            return (
              <article
                key={pol.id}
                className="realism-box"
                style={{ width: "100%" }}
              >
                <div className="realism-topglow" />
                <div
                  className="realism-blob"
                  style={{
                    background: `radial-gradient(circle 120px at 0% 100%, ${pol.themeColor}, ${pol.themeColor}55, transparent)`,
                    boxShadow: `-4px 9px 40px ${pol.themeColor}55`,
                  }}
                />
                <div
                  className="realism-inner"
                  style={{
                    padding: "1.35rem 1.45rem",
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "space-between",
                    minHeight: "100%",
                  }}
                >
                  <div className="realism-inner-glow" />

                  {/* Card Content */}
                  <div>
                    {/* Card Header */}
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                        <div
                          style={{
                            width: "38px",
                            height: "38px",
                            borderRadius: "10px",
                            background: "rgba(255, 255, 255, 0.05)",
                            border: `1px solid ${pol.themeColor}44`,
                            boxShadow: `0 0 14px ${pol.themeColor}22`,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            color: pol.themeColor,
                          }}
                        >
                          <Icon size={19} />
                        </div>
                        <div>
                          <h3 style={{ margin: 0, fontSize: "1.05rem", color: "#ffffff", fontWeight: 700, letterSpacing: "-0.01em" }}>
                            {pol.name}
                          </h3>
                          <p style={{ margin: "2px 0 0", fontSize: "11.5px", color: "var(--mist)" }}>
                            {pol.subtitle}
                          </p>
                        </div>
                      </div>

                      {/* Category Pill */}
                      <span
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "0.35rem",
                          padding: "0.22rem 0.7rem",
                          borderRadius: "20px",
                          fontSize: "11px",
                          fontFamily: "var(--mono)",
                          background: `${pol.catColor}18`,
                          color: pol.catColor,
                          border: `1px solid ${pol.catColor}44`,
                          fontWeight: 700,
                          boxShadow: `0 0 10px ${pol.catColor}22`,
                        }}
                      >
                        <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: pol.catColor, boxShadow: `0 0 6px ${pol.catColor}` }} />
                        {pol.category}
                      </span>
                    </div>

                    {/* Key Metrics Row (Current, % Change, Next Peak) */}
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "baseline",
                        marginTop: "1.15rem",
                        paddingBottom: "0.4rem",
                      }}
                    >
                      {/* Current */}
                      <div>
                        <div
                          style={{
                            fontSize: "10px",
                            fontFamily: "var(--mono)",
                            color: "var(--mist-faint)",
                            textTransform: "uppercase",
                            letterSpacing: "0.1em",
                          }}
                        >
                          CURRENT
                        </div>
                        <div
                          style={{
                            fontSize: "2rem",
                            fontFamily: "var(--mono)",
                            fontWeight: 800,
                            color: "#ffffff",
                            lineHeight: 1.1,
                            marginTop: "2px",
                            letterSpacing: "-0.02em",
                          }}
                        >
                          {formatVal(pol.chemical, pol.current)}{" "}
                          <span style={{ fontSize: "0.85rem", fontWeight: 400, color: "var(--mist-dim)" }}>
                            {pol.unit}
                          </span>
                        </div>
                      </div>

                      {/* % change */}
                      <div style={{ textAlign: "center" }}>
                        <div
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "0.2rem",
                            fontSize: "12.5px",
                            fontFamily: "var(--mono)",
                            fontWeight: 700,
                            color: pol.pctPositive ? "#ef4444" : "#10b981",
                          }}
                          title={pol.pctPositive ? "Concentration increased" : "Concentration decreased"}
                        >
                          {pol.pctPositive ? <ArrowUpRight size={15} /> : <ArrowDownRight size={15} />}
                          {pol.pctChange}%
                        </div>
                        <div style={{ fontSize: "10px", fontFamily: "var(--mono)", color: "var(--mist-faint)" }}>
                          {horizon === "24h" ? "vs 24h baseline" : horizon === "48h" ? "vs 48h baseline" : "vs 72h baseline"}
                        </div>
                      </div>

                      {/* Next Peak */}
                      <div style={{ textAlign: "right" }}>
                        <div
                          style={{
                            fontSize: "10px",
                            fontFamily: "var(--mono)",
                            color: "var(--mist-faint)",
                            textTransform: "uppercase",
                            letterSpacing: "0.1em",
                          }}
                        >
                          NEXT PEAK
                        </div>
                        <div
                          style={{
                            fontSize: "1rem",
                            fontFamily: "var(--mono)",
                            fontWeight: 700,
                            color: pol.themeColor,
                            marginTop: "2px",
                          }}
                        >
                          {pol.nextPeakDay}{" "}
                          <span style={{ fontSize: "0.9rem", fontWeight: 700, color: "#ffffff" }}>
                            {formatVal(pol.chemical, pol.nextPeakVal)}
                          </span>{" "}
                          <span style={{ fontSize: "0.8rem", color: "var(--mist)" }}>{pol.unit}</span>
                        </div>
                      </div>
                    </div>

                    {/* Spline Area Chart */}
                    {renderSplineChart(pol)}
                  </div>

                  {/* Bottom Metrics Bar */}
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(4, 1fr)",
                      gap: "0.5rem",
                      marginTop: "1.1rem",
                      paddingTop: "0.85rem",
                      borderTop: "1px solid rgba(255, 255, 255, 0.08)",
                      fontSize: "11px",
                      background: "rgba(255, 255, 255, 0.02)",
                      borderRadius: "6px",
                      padding: "0.65rem 0.75rem",
                    }}
                  >
                    <div>
                      <span style={{ color: "var(--mist-faint)", fontSize: "10px", fontFamily: "var(--mono)" }}>↗ Highest</span>
                      <div
                        style={{
                          color: "#f8fafc",
                          fontFamily: "var(--mono)",
                          fontWeight: 700,
                          fontSize: "13px",
                          marginTop: "2px",
                        }}
                      >
                        {formatVal(pol.chemical, pol.highest)}
                      </div>
                    </div>
                    <div>
                      <span style={{ color: "var(--mist-faint)", fontSize: "10px", fontFamily: "var(--mono)" }}>↘ Lowest</span>
                      <div
                        style={{
                          color: "#f8fafc",
                          fontFamily: "var(--mono)",
                          fontWeight: 700,
                          fontSize: "13px",
                          marginTop: "2px",
                        }}
                      >
                        {formatVal(pol.chemical, pol.lowest)}
                      </div>
                    </div>
                    <div>
                      <span style={{ color: "var(--mist-faint)", fontSize: "10px", fontFamily: "var(--mono)" }}>~ Average</span>
                      <div
                        style={{
                          color: "#f8fafc",
                          fontFamily: "var(--mono)",
                          fontWeight: 700,
                          fontSize: "13px",
                          marginTop: "2px",
                        }}
                      >
                        {formatVal(pol.chemical, pol.average)}
                      </div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <span style={{ color: "var(--mist-faint)", fontSize: "10px", fontFamily: "var(--mono)" }}>Sub-Index</span>
                      <div
                        style={{
                          color: pol.catColor,
                          fontFamily: "var(--mono)",
                          fontWeight: 800,
                          fontSize: "13.5px",
                          marginTop: "2px",
                        }}
                      >
                        {pol.currentSubIndex}
                      </div>
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
