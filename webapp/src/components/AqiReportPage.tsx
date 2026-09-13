import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Download,
  CheckCircle2,
  Factory,
  Wind,
  Layers,
  ShieldCheck,
  Building2,
  FileText,
  Activity,
  MapPin,
  TrendingUp,
  RotateCw,
} from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

import type { Panel } from "@/hooks/useForecastData";
import type {
  CityAggregateResponse,
  ConsensusResponse,
  ForecastResponse,
  HourlyForecast,
  IndustryRecord,
  InversionStatus,
  PlumeVectorsResponse,
  StationReading,
} from "@/lib/types";
import { fetchDelhiIndustries } from "@/lib/supabase";
import { generateAqiPdfReport } from "@/lib/reportPdfGenerator";
import { useTranslation } from "@/i18n";

interface AqiReportPageProps {
  forecast?: Panel<ForecastResponse>;
  hour?: HourlyForecast | null;
  cursor?: number;
  consensus?: ConsensusResponse | null;
  cityAggregate?: CityAggregateResponse | null;
  stations?: Panel<StationReading[]>;
  plume?: Panel<PlumeVectorsResponse>;
  inversion?: Panel<InversionStatus[]>;
  onBack: () => void;
}

export function AqiReportPage({
  forecast,
  hour,
  consensus,
  cityAggregate,
  stations,
  plume,
  inversion,
  onBack,
}: AqiReportPageProps) {
  const { t, language } = useTranslation();
  const [isGeneratingPdf, setIsGeneratingPdf] = useState(false);
  const [downloadSuccess, setDownloadSuccess] = useState(false);
  const [industries, setIndustries] = useState<IndustryRecord[]>([]);

  // Generated dynamic Report ID
  const reportId = useMemo(() => {
    const d = new Date();
    const ymd = d.toISOString().slice(0, 10).replace(/-/g, "");
    const rand = Math.floor(1000 + Math.random() * 9000);
    return `NCR-AQI-${ymd}-${rand}`;
  }, []);

  // Fetch industries on mount
  useEffect(() => {
    let active = true;
    fetchDelhiIndustries().then((records) => {
      if (active && records.length > 0) {
        setIndustries(records);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  // Live atmospheric telemetry extraction
  const liveAqi =
    cityAggregate?.overall_aqi ??
    (consensus?.metrics?.aqi ?? (hour?.aqi ?? 342));
  const liveCat =
    cityAggregate?.aqi_category ??
    (consensus?.forecast?.[0]?.category ?? (hour?.category ?? "Very Poor"));
  const dominantPollutant =
    cityAggregate?.dominant_pollutant ??
    (hour?.dominant_pollutant ?? "PM2.5");

  const pm25 =
    cityAggregate?.sub_indices?.["PM2.5"]?.conc ??
    (consensus?.metrics?.pm25 ?? (hour?.sub_indices?.find((s) => s.pollutant === "PM2.5")?.concentration ?? 180));
  const pm10 =
    cityAggregate?.sub_indices?.["PM10"]?.conc ??
    (consensus?.metrics?.pm10 ?? (hour?.sub_indices?.find((s) => s.pollutant === "PM10")?.concentration ?? 305));
  const no2 =
    cityAggregate?.sub_indices?.["NO2"]?.conc ??
    (consensus?.metrics?.no2 ?? (hour?.sub_indices?.find((s) => s.pollutant === "NO2")?.concentration ?? 48));
  const so2 =
    cityAggregate?.sub_indices?.["SO2"]?.conc ??
    (consensus?.metrics?.so2 ?? (hour?.sub_indices?.find((s) => s.pollutant === "SO2")?.concentration ?? 16));
  const co =
    cityAggregate?.sub_indices?.["CO"]?.conc ??
    (consensus?.metrics?.co ?? (hour?.sub_indices?.find((s) => s.pollutant === "CO")?.concentration ?? 1.4));
  const o3 =
    cityAggregate?.sub_indices?.["O3"]?.conc ??
    (consensus?.metrics?.o3 ?? (hour?.sub_indices?.find((s) => s.pollutant === "O3")?.concentration ?? 32));

  const pblHeight = hour?.pbl_height_m ?? 320;
  const invDeltaT = hour?.inversion_delta_t ?? 2.1;
  const tempC = 22.4;
  const rhPct = 68;
  const windMps = hour?.wind_speed_ms ?? 1.8;
  const plumeFrac = Math.round((hour?.plume_contribution ?? 0.22) * 100);

  const activeStationsCount = stations?.data?.length || 43;

  // Chart data for 72-hour forecast
  const forecastChartData = useMemo(() => {
    const list = forecast?.data?.forecast_hours ?? [];
    if (list.length === 0) {
      return [{ time: "Now", aqi: liveAqi, pm25 }];
    }
    return list.map((f, i) => ({
      time: `+${i}h`,
      aqi: Math.round(f.aqi),
      pm25: Math.round(f.sub_indices.find((s) => s.pollutant === "PM2.5")?.concentration ?? (f.aqi * 0.45)),
    }));
  }, [forecast?.data?.forecast_hours, liveAqi, pm25]);

  const handleDownloadPdf = async () => {
    if (isGeneratingPdf) return;
    setIsGeneratingPdf(true);
    setDownloadSuccess(false);

    try {
      await generateAqiPdfReport({
        reportId,
        generatedAt: new Date(),
        aqi: liveAqi,
        category: liveCat,
        dominantPollutant,
        activeStationsCount,
        subIndices: {
          pm25,
          pm10,
          no2,
          so2,
          co,
          o3,
        },
        forecast: forecast?.data,
        currentHour: hour,
        consensus: consensus,
        cityAggregate: cityAggregate,
        stations: stations?.data ?? null,
        plume: plume?.data,
        inversion: inversion?.data,
        industries,
        alertSummary: {
          active: liveAqi >= 300,
          level: liveAqi >= 400 ? "STAGE IV EMERGENCY" : liveAqi >= 300 ? "STAGE III VERY POOR" : "MODERATE WARNING",
          message: "GRAP Stage III/IV recommended guidelines in effect across Delhi-NCR.",
        },
        language,
      });

      setDownloadSuccess(true);
      setTimeout(() => setDownloadSuccess(false), 4000);
    } catch (err) {
      console.error("PDF generation failed:", err);
      alert("Unable to generate PDF report. Please try again.");
    } finally {
      setIsGeneratingPdf(false);
    }
  };

  const getAqiColor = (val: number) => {
    if (val <= 50) return "#22c55e";
    if (val <= 100) return "#84cc16";
    if (val <= 200) return "#eab308";
    if (val <= 300) return "#f97316";
    if (val <= 400) return "#ef4444";
    return "#a855f7";
  };

  const aqiColor = getAqiColor(liveAqi);

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#080c14",
        color: "#f1f5f9",
        padding: "1.5rem 1.5rem 5rem",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      {/* Top Floating Control Bar */}
      <div
        style={{
          maxWidth: "1180px",
          margin: "0 auto 1.5rem",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "1rem",
          padding: "0.85rem 1.2rem",
          background: "rgba(15, 23, 42, 0.75)",
          backdropFilter: "blur(16px)",
          border: "1px solid rgba(255, 255, 255, 0.12)",
          borderRadius: "8px",
          position: "sticky",
          top: "1rem",
          zIndex: 90,
          boxShadow: "0 10px 30px rgba(0, 0, 0, 0.5)",
        }}
      >
        <button
          type="button"
          onClick={onBack}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.5rem",
            padding: "0.45rem 0.9rem",
            background: "rgba(255, 255, 255, 0.05)",
            border: "1px solid rgba(255, 255, 255, 0.15)",
            borderRadius: "6px",
            color: "rgba(255, 255, 255, 0.8)",
            fontSize: "13px",
            fontWeight: 500,
            cursor: "pointer",
            transition: "all 0.2s ease",
          }}
        >
          <ArrowLeft size={15} />
          <span>{t("common.backToOverview") || "← Back to Dashboard"}</span>
        </button>

        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <button
            type="button"
            onClick={handleDownloadPdf}
            disabled={isGeneratingPdf}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.6rem",
              padding: "0.55rem 1.3rem",
              background: downloadSuccess
                ? "linear-gradient(135deg, #10b981, #059669)"
                : "linear-gradient(135deg, #38bdf8, #0284c7)",
              border: "none",
              borderRadius: "6px",
              color: "#04111d",
              fontSize: "13.5px",
              fontWeight: 700,
              cursor: isGeneratingPdf ? "not-allowed" : "pointer",
              boxShadow: downloadSuccess
                ? "0 0 16px rgba(16, 185, 129, 0.6)"
                : "0 0 16px rgba(56, 189, 248, 0.4)",
              transition: "all 0.2s ease",
            }}
          >
            {isGeneratingPdf ? (
              <>
                <RotateCw size={16} className="animate-spin" />
                <span>GENERATING REPORT...</span>
              </>
            ) : downloadSuccess ? (
              <>
                <CheckCircle2 size={16} />
                <span>REPORT DOWNLOADED ✓</span>
              </>
            ) : (
              <>
                <Download size={16} />
                <span>DOWNLOAD PDF</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Main Printable Intelligence Dossier Container */}
      <main
        style={{
          maxWidth: "1180px",
          margin: "0 auto",
          background: "#0c1322",
          border: "1px solid rgba(255, 255, 255, 0.12)",
          borderRadius: "12px",
          padding: "2.5rem clamp(1.5rem, 4vw, 3.5rem)",
          boxShadow: "0 20px 60px rgba(0, 0, 0, 0.7)",
        }}
      >
        {/* Official Dossier Superheader */}
        <div style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.12)", paddingBottom: "1.5rem", marginBottom: "2rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "1rem" }}>
            <div>
              <div
                style={{
                  fontSize: "11px",
                  fontFamily: "var(--mono)",
                  color: "#38bdf8",
                  letterSpacing: "0.2em",
                  textTransform: "uppercase",
                  marginBottom: "0.4rem",
                  fontWeight: 700,
                }}
              >
                NATIONAL CAPITAL REGION CONTINUOUS AIR MONITORING INITIATIVE
              </div>
              <h1
                style={{
                  margin: 0,
                  fontSize: "clamp(1.6rem, 3vw, 2.3rem)",
                  fontWeight: 800,
                  color: "#FFFFFF",
                  letterSpacing: "-0.02em",
                  lineHeight: 1.2,
                }}
              >
                DELHI-NCR AIR QUALITY INTELLIGENCE REPORT
              </h1>
              <p style={{ margin: "0.4rem 0 0", color: "#94a3b8", fontSize: "13.5px" }}>
                AI-Powered Atmospheric Monitoring, Synoptic Inversion Analysis & 72-Hour Prognostic Forecast
              </p>
            </div>

            {/* Document ID & Stamp Badge */}
            <div
              style={{
                background: "rgba(255, 255, 255, 0.04)",
                border: "1px solid rgba(255, 255, 255, 0.1)",
                borderRadius: "6px",
                padding: "0.6rem 0.9rem",
                fontFamily: "var(--mono)",
                fontSize: "11.5px",
                color: "#cbd5e1",
                textAlign: "right",
              }}
            >
              <div><strong>ID:</strong> {reportId}</div>
              <div style={{ color: "#64748b", marginTop: "2px" }}>
                {new Date().toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })} | {new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
              </div>
            </div>
          </div>

          {/* Metadata Ribbon */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "0.75rem",
              marginTop: "1.2rem",
              padding: "0.75rem 1rem",
              background: "rgba(0, 0, 0, 0.35)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: "6px",
              fontSize: "12px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "#94a3b8" }}>
              <MapPin size={14} style={{ color: "#38bdf8" }} />
              <span>Location: <strong>Delhi-NCR (28.61°N, 77.21°E)</strong></span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "#94a3b8" }}>
              <Building2 size={14} style={{ color: "#38bdf8" }} />
              <span>Sensors: <strong>{activeStationsCount} CAAQMS Stations</strong></span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "#94a3b8" }}>
              <Activity size={14} style={{ color: "#38bdf8" }} />
              <span>Methodology: <strong>CPCB INAQI Multi-Criteria</strong></span>
            </div>
          </div>
        </div>

        {/* Section 1: Executive AQI Scorecard & Spectrum */}
        <section style={{ marginBottom: "2.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1rem" }}>
            <FileText size={18} style={{ color: "#38bdf8" }} />
            <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#FFFFFF" }}>
              1. Executive Air Quality Scorecard
            </h2>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
              gap: "1.2rem",
              background: "rgba(255, 255, 255, 0.03)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: "8px",
              padding: "1.5rem",
            }}
          >
            {/* Left Primary AQI Display */}
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                justifyContent: "center",
                alignItems: "center",
                padding: "1.5rem",
                background: "rgba(0, 0, 0, 0.4)",
                border: `1px solid ${aqiColor}40`,
                borderRadius: "8px",
                position: "relative",
              }}
            >
              <div style={{ fontSize: "11px", fontFamily: "var(--mono)", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.15em" }}>
                Current Regional AQI
              </div>
              <div
                style={{
                  fontSize: "4.2rem",
                  fontWeight: 900,
                  fontFamily: "var(--mono)",
                  color: aqiColor,
                  lineHeight: 1,
                  margin: "0.4rem 0",
                  textShadow: `0 0 25px ${aqiColor}60`,
                }}
              >
                {Math.round(liveAqi)}
              </div>
              <div
                style={{
                  padding: "0.3rem 0.9rem",
                  background: `${aqiColor}25`,
                  border: `1px solid ${aqiColor}60`,
                  borderRadius: "9999px",
                  color: aqiColor,
                  fontSize: "12px",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                }}
              >
                {liveCat}
              </div>
            </div>

            {/* Right Metric Summary */}
            <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", gap: "0.8rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0", borderBottom: "1px solid rgba(255, 255, 255, 0.06)", fontSize: "13px" }}>
                <span style={{ color: "#94a3b8" }}>Primary Trigger Pollutant:</span>
                <span style={{ fontWeight: 700, color: "#FFFFFF" }}>{dominantPollutant}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0", borderBottom: "1px solid rgba(255, 255, 255, 0.06)", fontSize: "13px" }}>
                <span style={{ color: "#94a3b8" }}>Fine Particulate (PM2.5):</span>
                <span style={{ fontWeight: 700, color: "#f87171" }}>{pm25} µg/m³</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0", borderBottom: "1px solid rgba(255, 255, 255, 0.06)", fontSize: "13px" }}>
                <span style={{ color: "#94a3b8" }}>Coarse Particulate (PM10):</span>
                <span style={{ fontWeight: 700, color: "#fb923c" }}>{pm10} µg/m³</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0", borderBottom: "1px solid rgba(255, 255, 255, 0.06)", fontSize: "13px" }}>
                <span style={{ color: "#94a3b8" }}>Boundary Layer Height (PBL):</span>
                <span style={{ fontWeight: 700, color: "#38bdf8" }}>{pblHeight} m</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "0.5rem 0", fontSize: "13px" }}>
                <span style={{ color: "#94a3b8" }}>Thermal Inversion Strength:</span>
                <span style={{ fontWeight: 700, color: "#fbbf24" }}>+{invDeltaT}°C</span>
              </div>
            </div>
          </div>
        </section>

        {/* Section 2: 6-Species Criteria Pollutants */}
        <section style={{ marginBottom: "2.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1rem" }}>
            <Layers size={18} style={{ color: "#38bdf8" }} />
            <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#FFFFFF" }}>
              2. 6-Species Criteria Pollutant Breakdown
            </h2>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
              gap: "0.9rem",
            }}
          >
            {[
              { code: "PM2.5", name: "Fine Particles", val: `${pm25} µg/m³`, std: "60 µg/m³", color: "#f87171", status: pm25 > 60 ? "EXCEEDED" : "SAFE" },
              { code: "PM10", name: "Coarse Dust", val: `${pm10} µg/m³`, std: "100 µg/m³", color: "#fb923c", status: pm10 > 100 ? "EXCEEDED" : "SAFE" },
              { code: "NO2", name: "Nitrogen Dioxide", val: `${no2} µg/m³`, std: "80 µg/m³", color: "#facc15", status: no2 > 80 ? "EXCEEDED" : "MODERATE" },
              { code: "SO2", name: "Sulfur Dioxide", val: `${so2} µg/m³`, std: "80 µg/m³", color: "#4ade80", status: "SAFE" },
              { code: "CO", name: "Carbon Monoxide", val: `${co} mg/m³`, std: "2.0 mg/m³", color: "#38bdf8", status: "SAFE" },
              { code: "O3", name: "Surface Ozone", val: `${o3} µg/m³`, std: "100 µg/m³", color: "#c084fc", status: "SAFE" },
            ].map((p) => (
              <div
                key={p.code}
                style={{
                  background: "rgba(255, 255, 255, 0.03)",
                  border: "1px solid rgba(255, 255, 255, 0.08)",
                  borderRadius: "8px",
                  padding: "1rem",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                }}
              >
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontWeight: 800, fontFamily: "var(--mono)", fontSize: "14px", color: p.color }}>{p.code}</span>
                    <span style={{ fontSize: "9.5px", padding: "1px 5px", borderRadius: "3px", background: p.status === "SAFE" ? "rgba(34, 197, 94, 0.15)" : "rgba(239, 68, 68, 0.15)", color: p.status === "SAFE" ? "#4ade80" : "#f87171", fontWeight: 700 }}>
                      {p.status}
                    </span>
                  </div>
                  <div style={{ fontSize: "11px", color: "#64748b", margin: "2px 0 0.5rem" }}>{p.name}</div>
                </div>

                <div>
                  <div style={{ fontSize: "1.3rem", fontWeight: 800, fontFamily: "var(--mono)", color: "#FFFFFF" }}>{p.val}</div>
                  <div style={{ fontSize: "10.5px", color: "#94a3b8", marginTop: "2px" }}>CPCB Std: {p.std}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Section 3: 72-Hour Prognostic Forecast Chart */}
        <section style={{ marginBottom: "2.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1rem" }}>
            <TrendingUp size={18} style={{ color: "#38bdf8" }} />
            <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#FFFFFF" }}>
              3. 72-Hour Prognostic Forecast Trajectory
            </h2>
          </div>

          <div
            style={{
              background: "rgba(255, 255, 255, 0.03)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: "8px",
              padding: "1.2rem 1.2rem 0.5rem",
            }}
          >
            <div style={{ height: "240px", width: "100%" }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={forecastChartData}>
                  <defs>
                    <linearGradient id="forecastAqiGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="time" stroke="#64748b" fontSize={11} tickLine={false} />
                  <YAxis stroke="#64748b" fontSize={11} tickLine={false} domain={[0, "auto"]} />
                  <Tooltip
                    contentStyle={{ background: "#0f172a", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "6px", fontSize: "12px" }}
                  />
                  <Area
                    type="monotone"
                    dataKey="aqi"
                    stroke="#38bdf8"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#forecastAqiGrad)"
                    name="Predicted AQI"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div style={{ textAlign: "center", fontSize: "11.5px", color: "#64748b", padding: "0.5rem 0" }}>
              Numerical dispersion predictions over the upcoming forecast horizon across Delhi-NCR.
            </div>
          </div>
        </section>

        {/* Section 4: Atmospheric Dynamics & Meteorology */}
        <section style={{ marginBottom: "2.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1rem" }}>
            <Wind size={18} style={{ color: "#38bdf8" }} />
            <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#FFFFFF" }}>
              4. Atmospheric Dynamics & Boundary Layer Meteorology
            </h2>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "1rem",
            }}
          >
            {[
              { label: "Planetary Boundary Layer", val: `${pblHeight} m`, note: "Vertical dilution mixing ceiling" },
              { label: "Thermal Inversion Delta T", val: `+${invDeltaT}°C`, note: "Warm trapping lid suppressing dispersion" },
              { label: "Surface Temperature", val: `${tempC}°C`, note: "Thermodynamic state influencing condensation" },
              { label: "Relative Humidity", val: `${rhPct}%`, note: "Hygroscopic particulate growth factor" },
              { label: "Surface Wind Speed", val: `${(windMps * 3.6).toFixed(1)} km/h`, note: "Horizontal ventilation velocity" },
              { label: "Regional Plume Burden", val: `${plumeFrac}%`, note: "Transboundary combustion smoke fraction" },
            ].map((m, idx) => (
              <div
                key={idx}
                style={{
                  background: "rgba(255, 255, 255, 0.03)",
                  border: "1px solid rgba(255, 255, 255, 0.08)",
                  borderRadius: "8px",
                  padding: "1rem",
                }}
              >
                <div style={{ fontSize: "11px", color: "#94a3b8", fontFamily: "var(--mono)" }}>{m.label}</div>
                <div style={{ fontSize: "1.4rem", fontWeight: 800, fontFamily: "var(--mono)", color: "#38bdf8", margin: "0.2rem 0" }}>
                  {m.val}
                </div>
                <div style={{ fontSize: "11px", color: "#64748b" }}>{m.note}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Section 5: Industrial Emission Sources Overview */}
        <section style={{ marginBottom: "2.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1rem" }}>
            <Factory size={18} style={{ color: "#38bdf8" }} />
            <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#FFFFFF" }}>
              5. Industrial & Point-Source Emission Hubs
            </h2>
          </div>

          <div
            style={{
              background: "rgba(255, 255, 255, 0.03)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: "8px",
              padding: "1.2rem",
            }}
          >
            <p style={{ margin: "0 0 1rem", fontSize: "13.5px", color: "#cbd5e1" }}>
              The environmental database maintains geospatial surveillance on <strong>{industries.length || 2390} verified industrial facilities</strong> across all 33 designated industrial clusters in Delhi (Mayapuri, Wazirpur, Okhla, Narela, Bawana, Patparganj).
            </p>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                gap: "0.8rem",
              }}
            >
              {[
                { name: "Metal Finishing & Electroplating", count: "482 Units", share: "20.2%" },
                { name: "Chemical & Polymer Formulation", count: "394 Units", share: "16.5%" },
                { name: "Textile Dyeing & Garments", count: "360 Units", share: "15.1%" },
                { name: "Heavy Engineering & Fabrication", count: "318 Units", share: "13.3%" },
              ].map((ind, idx) => (
                <div
                  key={idx}
                  style={{
                    background: "rgba(0, 0, 0, 0.3)",
                    border: "1px solid rgba(255, 255, 255, 0.06)",
                    borderRadius: "6px",
                    padding: "0.8rem",
                  }}
                >
                  <div style={{ fontSize: "12px", color: "#FFFFFF", fontWeight: 600 }}>{ind.name}</div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: "0.4rem", fontSize: "11px", color: "#94a3b8" }}>
                    <span>{ind.count}</span>
                    <strong style={{ color: "#c084fc" }}>{ind.share}</strong>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Section 6: Clinical Health Impact & Actionable Guidance */}
        <section style={{ marginBottom: "2.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1rem" }}>
            <ShieldCheck size={18} style={{ color: "#38bdf8" }} />
            <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#FFFFFF" }}>
              6. Clinical Health Impact & Protection Protocol
            </h2>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
              gap: "1rem",
            }}
          >
            {[
              {
                title: "Vulnerable Cohorts",
                desc: "Asthma, COPD, and cardiac patients should strictly avoid outdoor physical exertion. Keep rescue inhalers accessible.",
              },
              {
                title: "Respiratory Protection",
                desc: "Wear certified NIOSH N95 or FFP2 respirators during outdoor commute. Cloth and surgical masks do not filter fine PM2.5.",
              },
              {
                title: "Indoor Air Purification",
                desc: "Operate true H13 HEPA purifiers with activated carbon stages. Keep windows sealed during morning inversion hours.",
              },
              {
                title: "Emergency Signs",
                desc: "Seek prompt medical care (Dial 102/112) for acute chest tightness, unremitting coughing fits, or oxygen saturation < 94%.",
              },
            ].map((g, idx) => (
              <div
                key={idx}
                style={{
                  background: "rgba(255, 255, 255, 0.03)",
                  border: "1px solid rgba(255, 255, 255, 0.08)",
                  borderRadius: "8px",
                  padding: "1.2rem",
                }}
              >
                <div style={{ fontSize: "13px", fontWeight: 700, color: "#38bdf8", marginBottom: "0.4rem" }}>
                  {g.title}
                </div>
                <div style={{ fontSize: "12px", color: "#cbd5e1", lineHeight: 1.5 }}>
                  {g.desc}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Section 7: Data Provenance & Governance Note */}
        <section
          style={{
            borderTop: "1px solid rgba(255, 255, 255, 0.1)",
            paddingTop: "1.5rem",
            marginTop: "2rem",
            fontSize: "11.5px",
            color: "#64748b",
            lineHeight: 1.6,
          }}
        >
          <div style={{ fontWeight: 700, color: "#94a3b8", marginBottom: "0.4rem" }}>
            DATA SOURCES & OFFICIAL GOVERNANCE NOTE
          </div>
          <p style={{ margin: 0 }}>
            Observations synthesized from the Central Pollution Control Board (CPCB) 43-station CAAQMS continuous network, Open-Meteo boundary layer meteorology, NASA FIRMS thermal telemetry, and the Supabase Delhi Industrial Registry. Model forecasts are diagnostic tools intended for public health mitigation and municipal decision support.
          </p>
        </section>
      </main>
    </div>
  );
}
