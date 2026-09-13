import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Armchair,
  Bike,
  CheckCircle2,
  Cigarette,
  Clock,
  Dumbbell,
  Footprints,
  HeartPulse,
  Info,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { calculateExposure } from "@/lib/api";
import type {
  ActivityType,
  ExposureResponse,
  ForecastResponse,
} from "@/lib/types";
import { useTranslation } from "@/i18n";

interface Props {
  currentPm25: number;
  forecast: {
    data: ForecastResponse | null;
    status: "idle" | "loading" | "ok" | "error";
  };
}

interface ActivityArchetype {
  type: ActivityType;
  id: string;
  label: string;
  sublabel: string;
  rate: number;
  icon: typeof Activity;
}

const ACTIVITIES: ActivityArchetype[] = [
  {
    type: "resting",
    id: "resting",
    label: "Resting / Indoor",
    sublabel: "Desk work, sleeping, indoor study",
    rate: 0.5,
    icon: Armchair,
  },
  {
    type: "moderate",
    id: "walking",
    label: "Walking / Commute",
    sublabel: "Brisk walking, errand, light transit",
    rate: 1.2,
    icon: Footprints,
  },
  {
    type: "heavy",
    id: "running",
    label: "Running / Jogging",
    sublabel: "Aerobic cardio, tempo running",
    rate: 2.8,
    icon: Activity,
  },
  {
    type: "heavy",
    id: "cycling",
    label: "Cycling / Fast Pace",
    sublabel: "Road biking, sustained commuting",
    rate: 3.5,
    icon: Bike,
  },
  {
    type: "heavy",
    id: "hiit",
    label: "High-Intensity Sport",
    sublabel: "HIIT, football, outdoor CrossFit",
    rate: 4.5,
    icon: Dumbbell,
  },
];

const DURATION_PRESETS = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12];

const MASK_OPTIONS = [
  { id: "none", label: "No Mask", sub: "0% Filtration", efficiency: 0.0, icon: ShieldAlert },
  { id: "cloth", label: "Cloth / Surgical", sub: "30% Filtration", efficiency: 0.3, icon: ShieldCheck },
  { id: "kn95", label: "KN95 / FFP2", sub: "80% Filtration", efficiency: 0.8, icon: ShieldCheck },
  { id: "n95", label: "N95 Certified", sub: "95% Filtration", efficiency: 0.95, icon: ShieldCheck },
];

export function ExposureTracker({ currentPm25, forecast }: Props) {
  const { t } = useTranslation();
  const [selectedArchetype, setSelectedArchetype] = useState<string>("running");
  const [customRate, setCustomRate] = useState<number>(2.8);
  const [durationHours, setDurationHours] = useState<number>(1.5);
  const [startHourOffset, setStartHourOffset] = useState<number>(0);
  const [maskId, setMaskId] = useState<string>("none");
  const [_exposureData, setExposureData] = useState<ExposureResponse | null>(null);

  // Extract 72h forecast array from physics engine
  const forecastHours = useMemo(() => {
    return forecast.data?.forecast_hours ?? [];
  }, [forecast.data]);

  const activeMask = MASK_OPTIONS.find((m) => m.id === maskId) || MASK_OPTIONS[0];
  const maskMultiplier = 1 - activeMask.efficiency;

  // Derive target string for API (e.g. "+0h", "+4h")
  const targetTimeStr = `+${startHourOffset}h`;

  // Update breathing rate when archetype changes
  const handleSelectArchetype = (arch: ActivityArchetype) => {
    setSelectedArchetype(arch.id);
    setCustomRate(arch.rate);
  };

  // Helper to format human-readable schedule timestamp
  const formatTimeSlot = (offset: number) => {
    if (offset === 0) return "Now (Live)";
    if (forecastHours[offset]?.timestamp) {
      const d = new Date(forecastHours[offset].timestamp);
      if (!isNaN(d.getTime())) {
        const dayStr = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
        const timeStr = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
        return `${dayStr}, ${timeStr} (+${offset}h)`;
      }
    }
    const now = new Date();
    const target = new Date(now.getTime() + offset * 3600 * 1000);
    const dayStr = target.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
    const timeStr = target.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
    return `${dayStr}, ${timeStr} (+${offset}h)`;
  };

  // Build chart points from 72h forecast
  const chartPoints = useMemo(() => {
    if (!forecastHours.length) {
      return Array.from({ length: 72 }).map((_, i) => ({
        hour: `+${i}h`,
        index: i,
        time: `+${i}h`,
        pm25: Math.round(currentPm25),
      }));
    }
    return forecastHours.map((h, i) => {
      let pm = currentPm25;
      if (h.sub_indices) {
        const s = h.sub_indices.find(
          (sub) =>
            sub.pollutant.toLowerCase().includes("25") ||
            sub.pollutant.toLowerCase().includes("2.5")
        );
        if (s) pm = s.concentration;
      }
      const d = h.timestamp ? new Date(h.timestamp) : null;
      const label = d && !isNaN(d.getTime())
        ? `${d.toLocaleDateString("en-US", { weekday: "short" })} ${d.getHours()}:00`
        : `+${i}h`;
      return {
        hour: `+${i}h`,
        index: i,
        time: label,
        pm25: Math.round(pm * 10) / 10,
      };
    });
  }, [forecastHours, currentPm25]);

  // Client-side Sliding Window Optimization to find lowest exposure window
  const clientOptimization = useMemo(() => {
    if (chartPoints.length === 0) return null;
    const windowLength = Math.max(1, Math.round(durationHours));
    let minAvg = Infinity;
    let bestIndex = 0;

    for (let i = 0; i <= chartPoints.length - windowLength; i++) {
      const slice = chartPoints.slice(i, i + windowLength);
      const avg = slice.reduce((sum, p) => sum + p.pm25, 0) / slice.length;
      if (avg < minAvg) {
        minAvg = avg;
        bestIndex = i;
      }
    }

    // Scheduled average
    const schedSlice = chartPoints.slice(startHourOffset, startHourOffset + windowLength);
    const schedAvg = schedSlice.length > 0
      ? schedSlice.reduce((sum, p) => sum + p.pm25, 0) / schedSlice.length
      : currentPm25;

    const currentDose = Math.round(schedAvg * customRate * durationHours * maskMultiplier * 10) / 10;
    const optimalDose = Math.round(minAvg * customRate * durationHours * maskMultiplier * 10) / 10;
    const savedDose = Math.max(0, Math.round((currentDose - optimalDose) * 10) / 10);
    const reductionPercent = currentDose > 0 ? Math.round((savedDose / currentDose) * 100) : 0;

    return {
      bestIndex,
      bestHourStr: `+${bestIndex}h`,
      minAvg: Math.round(minAvg * 10) / 10,
      schedAvg: Math.round(schedAvg * 10) / 10,
      currentDose,
      optimalDose,
      savedDose,
      reductionPercent,
    };
  }, [chartPoints, durationHours, startHourOffset, customRate, maskMultiplier, currentPm25]);

  // Fetch from API when parameters change, or fall back to client computation
  useEffect(() => {
    let cancelled = false;
    async function runCalc() {
      try {
        const formattedFc = chartPoints.map((p) => ({
          index: p.index,
          pm25: p.pm25,
          time: p.hour,
        }));

        const res = await calculateExposure({
          activity_type: selectedArchetype as ActivityType,
          duration_hours: durationHours,
          target_time: targetTimeStr,
          current_pm25: currentPm25,
          forecast_72h: formattedFc,
        });

        if (!cancelled && res) {
          setExposureData(res);
        }
      } catch {
        // Handled gracefully via clientCalculation fallback
      }
    }
    runCalc();
    return () => {
      cancelled = true;
    };
  }, [selectedArchetype, durationHours, targetTimeStr, currentPm25, chartPoints]);

  // Final Inhaled Mass & Cigarette Computations with Mask Efficiency
  const finalInhaledMass = clientOptimization ? clientOptimization.currentDose : 0;
  const finalCigarettes = Math.max(
    0.01,
    Math.round(((clientOptimization?.schedAvg ?? currentPm25) / 22) * (durationHours / 24) * (customRate / 1.5) * maskMultiplier * 100) / 100
  );

  const bestOptIdx = clientOptimization?.bestIndex ?? 0;
  const targetEndIdx = Math.min(chartPoints.length - 1, startHourOffset + Math.max(1, Math.ceil(durationHours)));
  const optimalEndIdx = Math.min(chartPoints.length - 1, bestOptIdx + Math.max(1, Math.ceil(durationHours)));

  // Risk warning text
  const currentRiskTier = useMemo(() => {
    const conc = clientOptimization?.schedAvg ?? currentPm25;
    if (finalInhaledMass > 400 || conc > 150) {
      return {
        tier: t("exposure.hazardousExertion"),
        color: "#f43f5e",
        text: t("exposure.hazardousExertionText"),
      };
    }
    if (finalInhaledMass > 180 || conc > 90) {
      return {
        tier: t("exposure.elevatedRisk"),
        color: "#fbbf24",
        text: t("exposure.elevatedRiskText"),
      };
    }
    return {
      tier: t("exposure.lowRisk"),
      color: "#10b981",
      text: t("exposure.lowRiskText"),
    };
  }, [finalInhaledMass, clientOptimization, currentPm25, t]);

  const getActivityLabel = (id: string, def: string) => {
    switch (id) {
      case "resting": return t("exposure.activityResting");
      case "walking": return t("exposure.activityModerate");
      case "running": return t("exposure.activityHeavy");
      case "cycling": return t("exposure.activityCycling");
      case "hiit": return t("exposure.activityHiit");
      default: return def;
    }
  };

  const getActivitySublabel = (id: string, def: string) => {
    switch (id) {
      case "resting": return t("exposure.activityRestingSub");
      case "walking": return t("exposure.activityModerateSub");
      case "running": return t("exposure.activityHeavySub");
      case "cycling": return t("exposure.activityCyclingSub");
      case "hiit": return t("exposure.activityHiitSub");
      default: return def;
    }
  };

  const getMaskLabel = (id: string, def: string) => {
    switch (id) {
      case "none": return t("exposure.noMask");
      case "cloth": return t("exposure.clothMask");
      case "kn95": return t("exposure.kn95Mask");
      case "n95": return t("exposure.n95Mask");
      default: return def;
    }
  };

  const timeSlots = [
    { label: t("exposure.nowLive"), offset: 0 },
    { label: t("exposure.tomorrow07am"), offset: 17 },
    { label: t("exposure.tomorrow02pm"), offset: 24 },
    { label: t("exposure.tomorrow07pm"), offset: 29 },
    { label: t("exposure.day307am"), offset: 41 },
  ];

  return (
    <section
      className="section"
      id="exposure-tracker"
      aria-labelledby="exposure-h"
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
          <p className="eyebrow" style={{ color: "var(--amber)", display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.25rem" }}>
            <HeartPulse size={14} /> micro-level human health dosimetry &amp; outdoor optimizer
          </p>
          <h2
            className="section__h"
            id="exposure-h"
            style={{
              fontSize: "clamp(2.1rem, 3.8vw, 3.0rem)",
              fontWeight: 600,
              letterSpacing: "-0.03em",
              color: "var(--bone)",
              margin: "0.15rem 0 0.4rem 0",
              lineHeight: 1.15,
            }}
          >
            {t("exposure.title")}
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
            {t("exposure.subtitle")}
          </p>
        </div>

        {/* Ambient Baseline Badge */}
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.6rem",
            background: "rgba(255, 255, 255, 0.04)",
            padding: "0.6rem 1.1rem",
            borderRadius: "8px",
            border: "1px solid var(--hairline-2)",
            boxShadow: "0 4px 15px rgba(0,0,0,0.4)",
          }}
        >
          <Clock size={16} style={{ color: "var(--cyan)" }} />
          <span style={{ fontSize: "12.5px", fontFamily: "var(--mono)", color: "var(--bone)" }}>
            {t("exposure.liveAmbient")}: <strong style={{ color: "var(--cyan)", fontSize: "14px" }}>{currentPm25.toFixed(1)} µg/m³</strong>
          </span>
        </div>
      </div>

      {/* ── INTERACTIVE ACTIVITY & DOSIMETRY CONTROLLER (REALISM SHINY BOX) ── */}
      <article className="realism-box" style={{ width: "100%", marginBottom: "1.8rem" }}>
        <div className="realism-topglow" />
        <div className="realism-blob" style={{ background: "radial-gradient(circle, #38bdf866 0%, transparent 70%)" }} />
        <div className="realism-inner" style={{ padding: "clamp(1.2rem, 2.2vw, 1.8rem)" }}>
          <div className="realism-inner-glow" />

          {/* 1. Activity Archetype Grid & Breathing Rate */}
          <div style={{ marginBottom: "1.6rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.8rem" }}>
              <label style={{ fontSize: "12px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--cyan)", fontFamily: "var(--mono)" }}>
                {t("exposure.step1")}
              </label>
              <span style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--bone)" }}>
                {t("exposure.ventilationRate")}: <strong style={{ color: "var(--cyan)" }}>{customRate.toFixed(1)} m³/h</strong>
              </span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: "0.75rem" }}>
              {ACTIVITIES.map((act) => {
                const Icon = act.icon;
                const isSelected = selectedArchetype === act.id;
                return (
                  <button
                    key={act.id}
                    type="button"
                    onClick={() => handleSelectArchetype(act)}
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "flex-start",
                      padding: "0.9rem 1rem",
                      borderRadius: "10px",
                      background: isSelected
                        ? "linear-gradient(135deg, rgba(56, 189, 248, 0.2), rgba(2, 132, 199, 0.08))"
                        : "rgba(255, 255, 255, 0.02)",
                      border: `1px solid ${isSelected ? "var(--cyan)" : "rgba(255, 255, 255, 0.08)"}`,
                      boxShadow: isSelected ? "0 4px 15px rgba(56, 189, 248, 0.25)" : "none",
                      color: isSelected ? "#fff" : "var(--bone)",
                      cursor: "pointer",
                      textAlign: "left",
                      transition: "all 0.2s ease",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", width: "100%", alignItems: "center", marginBottom: "0.4rem" }}>
                      <Icon size={20} style={{ color: isSelected ? "var(--cyan)" : "var(--mist)" }} />
                      <span style={{ fontSize: "11px", fontFamily: "var(--mono)", fontWeight: 700, color: isSelected ? "var(--cyan)" : "var(--mist-dim)" }}>
                        {act.rate} m³/h
                      </span>
                    </div>
                    <span style={{ fontSize: "13px", fontWeight: 700, marginBottom: "0.2rem" }}>{getActivityLabel(act.id, act.label)}</span>
                    <span style={{ fontSize: "11px", color: "var(--mist-dim)", lineHeight: 1.3 }}>{getActivitySublabel(act.id, act.sublabel)}</span>
                  </button>
                );
              })}
            </div>

            {/* Fine-Tuning Slider for Breathing Rate */}
            <div style={{ marginTop: "1rem", display: "flex", alignItems: "center", gap: "1rem", background: "rgba(0, 0, 0, 0.3)", padding: "0.6rem 1rem", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
              <span style={{ fontSize: "11px", fontFamily: "var(--mono)", color: "var(--mist-dim)", whiteSpace: "nowrap" }}>
                {t("exposure.fineTuneExertion")}
              </span>
              <input
                type="range"
                min={0.4}
                max={5.0}
                step={0.1}
                value={customRate}
                onChange={(e) => {
                  setCustomRate(parseFloat(e.target.value));
                  setSelectedArchetype("custom");
                }}
                style={{ flex: 1, accentColor: "var(--cyan)", cursor: "pointer" }}
              />
              <span style={{ fontSize: "12px", fontFamily: "var(--mono)", fontWeight: 700, color: "var(--cyan)", minWidth: "55px", textAlign: "right" }}>
                {customRate.toFixed(1)} m³/h
              </span>
            </div>
          </div>

          {/* 2. Flexible Duration & 3. 72-Hour Scheduled Start Time */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "1.6rem", marginBottom: "1.6rem" }}>
            {/* Flexible Duration Controller */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.6rem" }}>
                <label style={{ fontSize: "12px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--cyan)", fontFamily: "var(--mono)" }}>
                  {t("exposure.step2")}
                </label>
                <span style={{ fontFamily: "var(--mono)", fontSize: "14px", fontWeight: 800, color: "#fff" }}>
                  {durationHours >= 1 ? `${durationHours} ${durationHours === 1 ? t("exposure.hour") : t("exposure.hours")}` : `${Math.round(durationHours * 60)} ${t("exposure.minutes")}`}
                </span>
              </div>

              {/* Continuous Duration Slider */}
              <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", marginBottom: "0.8rem" }}>
                <button
                  type="button"
                  onClick={() => setDurationHours((prev) => Math.max(0.25, Math.round((prev - 0.25) * 100) / 100))}
                  style={{
                    background: "rgba(255, 255, 255, 0.06)",
                    border: "1px solid var(--hairline-2)",
                    borderRadius: "6px",
                    color: "var(--bone)",
                    padding: "0.3rem 0.65rem",
                    fontFamily: "var(--mono)",
                    fontSize: "12px",
                    cursor: "pointer",
                  }}
                >
                  -15m
                </button>
                <input
                  type="range"
                  min={0.25}
                  max={12}
                  step={0.25}
                  value={durationHours}
                  onChange={(e) => setDurationHours(parseFloat(e.target.value))}
                  style={{ flex: 1, accentColor: "var(--cyan)", cursor: "pointer" }}
                />
                <button
                  type="button"
                  onClick={() => setDurationHours((prev) => Math.min(12, Math.round((prev + 0.25) * 100) / 100))}
                  style={{
                    background: "rgba(255, 255, 255, 0.06)",
                    border: "1px solid var(--hairline-2)",
                    borderRadius: "6px",
                    color: "var(--bone)",
                    padding: "0.3rem 0.65rem",
                    fontFamily: "var(--mono)",
                    fontSize: "12px",
                    cursor: "pointer",
                  }}
                >
                  +15m
                </button>
              </div>

              {/* Quick Duration Preset Chips */}
              <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                {DURATION_PRESETS.map((dur) => (
                  <button
                    key={dur}
                    type="button"
                    onClick={() => setDurationHours(dur)}
                    style={{
                      flex: "1 1 35px",
                      padding: "0.4rem 0.2rem",
                      background: durationHours === dur ? "#38bdf8" : "rgba(255, 255, 255, 0.04)",
                      color: durationHours === dur ? "#04111d" : "var(--bone)",
                      border: `1px solid ${durationHours === dur ? "#38bdf8" : "rgba(255, 255, 255, 0.08)"}`,
                      borderRadius: "6px",
                      fontSize: "11px",
                      fontFamily: "var(--mono)",
                      fontWeight: 700,
                      cursor: "pointer",
                      transition: "all 0.15s ease",
                      textAlign: "center",
                    }}
                  >
                    {dur < 1 ? `${Math.round(dur * 60)}m` : `${dur}h`}
                  </button>
                ))}
              </div>
            </div>

            {/* Continuous 72-Hour Scheduled Start Time */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.6rem" }}>
                <label style={{ fontSize: "12px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--cyan)", fontFamily: "var(--mono)" }}>
                  {t("exposure.step3")}
                </label>
                <span style={{ fontFamily: "var(--mono)", fontSize: "13px", fontWeight: 800, color: "var(--amber)" }}>
                  {formatTimeSlot(startHourOffset)}
                </span>
              </div>

              {/* 72h Continuous Time Slider */}
              <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", marginBottom: "0.8rem" }}>
                <input
                  type="range"
                  min={0}
                  max={Math.max(0, chartPoints.length - 1)}
                  step={1}
                  value={startHourOffset}
                  onChange={(e) => setStartHourOffset(parseInt(e.target.value, 10))}
                  style={{ flex: 1, accentColor: "var(--amber)", cursor: "pointer" }}
                />
              </div>

              {/* Contextual Smart Jump Chips */}
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                {timeSlots.map((slot) => (
                  <button
                    key={slot.label}
                    type="button"
                    onClick={() => setStartHourOffset(Math.min(chartPoints.length - 1, slot.offset))}
                    style={{
                      flex: "1 1 110px",
                      padding: "0.4rem 0.6rem",
                      background: startHourOffset === slot.offset ? "rgba(245, 158, 11, 0.2)" : "rgba(255, 255, 255, 0.04)",
                      border: `1px solid ${startHourOffset === slot.offset ? "var(--amber)" : "rgba(255, 255, 255, 0.08)"}`,
                      color: startHourOffset === slot.offset ? "var(--amber)" : "var(--bone)",
                      borderRadius: "6px",
                      fontSize: "11px",
                      fontFamily: "var(--mono)",
                      fontWeight: 700,
                      cursor: "pointer",
                      transition: "all 0.15s ease",
                      textAlign: "center",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {slot.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* 4. Mask & Personal Filtration Protection Factor */}
          <div>
            <label style={{ fontSize: "12px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--cyan)", fontFamily: "var(--mono)", display: "block", marginBottom: "0.6rem" }}>
              {t("exposure.step4")}
            </label>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "0.65rem" }}>
              {MASK_OPTIONS.map((m) => {
                const isSelected = maskId === m.id;
                const Icon = m.icon;
                return (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setMaskId(m.id)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "0.75rem",
                      padding: "0.65rem 0.9rem",
                      borderRadius: "8px",
                      background: isSelected ? "rgba(16, 185, 129, 0.15)" : "rgba(255, 255, 255, 0.02)",
                      border: `1px solid ${isSelected ? "#10b981" : "rgba(255, 255, 255, 0.08)"}`,
                      color: isSelected ? "#10b981" : "var(--bone)",
                      cursor: "pointer",
                      transition: "all 0.2s ease",
                      textAlign: "left",
                    }}
                  >
                    <Icon size={18} style={{ color: isSelected ? "#10b981" : "var(--mist)" }} />
                    <div>
                      <div style={{ fontSize: "12px", fontWeight: 700 }}>{getMaskLabel(m.id, m.label)}</div>
                      <div style={{ fontSize: "10.5px", color: isSelected ? "#10b981" : "var(--mist-dim)", fontFamily: "var(--mono)" }}>
                        {m.efficiency * 100}% {t("exposure.filtration")}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </article>

      {/* ── 3 CORE REALISM SHINY DOSIMETRY STATS CARDS ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "1.1rem", marginBottom: "1.8rem" }}>
        {/* Card 1: Inhaled Alveolar PM2.5 Mass */}
        <article className="realism-box">
          <div className="realism-topglow" />
          <div className="realism-blob" style={{ background: "radial-gradient(circle, #38bdf888 0%, transparent 70%)" }} />
          <div className="realism-inner" style={{ padding: "1.2rem" }}>
            <div className="realism-inner-glow" />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", color: "#38bdf8", fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700 }}>
                <Zap size={15} />
                <span>{t("exposure.inhaledAlveolar")}</span>
              </div>
              {activeMask.efficiency > 0 && (
                <span style={{ fontSize: "10px", fontFamily: "var(--mono)", background: "#10b98120", color: "#10b981", border: "1px solid #10b98140", padding: "1px 6px", borderRadius: "4px" }}>
                  -{Math.round(activeMask.efficiency * 100)}% Masked
                </span>
              )}
            </div>

            <div style={{ fontSize: "2.3rem", fontWeight: 800, fontFamily: "var(--mono)", color: "#ffffff", margin: "0.45rem 0 0.2rem", lineHeight: 1 }}>
              {finalInhaledMass} <span style={{ fontSize: "0.95rem", fontWeight: 400, color: "var(--mist-dim)" }}>µg</span>
            </div>
            <div style={{ fontSize: "11.5px", color: "var(--mist)", marginTop: "0.3rem" }}>
              {t("exposure.totalMassTrapped")} {durationHours}{t("exposure.hours").charAt(0).toLowerCase()}.
            </div>

            <div style={{ marginTop: "0.8rem", background: "rgba(255, 255, 255, 0.06)", height: "6px", borderRadius: "3px", overflow: "hidden" }}>
              <div
                style={{
                  height: "100%",
                  width: `${Math.min(100, (finalInhaledMass / 600) * 100)}%`,
                  background: finalInhaledMass > 400 ? "#f43f5e" : finalInhaledMass > 180 ? "#fbbf24" : "#38bdf8",
                  transition: "width 0.3s ease",
                }}
              />
            </div>
          </div>
        </article>

        {/* Card 2: Cigarette Equivalents */}
        <article className="realism-box">
          <div className="realism-topglow" />
          <div className="realism-blob" style={{ background: "radial-gradient(circle, #fbbf2488 0%, transparent 70%)" }} />
          <div className="realism-inner" style={{ padding: "1.2rem" }}>
            <div className="realism-inner-glow" />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", color: "#fbbf24", fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700 }}>
                <Cigarette size={15} />
                <span>{t("exposure.cigaretteEquivalence")}</span>
              </div>
            </div>

            <div style={{ fontSize: "2.3rem", fontWeight: 800, fontFamily: "var(--mono)", color: "#fbbf24", margin: "0.45rem 0 0.2rem", lineHeight: 1 }}>
              {finalCigarettes} <span style={{ fontSize: "0.95rem", fontWeight: 400, color: "var(--mist-dim)" }}>cig</span>
            </div>
            <div style={{ fontSize: "11.5px", color: "var(--mist)", marginTop: "0.3rem" }}>
              {t("exposure.berkeleyStandard")}
            </div>

            <div style={{ display: "flex", gap: "4px", marginTop: "0.8rem" }}>
              {Array.from({ length: 6 }).map((_, i) => (
                <div
                  key={i}
                  style={{
                    flex: 1,
                    height: "6px",
                    borderRadius: "3px",
                    background:
                      finalCigarettes >= i + 1
                        ? "#fbbf24"
                        : finalCigarettes > i
                        ? "rgba(251, 191, 36, 0.4)"
                        : "rgba(255, 255, 255, 0.08)",
                  }}
                />
              ))}
            </div>
          </div>
        </article>

        {/* Card 3: Exertion Risk Level */}
        <article className="realism-box">
          <div className="realism-topglow" />
          <div className="realism-blob" style={{ background: `radial-gradient(circle, ${currentRiskTier.color}88 0%, transparent 70%)` }} />
          <div className="realism-inner" style={{ padding: "1.2rem" }}>
            <div className="realism-inner-glow" />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", color: currentRiskTier.color, fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700 }}>
                <ShieldAlert size={15} />
                <span>{currentRiskTier.tier}</span>
              </div>
            </div>

            <div style={{ margin: "0.45rem 0 0.3rem", fontSize: "12.5px", color: "var(--bone)", lineHeight: 1.45, minHeight: "48px" }}>
              {currentRiskTier.text}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "10.5px", color: "var(--mist-dim)", fontFamily: "var(--mono)", marginTop: "0.4rem" }}>
              <Info size={12} /> CPCB &amp; WHO Alveolar Dosimetry Model
            </div>
          </div>
        </article>
      </div>

      {/* ── 72-HOUR SMART OPTIMIZATION & AREA CHART (REALISM SHINY BOX) ── */}
      <article className="realism-box" style={{ width: "100%" }}>
        <div className="realism-topglow" />
        <div className="realism-blob" style={{ background: "radial-gradient(circle, #10b98155 0%, transparent 70%)" }} />
        <div className="realism-inner" style={{ padding: "clamp(1.2rem, 2vw, 1.8rem)" }}>
          <div className="realism-inner-glow" />

          {/* Optimizer Header & AI Recommendation Badge */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "1rem", marginBottom: "1.2rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
              <Sparkles size={20} style={{ color: "#fbbf24" }} />
              <div>
                <h3 style={{ fontSize: "1.3rem", fontWeight: 600, color: "var(--bone)", margin: 0 }}>
                  {t("exposure.smartOptimization")}
                </h3>
                <p style={{ margin: "0.2rem 0 0", fontSize: "12px", color: "var(--mist)" }}>
                  Atmospheric physics sliding-window solver across the entire 72h forecast horizon.
                </p>
              </div>
            </div>

            {clientOptimization && clientOptimization.reductionPercent > 0 ? (
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.4rem",
                  background: "rgba(16, 185, 129, 0.15)",
                  border: "1px solid rgba(16, 185, 129, 0.4)",
                  padding: "0.4rem 0.85rem",
                  borderRadius: "20px",
                  color: "#10b981",
                  fontSize: "12.5px",
                  fontWeight: 700,
                  fontFamily: "var(--mono)",
                  boxShadow: "0 0 15px rgba(16, 185, 129, 0.25)",
                }}
              >
                <CheckCircle2 size={15} />
                {clientOptimization.reductionPercent}% Lower Pollution Dose Available
              </div>
            ) : (
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.4rem",
                  background: "rgba(56, 189, 248, 0.15)",
                  border: "1px solid rgba(56, 189, 248, 0.4)",
                  padding: "0.4rem 0.85rem",
                  borderRadius: "20px",
                  color: "#38bdf8",
                  fontSize: "12.5px",
                  fontWeight: 700,
                  fontFamily: "var(--mono)",
                }}
              >
                Optimal Low-Pollution Window Selected
              </div>
            )}
          </div>

          {/* Actionable Shift Button Banner */}
          {clientOptimization && clientOptimization.bestIndex !== startHourOffset && (
            <div
              style={{
                background: "linear-gradient(90deg, rgba(16, 185, 129, 0.12), rgba(56, 189, 248, 0.08))",
                border: "1px solid rgba(16, 185, 129, 0.35)",
                borderRadius: "8px",
                padding: "0.9rem 1.2rem",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "1rem",
                marginBottom: "1.4rem",
              }}
            >
              <div style={{ flex: "1 1 320px" }}>
                <p style={{ margin: 0, fontSize: "13px", color: "var(--bone)", lineHeight: 1.5 }}>
                  💡 <strong>Physics Recommendation:</strong> Rescheduling your {durationHours}h workout to{" "}
                  <strong style={{ color: "#10b981" }}>{formatTimeSlot(clientOptimization.bestIndex)}</strong> drops average ambient PM2.5 from {clientOptimization.schedAvg} µg/m³ to{" "}
                  <strong style={{ color: "#10b981" }}>{clientOptimization.minAvg} µg/m³</strong>, avoiding <strong>{clientOptimization.savedDose} µg</strong> of toxic alveolar lung dose.
                </p>
              </div>

              <button
                type="button"
                onClick={() => setStartHourOffset(clientOptimization.bestIndex)}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.5rem",
                  background: "linear-gradient(135deg, #10b981, #059669)",
                  color: "#04111d",
                  border: "none",
                  borderRadius: "6px",
                  padding: "0.6rem 1.2rem",
                  fontSize: "12px",
                  fontFamily: "var(--mono)",
                  fontWeight: 800,
                  cursor: "pointer",
                  boxShadow: "0 2px 12px rgba(16, 185, 129, 0.4)",
                  transition: "all 0.2s ease",
                  whiteSpace: "nowrap",
                }}
              >
                ⚡ Shift to Optimal Slot (+{clientOptimization.bestIndex}h)
              </button>
            </div>
          )}

          {/* Comparative Dosimetry Badges */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "0.9rem", marginBottom: "1.4rem" }}>
            <div style={{ background: "rgba(0, 0, 0, 0.3)", padding: "0.9rem", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
              <div style={{ fontSize: "11px", color: "var(--mist-dim)", textTransform: "uppercase", fontFamily: "var(--mono)" }}>Scheduled Window Avg</div>
              <div style={{ fontSize: "1.4rem", fontFamily: "var(--mono)", fontWeight: 800, color: "#fff", margin: "0.2rem 0" }}>
                {clientOptimization?.schedAvg ?? currentPm25} <span style={{ fontSize: "11px", color: "var(--mist-dim)" }}>µg/m³</span>
              </div>
              <div style={{ fontSize: "11.5px", color: "var(--mist)" }}>
                Inhaled: <strong>{clientOptimization?.currentDose ?? 0} µg</strong>
              </div>
            </div>

            <div style={{ background: "rgba(16, 185, 129, 0.08)", padding: "0.9rem", borderRadius: "8px", border: "1px solid rgba(16, 185, 129, 0.3)" }}>
              <div style={{ fontSize: "11px", color: "#10b981", textTransform: "uppercase", fontFamily: "var(--mono)", fontWeight: 700 }}>Cleanest 72h Window Avg</div>
              <div style={{ fontSize: "1.4rem", fontFamily: "var(--mono)", fontWeight: 800, color: "#10b981", margin: "0.2rem 0" }}>
                {clientOptimization?.minAvg ?? currentPm25} <span style={{ fontSize: "11px", color: "var(--mist-dim)" }}>µg/m³</span>
              </div>
              <div style={{ fontSize: "11.5px", color: "#10b981" }}>
                Inhaled: <strong>{clientOptimization?.optimalDose ?? 0} µg</strong>
              </div>
            </div>

            <div style={{ background: "rgba(56, 189, 248, 0.08)", padding: "0.9rem", borderRadius: "8px", border: "1px solid rgba(56, 189, 248, 0.3)" }}>
              <div style={{ fontSize: "11px", color: "#38bdf8", textTransform: "uppercase", fontFamily: "var(--mono)", fontWeight: 700 }}>Avoided Inhaled Dose</div>
              <div style={{ fontSize: "1.4rem", fontFamily: "var(--mono)", fontWeight: 800, color: "#38bdf8", margin: "0.2rem 0" }}>
                -{clientOptimization?.savedDose ?? 0} <span style={{ fontSize: "11px", color: "var(--mist-dim)" }}>µg</span>
              </div>
              <div style={{ fontSize: "11.5px", color: "#38bdf8" }}>
                Saved <strong>{(((clientOptimization?.savedDose ?? 0) / 22) * (durationHours / 24) * (customRate / 1.5) * maskMultiplier).toFixed(2)}</strong> cigarette equivalents
              </div>
            </div>
          </div>

          {/* 72-Hour PM2.5 Trajectory Chart with Dual Highlighted Regions */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.6rem" }}>
              <span style={{ fontSize: "11.5px", fontFamily: "var(--mono)", color: "var(--mist)" }}>
                Continuous 72-Hour PM2.5 Forecast Sounding &amp; Dual Activity Zones
              </span>
              <div style={{ display: "flex", alignItems: "center", gap: "1rem", fontSize: "11px", fontFamily: "var(--mono)" }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "5px", color: "var(--amber)" }}>
                  <span style={{ width: "10px", height: "10px", background: "rgba(245, 158, 11, 0.6)", borderRadius: "2px" }} />
                  Scheduled Slot ({targetTimeStr})
                </span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "5px", color: "#10b981" }}>
                  <span style={{ width: "10px", height: "10px", background: "rgba(16, 185, 129, 0.6)", borderRadius: "2px" }} />
                  Cleanest Slot (+{bestOptIdx}h)
                </span>
              </div>
            </div>

            <div style={{ width: "100%", height: 230 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartPoints} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="exposurePm25Gradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.5} />
                      <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.08)" vertical={false} />
                  <XAxis dataKey="time" stroke="rgba(255, 255, 255, 0.4)" fontSize={10} fontFamily="var(--mono)" interval={8} />
                  <YAxis stroke="rgba(255, 255, 255, 0.4)" fontSize={10} fontFamily="var(--mono)" unit=" µg" />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (!active || !payload || !payload.length) return null;
                      const d = payload[0].payload;
                      return (
                        <div
                          style={{
                            background: "rgba(10, 16, 26, 0.95)",
                            border: "1px solid #38bdf855",
                            borderRadius: "8px",
                            padding: "0.75rem 1rem",
                            boxShadow: "0 10px 30px rgba(0,0,0,0.8)",
                            fontFamily: "var(--mono)",
                            fontSize: "11.5px",
                          }}
                        >
                          <div style={{ color: "var(--mist)", marginBottom: "0.2rem" }}>{d.time} ({d.hour})</div>
                          <div style={{ color: "#38bdf8", fontWeight: 800, fontSize: "1.1rem" }}>
                            {d.pm25} <span style={{ fontSize: "10px", fontWeight: 400 }}>µg/m³</span>
                          </div>
                        </div>
                      );
                    }}
                  />

                  {/* Scheduled Slot Reference Area */}
                  <ReferenceArea
                    x1={chartPoints[startHourOffset]?.time}
                    x2={chartPoints[targetEndIdx]?.time}
                    fill="rgba(245, 158, 11, 0.25)"
                    stroke="rgba(245, 158, 11, 0.8)"
                    strokeDasharray="3 3"
                  />

                  {/* Optimal Cleanest Slot Reference Area */}
                  {bestOptIdx !== startHourOffset && (
                    <ReferenceArea
                      x1={chartPoints[bestOptIdx]?.time}
                      x2={chartPoints[optimalEndIdx]?.time}
                      fill="rgba(16, 185, 129, 0.25)"
                      stroke="rgba(16, 185, 129, 0.8)"
                      strokeDasharray="3 3"
                    />
                  )}

                  <Area
                    type="monotone"
                    dataKey="pm25"
                    stroke="#38bdf8"
                    strokeWidth={2.4}
                    fill="url(#exposurePm25Gradient)"
                    isAnimationActive={true}
                    animationDuration={1000}
                    animationEasing="ease-out"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </article>
    </section>
  );
}
export default ExposureTracker;
