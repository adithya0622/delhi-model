import { useEffect, useMemo, useState } from "react";
import {
  History,
  TrendingUp,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Waves,
  BarChart3,
  Sun,
  Moon,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { aqiToCategory, categoryColor } from "@/lib/aqi";
import { getHistoricalAirQuality } from "@/lib/api";
import type { Panel } from "@/hooks/useForecastData";
import type { AqiCategory, CityAggregateResponse, ForecastResponse, Historical7dHour } from "@/lib/types";
import { useTranslation } from "@/i18n";

type TimeRange = "24h" | "7d" | "diurnal";

interface HistoricalPoint {
  time: string;
  hour: string;
  day: string;
  date: string;
  aqi: number;
  pm25: number;
  pm10: number;
  no2: number;
  cat: string;
}

interface HistoricalDataProps {
  currentAqi?: number;
  forecast?: Panel<ForecastResponse>;
  cityAggregate?: CityAggregateResponse | null;
}

function safeCategoryColor(cat: string): string {
  try {
    return categoryColor(cat as AqiCategory);
  } catch {
    return "#38bdf8";
  }
}

export function HistoricalData({ currentAqi = 220, forecast, cityAggregate }: HistoricalDataProps) {
  const { t } = useTranslation();
  const [range, setRange] = useState<TimeRange>("24h");
  const [activePollutant, setActivePollutant] = useState<"aqi" | "pm25" | "pm10" | "no2">("aqi");
  const [chartType, setChartType] = useState<"wave" | "bars">("wave");

  const effectiveAqi = cityAggregate?.overall_aqi ?? currentAqi;
  const effectivePm25 = cityAggregate?.sub_indices?.["PM2.5"]?.conc ?? 73.8;
  const effectivePm10 = cityAggregate?.sub_indices?.["PM10"]?.conc ?? 97.8;
  const effectiveNo2 = cityAggregate?.sub_indices?.["NO2"]?.conc ?? 14.7;

  const [historyHours, setHistoryHours] = useState<Historical7dHour[]>([]);

  useEffect(() => {
    let active = true;
    getHistoricalAirQuality()
      .then((res) => {
        if (active && res?.hours?.length) {
          setHistoryHours(res.hours);
        }
      })
      .catch((err) => console.warn("Failed to load historical air quality:", err));
    return () => {
      active = false;
    };
  }, []);

  const past24Hours: HistoricalPoint[] = useMemo(() => {
    if (historyHours.length >= 24) {
      const slice24 = historyHours.slice(-24);
      return slice24.map((h, i) => {
        const isLatest = i === slice24.length - 1;
        const d = new Date(h.timestamp);
        const hourStr = d.getHours().toString().padStart(2, "0") + ":00";
        const aqi = isLatest ? effectiveAqi : Math.round(h.aqi ?? 0);
        const pm25 = isLatest ? Math.round(effectivePm25) : Math.round(h.pm25 ?? 0);
        const pm10 = isLatest ? Math.round(effectivePm10) : Math.round(h.pm10 ?? 0);
        const no2 = isLatest ? Math.round(effectiveNo2) : Math.round(h.no2 ?? 0);
        return {
          time: isLatest ? "Current Hour" : hourStr,
          hour: isLatest ? "Now" : hourStr,
          day: isLatest ? "Today" : d.toLocaleDateString("en-US", { weekday: "short" }),
          date: isLatest ? "Now" : hourStr,
          aqi,
          pm25,
          pm10,
          no2,
          cat: aqiToCategory(aqi),
        };
      });
    }

    return [
      {
        time: "Current Hour",
        hour: "Now",
        day: "Today",
        date: "Now",
        aqi: effectiveAqi,
        pm25: Math.round(effectivePm25),
        pm10: Math.round(effectivePm10),
        no2: Math.round(effectiveNo2),
        cat: aqiToCategory(effectiveAqi),
      },
    ];
  }, [historyHours, effectiveAqi, effectivePm25, effectivePm10, effectiveNo2]);

  const past7Days: HistoricalPoint[] = useMemo(() => {
    if (historyHours.length >= 24) {
      const daysCount = Math.min(7, Math.floor(historyHours.length / 24));
      const result: HistoricalPoint[] = [];

      for (let dayIdx = 0; dayIdx < daysCount; dayIdx++) {
        const start = dayIdx * 24;
        const slice = historyHours.slice(start, start + 24);
        if (slice.length === 0) continue;

        const isToday = dayIdx === daysCount - 1;
        const d = new Date(slice[0].timestamp);
        const dateStr = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
        const dayLabel = isToday
          ? "Today (Live)"
          : dayIdx === daysCount - 2
          ? "Yesterday"
          : `${daysCount - 1 - dayIdx} Days Ago`;

        const avgAqi = isToday ? effectiveAqi : Math.round(slice.reduce((acc, h) => acc + (h.aqi ?? 0), 0) / slice.length);
        const avgPm25 = isToday ? Math.round(effectivePm25) : Math.round(slice.reduce((acc, h) => acc + (h.pm25 ?? 0), 0) / slice.length);
        const avgPm10 = isToday ? Math.round(effectivePm10) : Math.round(slice.reduce((acc, h) => acc + (h.pm10 ?? 0), 0) / slice.length);
        const avgNo2 = isToday ? Math.round(effectiveNo2) : Math.round(slice.reduce((acc, h) => acc + (h.no2 ?? 0), 0) / slice.length);

        result.push({
          time: dateStr,
          hour: isToday ? "Today" : dateStr,
          day: dayLabel,
          date: dateStr,
          aqi: avgAqi,
          pm25: avgPm25,
          pm10: avgPm10,
          no2: avgNo2,
          cat: aqiToCategory(avgAqi),
        });
      }

      return result;
    }

    return [
      {
        time: "Today",
        hour: "Today",
        day: "Today (Live)",
        date: "Today",
        aqi: effectiveAqi,
        pm25: Math.round(effectivePm25),
        pm10: Math.round(effectivePm10),
        no2: Math.round(effectiveNo2),
        cat: aqiToCategory(effectiveAqi),
      },
    ];
  }, [historyHours, effectiveAqi, effectivePm25, effectivePm10, effectiveNo2]);

  const diurnalProfile = [
    { hour: "00:00", label: "Midnight Baseline", aqi: 280, cat: "Poor" as const, note: "Boundary layer shallow (~200m), nocturnal accumulation" },
    { hour: "04:00", label: "Early Dawn Stagnation", aqi: 310, cat: "Very Poor" as const, note: "Peak ground thermal inversion stability" },
    { hour: "08:00", label: "Morning Commuter Peak", aqi: 365, cat: "Very Poor" as const, note: "Fumigation effect as rising sun entrains overnight residual mass + rush traffic" },
    { hour: "12:00", label: "Midday Solar Convection", aqi: 230, cat: "Poor" as const, note: "Solar heating expands PBL (>1800m), strong vertical atmospheric dilution" },
    { hour: "15:00", label: "Afternoon Minimum", aqi: 160, cat: "Moderate" as const, note: "Deepest mixing layer of the day, cleanest surface air" },
    { hour: "19:00", label: "Evening Rush Collapse", aqi: 275, cat: "Poor" as const, note: "Sunset collapse of PBL into nocturnal inversion layer + evening rush" },
    { hour: "22:00", label: "Night Inversion", aqi: 285, cat: "Poor" as const, note: "Particulate mass trapped under shallow nocturnal inversion ceiling" },
  ];

  const forecastHours = forecast?.data?.forecast_hours ?? [];
  const dynamic24Hours: HistoricalPoint[] = useMemo(() => {
    if (forecastHours.length === 0) return past24Hours;
    return forecastHours.slice(0, 24).map((h, i) => {
      const pm25Val = h.sub_indices.find((s) => s.pollutant === "PM2.5")?.concentration ?? 0;
      const pm10Val = h.sub_indices.find((s) => s.pollutant === "PM10")?.concentration ?? 0;
      const no2Val = h.sub_indices.find((s) => s.pollutant === "NO2")?.concentration ?? 0;
      const d = new Date(h.timestamp);
      const timeStr = !isNaN(d.getTime())
        ? `${d.toLocaleDateString("en-US", { weekday: "short" })} ${String(d.getHours()).padStart(2, "0")}:00`
        : `+${i}h`;
      const hourStr = !isNaN(d.getTime()) ? `${String(d.getHours()).padStart(2, "0")}:00` : `+${i}h`;

      const isAnchor = i === 0;
      const finalAqi = isAnchor ? effectiveAqi : h.aqi;
      const finalPm25 = isAnchor ? Math.round(effectivePm25) : Math.round(pm25Val);
      const finalPm10 = isAnchor ? Math.round(effectivePm10) : Math.round(pm10Val);
      const finalNo2 = isAnchor ? Math.round(effectiveNo2) : Math.round(no2Val);

      return {
        time: isAnchor ? "Now (Live)" : timeStr,
        hour: isAnchor ? "Now" : hourStr,
        day: isAnchor ? "Today" : timeStr,
        date: hourStr,
        aqi: finalAqi,
        pm25: finalPm25,
        pm10: finalPm10,
        no2: finalNo2,
        cat: aqiToCategory(finalAqi),
      };
    });
  }, [forecastHours, past24Hours, effectiveAqi, effectivePm25, effectivePm10, effectiveNo2]);

  const currentDataset: HistoricalPoint[] = range === "24h" ? dynamic24Hours : range === "7d" ? past7Days : [];

  const getMetricValue = (item: HistoricalPoint) => {
    if (activePollutant === "aqi") return item.aqi;
    if (activePollutant === "pm25") return item.pm25;
    if (activePollutant === "pm10") return item.pm10;
    return item.no2;
  };

  const getMetricUnit = () => (activePollutant === "aqi" ? "AQI" : "µg/m³");

  const values = range !== "diurnal" ? currentDataset.map(getMetricValue) : diurnalProfile.map((d) => d.aqi);
  const minVal = values.length ? Math.min(...values) : 0;
  const maxVal = values.length ? Math.max(...values) : 0;
  const avgVal = values.length ? Math.round(values.reduce((a, b) => a + b, 0) / values.length) : 0;

  const maxItem = range !== "diurnal" ? currentDataset.find((d) => getMetricValue(d) === maxVal) : null;
  const minItem = range !== "diurnal" ? currentDataset.find((d) => getMetricValue(d) === minVal) : null;

  const peakSubtitle = maxItem
    ? (maxItem.hour === "Now" || maxItem.day.includes("Today")
        ? `${t("common.live")} (${t("historic.peakObservation")})`
        : `${maxItem.time || maxItem.day} (${maxItem.hour || maxItem.date})`)
    : t("historic.peakObservation");

  const cleanestSubtitle = range === "diurnal"
    ? t("historic.afternoonMixing")
    : minItem
    ? (minItem.hour === "Now" || minItem.day.includes("Today")
        ? t("historic.cleanestLive")
        : `${minItem.time || minItem.day} (${minItem.hour || minItem.date})`)
    : t("historic.cleanestWindow");

  const activeColor =
    activePollutant === "aqi"
      ? "#38bdf8"
      : activePollutant === "pm25"
      ? "#f43f5e"
      : activePollutant === "pm10"
      ? "#fbbf24"
      : "#34d399";

  return (
    <section
      className="section"
      id="historical-trends"
      aria-labelledby="hist-h"
      style={{
        padding: "1.2rem var(--pad) 3rem",
        marginTop: 0,
        borderBottom: "none",
      }}
    >
      {/* ── UNIFIED SECTION HEADER ── */}
      <div
        className="section__head"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          flexWrap: "wrap",
          gap: "1.2rem",
          marginBottom: "1.5rem",
        }}
      >
        <div>
          <p className="eyebrow" style={{ color: "var(--mist-dim)", marginBottom: "0.25rem" }}>
            retrospective analysis &amp; climatological soundings
          </p>
          <h2
            className="section__h"
            id="hist-h"
            style={{
              fontSize: "clamp(2.1rem, 3.8vw, 3.0rem)",
              fontWeight: 600,
              letterSpacing: "-0.03em",
              color: "var(--bone)",
              margin: "0.15rem 0 0.4rem 0",
              lineHeight: 1.15,
            }}
          >
            {t("historic.title")}
          </h2>
          <p
            className="section__lede"
            style={{
              fontSize: "0.95rem",
              color: "var(--mist)",
              maxWidth: "75ch",
              lineHeight: 1.55,
              margin: 0,
            }}
          >
            {t("historic.subtitle")}
          </p>
        </div>

        {/* Horizon & Pollutant Toggles */}
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "center" }}>
          <div className="map__ctrlRow" role="group" aria-label="Time range">
            <button
              type="button"
              className="btn btn--solid map__ctrlBtn"
              aria-pressed={range === "24h"}
              onClick={() => setRange("24h")}
            >
              24h
            </button>
            <button
              type="button"
              className="btn btn--solid map__ctrlBtn"
              aria-pressed={range === "7d"}
              onClick={() => setRange("7d")}
            >
              7d
            </button>
            <button
              type="button"
              className="btn btn--solid map__ctrlBtn"
              aria-pressed={range === "diurnal"}
              onClick={() => setRange("diurnal")}
            >
              {t("historic.diurnalCycle")}
            </button>
          </div>

          {range !== "diurnal" && (
            <div className="map__ctrlRow" role="group" aria-label="Pollutant filter">
              {(["aqi", "pm25", "pm10", "no2"] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  className="btn btn--solid map__ctrlBtn"
                  aria-pressed={activePollutant === p}
                  onClick={() => setActivePollutant(p)}
                  style={{ textTransform: "uppercase" }}
                >
                  {p === "pm25" ? "PM2.5" : p === "pm10" ? "PM10" : p}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── 4 QUICK STAT CARDS (REALISM SHINY BORDERS) ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: "1.1rem", marginBottom: "1.8rem" }}>
        {/* 1. Average Metric */}
        <article className="realism-box">
          <div className="realism-topglow" />
          <div className="realism-blob" style={{ background: "radial-gradient(circle, #38bdf888 0%, transparent 70%)" }} />
          <div className="realism-inner" style={{ padding: "1.2rem" }}>
            <div className="realism-inner-glow" />
            <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", color: "#38bdf8", fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700 }}>
              <History size={15} />
              <span>{t("historic.average")} {activePollutant.toUpperCase()}</span>
            </div>
            <div style={{ fontSize: "2.1rem", fontWeight: 800, fontFamily: "var(--mono)", color: "#ffffff", margin: "0.45rem 0 0.2rem", lineHeight: 1 }}>
              {avgVal} <span style={{ fontSize: "0.85rem", fontWeight: 400, color: "var(--mist-dim)" }}>{getMetricUnit()}</span>
            </div>
            <div style={{ fontSize: "11.5px", color: "var(--mist)", marginTop: "0.3rem" }}>
              {range === "24h" ? t("historic.weightedMean") : range === "7d" ? t("historic.rollingBaseline") : t("historic.climatologicalBase")}
            </div>
          </div>
        </article>

        {/* 2. Peak Observation */}
        <article className="realism-box">
          <div className="realism-topglow" />
          <div className="realism-blob" style={{ background: "radial-gradient(circle, #f43f5e88 0%, transparent 70%)" }} />
          <div className="realism-inner" style={{ padding: "1.2rem" }}>
            <div className="realism-inner-glow" />
            <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", color: "#f43f5e", fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700 }}>
              <AlertTriangle size={15} />
              <span>{t("historic.peakObservation")}</span>
            </div>
            <div style={{ fontSize: "2.1rem", fontWeight: 800, fontFamily: "var(--mono)", color: "#f43f5e", margin: "0.45rem 0 0.2rem", lineHeight: 1 }}>
              {maxVal} <span style={{ fontSize: "0.85rem", fontWeight: 400, color: "var(--mist-dim)" }}>{getMetricUnit()}</span>
            </div>
            <div style={{ fontSize: "11.5px", color: "var(--mist)", marginTop: "0.3rem" }}>
              {peakSubtitle}
            </div>
          </div>
        </article>

        {/* 3. Cleanest Window */}
        <article className="realism-box">
          <div className="realism-topglow" />
          <div className="realism-blob" style={{ background: "radial-gradient(circle, #10b98188 0%, transparent 70%)" }} />
          <div className="realism-inner" style={{ padding: "1.2rem" }}>
            <div className="realism-inner-glow" />
            <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", color: "#10b981", fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700 }}>
              <CheckCircle2 size={15} />
              <span>{t("historic.cleanestWindow")}</span>
            </div>
            <div style={{ fontSize: "2.1rem", fontWeight: 800, fontFamily: "var(--mono)", color: "#10b981", margin: "0.45rem 0 0.2rem", lineHeight: 1 }}>
              {minVal} <span style={{ fontSize: "0.85rem", fontWeight: 400, color: "var(--mist-dim)" }}>{getMetricUnit()}</span>
            </div>
            <div style={{ fontSize: "11.5px", color: "var(--mist)", marginTop: "0.3rem" }}>
              {cleanestSubtitle}
            </div>
          </div>
        </article>

        {/* 4. Day / Night Delta */}
        <article className="realism-box">
          <div className="realism-topglow" />
          <div className="realism-blob" style={{ background: "radial-gradient(circle, #c084fc88 0%, transparent 70%)" }} />
          <div className="realism-inner" style={{ padding: "1.2rem" }}>
            <div className="realism-inner-glow" />
            <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", color: "#c084fc", fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700 }}>
              <TrendingUp size={15} />
              <span>{t("historic.dayNightDelta")}</span>
            </div>
            <div style={{ fontSize: "2.1rem", fontWeight: 800, fontFamily: "var(--mono)", color: "#ffffff", margin: "0.45rem 0 0.2rem", lineHeight: 1 }}>
              +{(maxVal - minVal)} <span style={{ fontSize: "0.85rem", fontWeight: 400, color: "var(--mist-dim)" }}>{getMetricUnit()}</span>
            </div>
            <div style={{ fontSize: "11.5px", color: "var(--mist)", marginTop: "0.3rem" }}>
              {t("historic.diurnalAmplitude")}
            </div>
          </div>
        </article>
      </div>

      {/* ── ULTRA-PREMIUM HISTORICAL CHART SECTION (REALISM SHINY BOX) ── */}
      <article className="realism-box" style={{ width: "100%" }}>
        <div className="realism-topglow" />
        <div className="realism-blob" style={{ background: `radial-gradient(circle, ${activeColor}55 0%, transparent 70%)` }} />
        <div className="realism-inner" style={{ padding: "clamp(1.2rem, 2vw, 1.8rem)" }}>
          <div className="realism-inner-glow" />

          {/* Chart Header & Visual View Controls */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "1rem", marginBottom: "1.2rem" }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <span className="daily-pulse-dot" style={{ background: activeColor, boxShadow: `0 0 10px ${activeColor}` }} />
                <span style={{ fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--cyan)", fontWeight: 700 }}>
                  {t("historic.retrospectiveTelemetry")}
                </span>
              </div>
              <h3 style={{ fontSize: "1.3rem", fontWeight: 600, color: "var(--bone)", margin: "0.25rem 0 0", letterSpacing: "-0.01em" }}>
                {range === "24h" && t("historic.timeline24h")}
                {range === "7d" && t("historic.timeline7d")}
                {range === "diurnal" && t("historic.timelineDiurnal")}
              </h3>
            </div>

            {/* Animation & Chart Mode Switcher */}
            {range !== "diurnal" && (
              <div
                style={{
                  display: "inline-flex",
                  background: "rgba(5, 8, 14, 0.9)",
                  borderRadius: "8px",
                  padding: "3px",
                  border: "1px solid var(--hairline-2)",
                  boxShadow: "inset 0 2px 6px rgba(0,0,0,0.6)",
                }}
              >
                <button
                  type="button"
                  onClick={() => setChartType("wave")}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "0.45rem 0.85rem",
                    borderRadius: "6px",
                    fontSize: "12px",
                    fontFamily: "var(--mono)",
                    fontWeight: 700,
                    cursor: "pointer",
                    border: "none",
                    background: chartType === "wave" ? "linear-gradient(135deg, #38bdf8, #0284c7)" : "transparent",
                    color: chartType === "wave" ? "#04111d" : "var(--mist)",
                    boxShadow: chartType === "wave" ? "0 2px 10px rgba(56, 189, 248, 0.4)" : "none",
                    transition: "all 0.2s ease",
                  }}
                >
                  <Waves size={14} /> {t("historic.luminousWave")}
                </button>
                <button
                  type="button"
                  onClick={() => setChartType("bars")}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "0.45rem 0.85rem",
                    borderRadius: "6px",
                    fontSize: "12px",
                    fontFamily: "var(--mono)",
                    fontWeight: 700,
                    cursor: "pointer",
                    border: "none",
                    background: chartType === "bars" ? "linear-gradient(135deg, #38bdf8, #0284c7)" : "transparent",
                    color: chartType === "bars" ? "#04111d" : "var(--mist)",
                    boxShadow: chartType === "bars" ? "0 2px 10px rgba(56, 189, 248, 0.4)" : "none",
                    transition: "all 0.2s ease",
                  }}
                >
                  <BarChart3 size={14} /> {t("historic.spectralBars")}
                </button>
              </div>
            )}
          </div>

          {/* ── TIME-SERIES & 7-DAY CHARTS ── */}
          {range !== "diurnal" ? (
            <div style={{ width: "100%", height: "330px", marginTop: "1rem" }}>
              <ResponsiveContainer width="100%" height="100%">
                {chartType === "wave" ? (
                  <AreaChart data={currentDataset} margin={{ top: 15, right: 15, left: -15, bottom: 0 }}>
                    <defs>
                      <linearGradient id="hist-gradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={activeColor} stopOpacity={0.8} />
                        <stop offset="50%" stopColor={activeColor} stopOpacity={0.35} />
                        <stop offset="95%" stopColor={activeColor} stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.08)" vertical={false} />
                    <XAxis
                      dataKey={range === "24h" ? "hour" : "date"}
                      stroke="rgba(255, 255, 255, 0.5)"
                      fontSize={11}
                      fontFamily="var(--mono)"
                      tickLine={false}
                      interval={range === "24h" ? 2 : 0}
                    />
                    <YAxis
                      stroke="rgba(255, 255, 255, 0.5)"
                      fontSize={11}
                      fontFamily="var(--mono)"
                      tickLine={false}
                      unit={` ${getMetricUnit()}`}
                    />
                    <ReferenceLine
                      y={avgVal}
                      stroke="rgba(255, 255, 255, 0.25)"
                      strokeDasharray="4 4"
                      label={{
                        value: `Mean: ${avgVal}`,
                        fill: "var(--mist)",
                        fontSize: 10,
                        fontFamily: "var(--mono)",
                        position: "right",
                      }}
                    />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload || !payload.length) return null;
                        const d = payload[0].payload as HistoricalPoint;
                        const val = getMetricValue(d);
                        const cat = d.cat || aqiToCategory(d.aqi);
                        const cColor = safeCategoryColor(cat);
                        return (
                          <div
                            style={{
                              background: "rgba(10, 16, 26, 0.95)",
                              border: `1px solid ${activeColor}55`,
                              borderRadius: "10px",
                              padding: "0.85rem 1.1rem",
                              boxShadow: `0 14px 35px rgba(0, 0, 0, 0.8), 0 0 20px ${activeColor}22`,
                              backdropFilter: "blur(12px)",
                              fontFamily: "var(--mono)",
                              fontSize: "12px",
                              minWidth: "210px",
                            }}
                          >
                            <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid rgba(255,255,255,0.1)", paddingBottom: "0.4rem", marginBottom: "0.5rem" }}>
                              <span style={{ color: "var(--mist)", fontSize: "11px" }}>{d.time || d.day}</span>
                              <span style={{ color: cColor, fontWeight: 700, fontSize: "11px" }}>● {cat}</span>
                            </div>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                              <span style={{ color: "var(--bone)", fontSize: "11.5px" }}>{activePollutant.toUpperCase()} Level:</span>
                              <span style={{ color: activeColor, fontWeight: 800, fontSize: "1.3rem" }}>
                                {val} <span style={{ fontSize: "0.75rem", fontWeight: 400 }}>{getMetricUnit()}</span>
                              </span>
                            </div>
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.3rem", marginTop: "0.5rem", paddingTop: "0.4rem", borderTop: "1px solid rgba(255,255,255,0.06)", fontSize: "10.5px", color: "var(--mist)" }}>
                              <span>PM2.5: <strong style={{ color: "#fff" }}>{d.pm25}</strong></span>
                              <span>PM10: <strong style={{ color: "#fff" }}>{d.pm10}</strong></span>
                              <span>NO₂: <strong style={{ color: "#fff" }}>{d.no2}</strong></span>
                              <span>AQI: <strong style={{ color: safeCategoryColor(d.cat) }}>{d.aqi}</strong></span>
                            </div>
                          </div>
                        );
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey={getMetricValue}
                      stroke={activeColor}
                      strokeWidth={2.8}
                      fill="url(#hist-gradient)"
                      isAnimationActive={true}
                      animationDuration={1100}
                      animationEasing="ease-out"
                    />
                  </AreaChart>
                ) : (
                  <BarChart data={currentDataset} margin={{ top: 15, right: 15, left: -15, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.08)" vertical={false} />
                    <XAxis
                      dataKey={range === "24h" ? "hour" : "date"}
                      stroke="rgba(255, 255, 255, 0.5)"
                      fontSize={11}
                      fontFamily="var(--mono)"
                      tickLine={false}
                      interval={range === "24h" ? 2 : 0}
                    />
                    <YAxis
                      stroke="rgba(255, 255, 255, 0.5)"
                      fontSize={11}
                      fontFamily="var(--mono)"
                      tickLine={false}
                      unit={` ${getMetricUnit()}`}
                    />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload || !payload.length) return null;
                        const d = payload[0].payload as HistoricalPoint;
                        const val = getMetricValue(d);
                        const cat = d.cat || aqiToCategory(d.aqi);
                        const cColor = safeCategoryColor(cat);
                        return (
                          <div
                            style={{
                              background: "rgba(10, 16, 26, 0.95)",
                              border: `1px solid ${activeColor}55`,
                              borderRadius: "10px",
                              padding: "0.85rem 1.1rem",
                              boxShadow: `0 14px 35px rgba(0, 0, 0, 0.8), 0 0 20px ${activeColor}22`,
                              backdropFilter: "blur(12px)",
                              fontFamily: "var(--mono)",
                              fontSize: "12px",
                              minWidth: "210px",
                            }}
                          >
                            <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid rgba(255,255,255,0.1)", paddingBottom: "0.4rem", marginBottom: "0.5rem" }}>
                              <span style={{ color: "var(--mist)", fontSize: "11px" }}>{d.time || d.day}</span>
                              <span style={{ color: cColor, fontWeight: 700, fontSize: "11px" }}>● {cat}</span>
                            </div>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                              <span style={{ color: "var(--bone)", fontSize: "11.5px" }}>{activePollutant.toUpperCase()} Level:</span>
                              <span style={{ color: activeColor, fontWeight: 800, fontSize: "1.3rem" }}>
                                {val} <span style={{ fontSize: "0.75rem", fontWeight: 400 }}>{getMetricUnit()}</span>
                              </span>
                            </div>
                          </div>
                        );
                      }}
                    />
                    <Bar
                      dataKey={getMetricValue}
                      radius={[4, 4, 0, 0]}
                      isAnimationActive={true}
                      animationDuration={1100}
                      animationEasing="ease-out"
                    >
                      {currentDataset.map((entry: HistoricalPoint, index: number) => {
                        const barColor =
                          activePollutant === "aqi"
                            ? safeCategoryColor(entry.cat)
                            : activeColor;
                        return <Cell key={`cell-${index}`} fill={barColor} fillOpacity={0.85} />;
                      })}
                    </Bar>
                  </BarChart>
                )}
              </ResponsiveContainer>
            </div>
          ) : (
            /* ── DIURNAL CLIMATOLOGICAL CYCLE CARDS ── */
            <div style={{ marginTop: "1.2rem" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1rem" }}>
                {diurnalProfile.map((d, i) => {
                  const isPeak = d.hour === "08:00";
                  const isClean = d.hour === "15:00";
                  const cardColor = isPeak ? "#f43f5e" : isClean ? "#10b981" : safeCategoryColor(d.cat);
                  const Icon = isPeak ? Zap : isClean ? Sun : d.hour >= "19:00" || d.hour < "06:00" ? Moon : Clock;

                  return (
                    <div
                      key={i}
                      style={{
                        background: isPeak ? "rgba(244, 63, 94, 0.08)" : isClean ? "rgba(16, 185, 129, 0.08)" : "rgba(255, 255, 255, 0.03)",
                        border: `1px solid ${isPeak ? "rgba(244, 63, 94, 0.4)" : isClean ? "rgba(16, 185, 129, 0.4)" : "var(--hairline)"}`,
                        borderRadius: "10px",
                        padding: "1.2rem",
                        position: "relative",
                        transition: "all 0.25s ease",
                      }}
                    >
                      {isPeak && (
                        <span style={{ position: "absolute", top: "10px", right: "10px", fontSize: "9px", fontFamily: "var(--mono)", fontWeight: 800, background: "#f43f5e", color: "#fff", padding: "2px 6px", borderRadius: "3px", textTransform: "uppercase" }}>
                          Diurnal Peak
                        </span>
                      )}
                      {isClean && (
                        <span style={{ position: "absolute", top: "10px", right: "10px", fontSize: "9px", fontFamily: "var(--mono)", fontWeight: 800, background: "#10b981", color: "#000", padding: "2px 6px", borderRadius: "3px", textTransform: "uppercase" }}>
                          Cleanest Hour
                        </span>
                      )}

                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", color: cardColor }}>
                          <Icon size={16} />
                          <span style={{ fontSize: "13px", fontFamily: "var(--mono)", fontWeight: 700 }}>{d.hour} IST</span>
                        </div>
                        <span
                          style={{
                            padding: "2px 8px",
                            borderRadius: "12px",
                            fontSize: "11px",
                            fontFamily: "var(--mono)",
                            fontWeight: 700,
                            background: `${safeCategoryColor(d.cat)}20`,
                            color: safeCategoryColor(d.cat),
                            border: `1px solid ${safeCategoryColor(d.cat)}40`,
                          }}
                        >
                          AQI {d.aqi} • {d.cat}
                        </span>
                      </div>

                      <h4 style={{ margin: "0.4rem 0 0.3rem", fontSize: "15px", color: "var(--bone)", fontWeight: 700 }}>
                        {d.label}
                      </h4>
                      <p style={{ margin: 0, fontSize: "12px", color: "var(--mist)", lineHeight: 1.5 }}>
                        {d.note}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </article>
    </section>
  );
}
export default HistoricalData;
