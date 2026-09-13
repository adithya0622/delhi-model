import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Car,
  Clock,
  Factory,
  Flame,
  Layers,
  RotateCcw,
  Sliders,
  Truck,
  Wind,
  Compass,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getSourceApportionment, getSourceTimeSeries } from "@/lib/api";
import type {
  ApportionmentHour,
  SourceApportionmentResponse,
} from "@/lib/types";
import { useTranslation } from "@/i18n";

interface Props {
  currentPm25: number;
  currentNo2?: number;
}

const SECTOR_COLORS = {
  transport: "#38bdf8", // Electric Cyan
  dust: "#fbbf24",      // Radiant Amber
  biomass: "#f97316",   // Solar Flare Orange
  industry: "#c084fc",  // Luminous Purple
};

const VEHICLE_COLORS = {
  trucks: "#f43f5e",    // Neon Rose / Red
  twoWheelers: "#38bdf8", // Electric Cyan
  cars: "#34d399",      // Emerald Mint
};

export function SourceApportionment({ currentPm25, currentNo2 = 38.5 }: Props) {
  const { t } = useTranslation();
  const [isManual, setIsManual] = useState(false);
  const [manualNo2, setManualNo2] = useState<number>(currentNo2);
  const [manualHour, setManualHour] = useState<number>(new Date().getHours());
  const [data, setData] = useState<SourceApportionmentResponse | null>(null);
  const [timeSeries, setTimeSeries] = useState<ApportionmentHour[]>([]);
  const [timeSeriesMode, setTimeSeriesMode] = useState<"fleet" | "macro">("fleet");
  const [highlightedKey, setHighlightedKey] = useState<string | null>(null);

  const activeNo2 = isManual ? manualNo2 : currentNo2;
  const activeHour = isManual ? manualHour : new Date().getHours();

  useEffect(() => {
    let cancelled = false;
    async function fetchApportionment() {
      try {
        const res = await getSourceApportionment(currentPm25, activeNo2, activeHour);
        if (!cancelled) {
          setData(res);
        }
      } catch {
        const ratio = Math.min(1.0, Math.max(0.0, activeNo2 / 60.0));
        const transPct = Math.round(25.0 * ratio * 100) / 100;
        const missing = 25.0 - transPct;
        const dustPct = Math.round((30.0 + missing / 3.0) * 100) / 100;
        const bioPct = Math.round((25.0 + missing / 3.0) * 100) / 100;
        const indPct = Math.round((100.0 - transPct - dustPct - bioPct) * 100) / 100;

        let truckShare = 30;
        let twoShare = 50;
        let carShare = 20;

        if (activeHour >= 22 || activeHour < 6) {
          truckShare = 61;
          twoShare = 25;
          carShare = 14;
        } else if ((activeHour >= 8 && activeHour < 11) || (activeHour >= 17 && activeHour < 20)) {
          truckShare = 10;
          twoShare = 60;
          carShare = 30;
        }

        const transMcg = Math.round(currentPm25 * (transPct / 100) * 100) / 100;
        if (!cancelled) {
          setData({
            total_pm25: currentPm25,
            transport_pct: transPct,
            dust_pct: dustPct,
            biomass_pct: bioPct,
            industry_pct: indPct,
            transport_mcg: transMcg,
            dust_mcg: Math.round(currentPm25 * (dustPct / 100) * 100) / 100,
            biomass_mcg: Math.round(currentPm25 * (bioPct / 100) * 100) / 100,
            industry_mcg: Math.round(currentPm25 * (indPct / 100) * 100) / 100,
            vehicle_breakdown: {
              heavy_trucks_pct: truckShare,
              two_three_wheelers_pct: twoShare,
              cars_pct: carShare,
              heavy_trucks_mcg: Math.round(transMcg * (truckShare / 100) * 100) / 100,
              two_three_wheelers_mcg: Math.round(transMcg * (twoShare / 100) * 100) / 100,
              cars_mcg: Math.round(transMcg * (carShare / 100) * 100) / 100,
            },
            proxy_status:
              ratio >= 0.95
                ? "Normal Traffic Flow (100% Baseline)"
                : ratio < 0.5
                ? `Significant Traffic Suppression (NO₂ Index: ${Math.round(ratio * 100)}%)`
                : `Moderate Traffic Load (NO₂ Index: ${Math.round(ratio * 100)}%)`,
          });
        }
      }
    }

    fetchApportionment();
    return () => {
      cancelled = true;
    };
  }, [currentPm25, activeNo2, activeHour]);

  // Fetch 72-hour predictive source apportionment time-series
  useEffect(() => {
    let cancelled = false;
    async function fetchSeries() {
      try {
        const res = await getSourceTimeSeries();
        if (!cancelled && res?.forecast) {
          setTimeSeries(res.forecast);
        }
      } catch {
        const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
        const now = new Date();
        const fallbackList: ApportionmentHour[] = [];
        for (let i = 0; i < 72; i++) {
          const d = new Date(now.getTime() + i * 3600 * 1000);
          const hr = d.getHours();
          const dayName = days[d.getDay()];
          const timeStr = `${dayName} ${hr.toString().padStart(2, "0")}:00`;

          let pm = currentPm25;
          if (hr < 6 || hr >= 22) {
            pm = 130 + (6 - Math.abs(hr - 2)) * 7;
          } else if ((hr >= 8 && hr <= 11) || (hr >= 17 && hr <= 20)) {
            pm = 85 + (10 - Math.abs(hr - 9)) * 5;
          } else {
            pm = 50 + (hr - 12) * 2;
          }
          pm = Math.max(25, Math.round(pm * 10) / 10);

          const dust = Math.round(pm * 0.3 * 100) / 100;
          const bio = Math.round(pm * 0.25 * 100) / 100;
          const ind = Math.round(pm * 0.2 * 100) / 100;
          const transTotal = pm * 0.25;

          let trkShare = 0.3;
          let twoShare = 0.5;
          let carShare = 0.2;
          if (hr >= 22 || hr < 6) {
            trkShare = 0.61;
            twoShare = 0.25;
            carShare = 0.14;
          } else if ((hr >= 8 && hr <= 10) || (hr >= 17 && hr <= 19)) {
            trkShare = 0.1;
            twoShare = 0.6;
            carShare = 0.3;
          }

          fallbackList.push({
            timestamp: timeStr,
            total_pm25: pm,
            dust_mcg: dust,
            biomass_mcg: bio,
            industry_mcg: ind,
            trucks_mcg: Math.round(transTotal * trkShare * 100) / 100,
            two_wheelers_mcg: Math.round(transTotal * twoShare * 100) / 100,
            cars_mcg: Math.round(transTotal * carShare * 100) / 100,
          });
        }
        if (!cancelled) {
          setTimeSeries(fallbackList);
        }
      }
    }

    fetchSeries();
    return () => {
      cancelled = true;
    };
  }, [currentPm25]);

  const isNightWindow = activeHour >= 22 || activeHour < 6;
  const isRushHour = (activeHour >= 8 && activeHour < 11) || (activeHour >= 17 && activeHour < 20);

  // Time-Series chart dataset formatting: cleanly anchored to live Nowcast metrics at t=0
  const formattedTimeSeries = useMemo(() => {
    if (!timeSeries.length) return [];
    const offsetPm = currentPm25 - (timeSeries[0]?.total_pm25 ?? currentPm25);

    return timeSeries.map((pt, idx) => {
      if (idx === 0 && data) {
        return {
          ...pt,
          total_pm25: data.total_pm25,
          dust_mcg: data.dust_mcg,
          biomass_mcg: data.biomass_mcg,
          industry_mcg: data.industry_mcg,
          trucks_mcg: data.vehicle_breakdown.heavy_trucks_mcg,
          two_wheelers_mcg: data.vehicle_breakdown.two_three_wheelers_mcg,
          cars_mcg: data.vehicle_breakdown.cars_mcg,
          transport_mcg: data.transport_mcg,
        };
      }

      const decay = Math.exp(-idx / 24);
      const nudgedPm = Math.max(10, Math.round((pt.total_pm25 + offsetPm * decay) * 10) / 10);
      const ratio = nudgedPm / (pt.total_pm25 || 1);

      const d_mcg = Math.round(pt.dust_mcg * ratio * 100) / 100;
      const b_mcg = Math.round(pt.biomass_mcg * ratio * 100) / 100;
      const i_mcg = Math.round(pt.industry_mcg * ratio * 100) / 100;
      const tr_mcg = Math.round(pt.trucks_mcg * ratio * 100) / 100;
      const tw_mcg = Math.round(pt.two_wheelers_mcg * ratio * 100) / 100;
      const c_mcg = Math.round(pt.cars_mcg * ratio * 100) / 100;
      const transportTotal = Math.round((tr_mcg + tw_mcg + c_mcg) * 100) / 100;

      return {
        ...pt,
        total_pm25: nudgedPm,
        dust_mcg: d_mcg,
        biomass_mcg: b_mcg,
        industry_mcg: i_mcg,
        trucks_mcg: tr_mcg,
        two_wheelers_mcg: tw_mcg,
        cars_mcg: c_mcg,
        transport_mcg: transportTotal,
      };
    });
  }, [timeSeries, data, currentPm25]);

  return (
    <section
      id="source-apportionment"
      className="section"
      style={{
        background: "var(--slab)",
        border: "1px solid var(--hairline)",
        borderRadius: "16px",
        padding: "clamp(1.5rem, 3vw, 2.5rem)",
        marginBottom: "2.5rem",
        boxShadow: "0 20px 50px rgba(0, 0, 0, 0.6)",
      }}
      aria-label="Dynamic Source Apportionment"
    >
      {/* ── STAGE 1: SECTION HEADER & CONSERVATION OF MASS SUMMARY ── */}
      <div style={{ marginBottom: "1.8rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "1rem" }}>
          <div>
            <p className="eyebrow" style={{ color: "var(--cyan)", display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.3rem" }}>
              <Compass size={14} /> {t("sourceApportionment.tracerBadge")}
            </p>
            <h2 style={{ fontSize: "clamp(1.5rem, 2.8vw, 2.1rem)", fontWeight: 600, color: "var(--bone)", margin: 0, letterSpacing: "-0.02em" }}>
              {t("sourceApportionment.title")}
            </h2>
            <p style={{ color: "var(--mist)", fontSize: "0.95rem", marginTop: "0.4rem", maxWidth: "820px", lineHeight: 1.55 }}>
              {t("sourceApportionment.subtitle")}
            </p>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
            <button
              type="button"
              onClick={() => setIsManual(!isManual)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.4rem",
                padding: "0.5rem 0.95rem",
                borderRadius: "6px",
                fontSize: "12px",
                fontFamily: "var(--mono)",
                fontWeight: 600,
                cursor: "pointer",
                background: isManual ? "rgba(245, 158, 11, 0.2)" : "rgba(255, 255, 255, 0.05)",
                border: `1px solid ${isManual ? "var(--amber)" : "var(--hairline-2)"}`,
                color: isManual ? "var(--amber)" : "var(--bone)",
                transition: "all 0.2s ease",
              }}
            >
              <Sliders size={14} />
              {isManual ? t("sourceApportionment.simulationMode") : t("sourceApportionment.liveSync")}
            </button>
          </div>
        </div>

        {/* Total Mass Allocation Progress Bar */}
        <div style={{ marginTop: "1.4rem", background: "rgba(10, 15, 22, 0.8)", border: "1px solid var(--hairline)", borderRadius: "10px", padding: "1rem 1.25rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.65rem" }}>
            <span style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--bone)", fontWeight: 600 }}>
              {t("sourceApportionment.totalAmbient")}: <span style={{ color: "var(--cyan)", fontSize: "1.05rem" }}>{currentPm25.toFixed(1)} µg/m³</span> (100% {t("cardstack.activeTelemetry")})
            </span>
            <span style={{ fontSize: "11px", fontFamily: "var(--mono)", color: "var(--mist-faint)" }}>
              NO₂ Tracer: <strong style={{ color: "var(--cyan)" }}>{activeNo2.toFixed(1)} µg/m³</strong> • Status: <strong style={{ color: "var(--emerald)" }}>{data?.proxy_status ?? "Live Baseline"}</strong>
            </span>
          </div>

          <div style={{ display: "flex", height: "14px", borderRadius: "7px", overflow: "hidden", background: "rgba(255, 255, 255, 0.05)" }}>
            <div style={{ width: `${data?.transport_pct ?? 25}%`, background: SECTOR_COLORS.transport, transition: "width 0.4s ease" }} title={`${t("sourceApportionment.vehicular")}: ${data?.transport_pct?.toFixed(1)}%`} />
            <div style={{ width: `${data?.dust_pct ?? 30}%`, background: SECTOR_COLORS.dust, transition: "width 0.4s ease" }} title={`${t("sourceApportionment.roadDust")}: ${data?.dust_pct?.toFixed(1)}%`} />
            <div style={{ width: `${data?.biomass_pct ?? 25}%`, background: SECTOR_COLORS.biomass, transition: "width 0.4s ease" }} title={`${t("sourceApportionment.biomassBurning")}: ${data?.biomass_pct?.toFixed(1)}%`} />
            <div style={{ width: `${data?.industry_pct ?? 20}%`, background: SECTOR_COLORS.industry, transition: "width 0.4s ease" }} title={`${t("sourceApportionment.industrial")}: ${data?.industry_pct?.toFixed(1)}%`} />
          </div>
        </div>
      </div>

      {/* ── STAGE 2: 4 MAJOR POLLUTION SECTOR CARDS (REALISM SHINY BORDERS) ── */}
      <div style={{ marginBottom: "2.2rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.85rem" }}>
          <span style={{ fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--mist-dim)" }}>
            STEP 1 · 4-Sector Macro Pollution Apportionment
          </span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: "1rem" }}>
          {/* 1. Vehicular Transport */}
          <article className="realism-box">
            <div className="realism-topglow" />
            <div className="realism-blob" style={{ background: "radial-gradient(circle, #38bdf888 0%, transparent 70%)" }} />
            <div className="realism-inner" style={{ padding: "1.1rem" }}>
              <div className="realism-inner-glow" />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", color: SECTOR_COLORS.transport, fontWeight: 700 }}>
                  {t("sourceApportionment.vehicular")}
                </span>
                <Car size={18} style={{ color: SECTOR_COLORS.transport }} />
              </div>
              <div style={{ margin: "0.65rem 0" }}>
                <div style={{ fontSize: "2rem", fontWeight: 800, fontFamily: "var(--mono)", color: SECTOR_COLORS.transport, lineHeight: 1 }}>
                  {data?.transport_pct?.toFixed(1) ?? "25.0"}%
                </div>
                <div style={{ fontSize: "13px", fontFamily: "var(--mono)", color: "var(--bone)", marginTop: "0.35rem" }}>
                  <strong>{data?.transport_mcg?.toFixed(1) ?? "—"}</strong> µg/m³
                </div>
              </div>
              <p style={{ fontSize: "11px", color: "var(--mist)", margin: 0, lineHeight: 1.35 }}>
                Tailpipe combustion from diesel trucks, two-wheelers &amp; cars. Dynamically inferred via NO₂ proxy.
              </p>
            </div>
          </article>

          {/* 2. Road & Soil Dust */}
          <article className="realism-box">
            <div className="realism-topglow" />
            <div className="realism-blob" style={{ background: "radial-gradient(circle, #fbbf2488 0%, transparent 70%)" }} />
            <div className="realism-inner" style={{ padding: "1.1rem" }}>
              <div className="realism-inner-glow" />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", color: SECTOR_COLORS.dust, fontWeight: 700 }}>
                  {t("sourceApportionment.roadDust")}
                </span>
                <Wind size={18} style={{ color: SECTOR_COLORS.dust }} />
              </div>
              <div style={{ margin: "0.65rem 0" }}>
                <div style={{ fontSize: "2rem", fontWeight: 800, fontFamily: "var(--mono)", color: SECTOR_COLORS.dust, lineHeight: 1 }}>
                  {data?.dust_pct?.toFixed(1) ?? "30.0"}%
                </div>
                <div style={{ fontSize: "13px", fontFamily: "var(--mono)", color: "var(--bone)", marginTop: "0.35rem" }}>
                  <strong>{data?.dust_mcg?.toFixed(1) ?? "—"}</strong> µg/m³
                </div>
              </div>
              <p style={{ fontSize: "11px", color: "var(--mist)", margin: 0, lineHeight: 1.35 }}>
                Resuspended road silt, construction activities, soil erosion, and mechanical abrasion.
              </p>
            </div>
          </article>

          {/* 3. Biomass / Stubble */}
          <article className="realism-box">
            <div className="realism-topglow" />
            <div className="realism-blob" style={{ background: "radial-gradient(circle, #f9731688 0%, transparent 70%)" }} />
            <div className="realism-inner" style={{ padding: "1.1rem" }}>
              <div className="realism-inner-glow" />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", color: SECTOR_COLORS.biomass, fontWeight: 700 }}>
                  {t("sourceApportionment.biomassBurning")}
                </span>
                <Flame size={18} style={{ color: SECTOR_COLORS.biomass }} />
              </div>
              <div style={{ margin: "0.65rem 0" }}>
                <div style={{ fontSize: "2rem", fontWeight: 800, fontFamily: "var(--mono)", color: SECTOR_COLORS.biomass, lineHeight: 1 }}>
                  {data?.biomass_pct?.toFixed(1) ?? "25.0"}%
                </div>
                <div style={{ fontSize: "13px", fontFamily: "var(--mono)", color: "var(--bone)", marginTop: "0.35rem" }}>
                  <strong>{data?.biomass_mcg?.toFixed(1) ?? "—"}</strong> µg/m³
                </div>
              </div>
              <p style={{ fontSize: "11px", color: "var(--mist)", margin: 0, lineHeight: 1.35 }}>
                Agricultural residue burning from Punjab/Haryana &amp; municipal/domestic solid biomass fuels.
              </p>
            </div>
          </article>

          {/* 4. Industry & Power */}
          <article className="realism-box">
            <div className="realism-topglow" />
            <div className="realism-blob" style={{ background: "radial-gradient(circle, #c084fc88 0%, transparent 70%)" }} />
            <div className="realism-inner" style={{ padding: "1.1rem" }}>
              <div className="realism-inner-glow" />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", color: SECTOR_COLORS.industry, fontWeight: 700 }}>
                  {t("sourceApportionment.industrial")}
                </span>
                <Factory size={18} style={{ color: SECTOR_COLORS.industry }} />
              </div>
              <div style={{ margin: "0.65rem 0" }}>
                <div style={{ fontSize: "2rem", fontWeight: 800, fontFamily: "var(--mono)", color: SECTOR_COLORS.industry, lineHeight: 1 }}>
                  {data?.industry_pct?.toFixed(1) ?? "20.0"}%
                </div>
                <div style={{ fontSize: "13px", fontFamily: "var(--mono)", color: "var(--bone)", marginTop: "0.35rem" }}>
                  <strong>{data?.industry_mcg?.toFixed(1) ?? "—"}</strong> µg/m³
                </div>
              </div>
              <p style={{ fontSize: "11px", color: "var(--mist)", margin: 0, lineHeight: 1.35 }}>
                Surrounding industrial clusters, brick kilns, thermal power plants, and DG generator sets.
              </p>
            </div>
          </article>
        </div>
      </div>

      {/* ── STAGE 3: IN-DEPTH TRANSPORT FLEET BREAKDOWN (CORE VEHICLE MODES) ── */}
      <div style={{ background: "rgba(10, 15, 24, 0.85)", border: "1px solid var(--hairline)", borderRadius: "12px", padding: "1.4rem", marginBottom: "2.2rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.8rem", marginBottom: "1.2rem" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <span style={{ fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--cyan)", fontWeight: 700 }}>
                STEP 2 · Deep-Dive: How Transport &amp; Vehicles Pollute Delhi
              </span>
            </div>
            <h3 style={{ fontSize: "1.25rem", fontWeight: 600, color: "var(--bone)", margin: "0.2rem 0 0" }}>
              {t("sourceApportionment.fleetBreakdown")}
            </h3>
          </div>

          {/* Active Fleet Regime Pill */}
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", background: "rgba(255, 255, 255, 0.04)", padding: "0.4rem 0.8rem", borderRadius: "6px", border: "1px solid var(--hairline)" }}>
            <Clock size={14} style={{ color: isNightWindow ? "var(--red)" : isRushHour ? "var(--amber)" : "var(--cyan)" }} />
            <span style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--bone)" }}>
              Hour {activeHour.toString().padStart(2, "0")}:00 IST:{" "}
              {isNightWindow ? (
                <strong style={{ color: "var(--red)" }}>🌙 Night Truck Entry (Surges to 61%)</strong>
              ) : isRushHour ? (
                <strong style={{ color: "var(--amber)" }}>⚡ Peak Commuter Rush (2-Wheelers 60%)</strong>
              ) : (
                <strong style={{ color: "var(--cyan)" }}>☀️ Normal Daytime Fleet (Balanced)</strong>
              )}
            </span>
          </div>
        </div>

        {/* 3 Detailed Transport Mode Cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(270px, 1fr))", gap: "1.1rem" }}>
          {/* 1. Heavy Commercial Trucks */}
          <div
            style={{
              background: isNightWindow ? "rgba(244, 63, 94, 0.08)" : "rgba(255, 255, 255, 0.03)",
              border: `1px solid ${isNightWindow ? "rgba(244, 63, 94, 0.45)" : "var(--hairline)"}`,
              borderRadius: "10px",
              padding: "1.2rem",
              position: "relative",
            }}
          >
            {isNightWindow && (
              <span style={{ position: "absolute", top: "10px", right: "10px", fontSize: "9px", fontFamily: "var(--mono)", fontWeight: 700, background: VEHICLE_COLORS.trucks, color: "#fff", padding: "2px 6px", borderRadius: "3px", textTransform: "uppercase" }}>
                Active Night Window
              </span>
            )}
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: VEHICLE_COLORS.trucks, marginBottom: "0.5rem" }}>
              <Truck size={18} />
              <span style={{ fontSize: "13px", fontWeight: 700 }}>{t("sourceApportionment.trucks")}</span>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem", margin: "0.3rem 0" }}>
              <span style={{ fontSize: "2rem", fontWeight: 800, fontFamily: "var(--mono)", color: VEHICLE_COLORS.trucks }}>
                {data?.vehicle_breakdown?.heavy_trucks_pct ?? 30}%
              </span>
              <span style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--mist)" }}>
                of vehicular emissions
              </span>
            </div>
            <div style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--bone)", marginBottom: "0.6rem" }}>
              Mass Contribution: <strong style={{ color: VEHICLE_COLORS.trucks }}>{data?.vehicle_breakdown?.heavy_trucks_mcg?.toFixed(1) ?? "—"} µg/m³</strong>
            </div>
            <div style={{ background: "rgba(255, 255, 255, 0.08)", height: "6px", borderRadius: "3px", overflow: "hidden", marginBottom: "0.8rem" }}>
              <div style={{ width: `${data?.vehicle_breakdown?.heavy_trucks_pct ?? 30}%`, height: "100%", background: VEHICLE_COLORS.trucks }} />
            </div>
            <p style={{ fontSize: "11.5px", color: "var(--mist)", margin: 0, lineHeight: 1.45 }}>
              Heavy commercial diesel trucks enter Delhi highways after 10 PM. Because diesel engines produce high elemental carbon (soot) and NOx, a single truck emits up to <strong>15× more PM2.5</strong> than a passenger car.
            </p>
          </div>

          {/* 2. 2-Wheelers & 3-Wheelers */}
          <div
            style={{
              background: isRushHour ? "rgba(56, 189, 248, 0.08)" : "rgba(255, 255, 255, 0.03)",
              border: `1px solid ${isRushHour ? "rgba(56, 189, 248, 0.45)" : "var(--hairline)"}`,
              borderRadius: "10px",
              padding: "1.2rem",
              position: "relative",
            }}
          >
            {isRushHour && (
              <span style={{ position: "absolute", top: "10px", right: "10px", fontSize: "9px", fontFamily: "var(--mono)", fontWeight: 700, background: VEHICLE_COLORS.twoWheelers, color: "#000", padding: "2px 6px", borderRadius: "3px", textTransform: "uppercase" }}>
                Peak Commuter Spike
              </span>
            )}
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: VEHICLE_COLORS.twoWheelers, marginBottom: "0.5rem" }}>
              <Activity size={18} />
              <span style={{ fontSize: "13px", fontWeight: 700 }}>{t("sourceApportionment.twoWheelers")}</span>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem", margin: "0.3rem 0" }}>
              <span style={{ fontSize: "2rem", fontWeight: 800, fontFamily: "var(--mono)", color: VEHICLE_COLORS.twoWheelers }}>
                {data?.vehicle_breakdown?.two_three_wheelers_pct ?? 50}%
              </span>
              <span style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--mist)" }}>
                of vehicular emissions
              </span>
            </div>
            <div style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--bone)", marginBottom: "0.6rem" }}>
              Mass Contribution: <strong style={{ color: VEHICLE_COLORS.twoWheelers }}>{data?.vehicle_breakdown?.two_three_wheelers_mcg?.toFixed(1) ?? "—"} µg/m³</strong>
            </div>
            <div style={{ background: "rgba(255, 255, 255, 0.08)", height: "6px", borderRadius: "3px", overflow: "hidden", marginBottom: "0.8rem" }}>
              <div style={{ width: `${data?.vehicle_breakdown?.two_three_wheelers_pct ?? 50}%`, height: "100%", background: VEHICLE_COLORS.twoWheelers }} />
            </div>
            <p style={{ fontSize: "11.5px", color: "var(--mist)", margin: 0, lineHeight: 1.45 }}>
              Over <strong>7 million registered two-wheelers</strong> drive Delhi daily. High stop-and-go acceleration and incomplete 2-stroke/4-stroke fuel combustion make them the single largest emitter during morning &amp; evening commute peaks.
            </p>
          </div>

          {/* 3. Passenger Cars & Taxis */}
          <div
            style={{
              background: "rgba(255, 255, 255, 0.03)",
              border: "1px solid var(--hairline)",
              borderRadius: "10px",
              padding: "1.2rem",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: VEHICLE_COLORS.cars, marginBottom: "0.5rem" }}>
              <Car size={18} />
              <span style={{ fontSize: "13px", fontWeight: 700 }}>{t("sourceApportionment.cars")}</span>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem", margin: "0.3rem 0" }}>
              <span style={{ fontSize: "2rem", fontWeight: 800, fontFamily: "var(--mono)", color: VEHICLE_COLORS.cars }}>
                {data?.vehicle_breakdown?.cars_pct ?? 20}%
              </span>
              <span style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--mist)" }}>
                of vehicular emissions
              </span>
            </div>
            <div style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--bone)", marginBottom: "0.6rem" }}>
              Mass Contribution: <strong style={{ color: VEHICLE_COLORS.cars }}>{data?.vehicle_breakdown?.cars_mcg?.toFixed(1) ?? "—"} µg/m³</strong>
            </div>
            <div style={{ background: "rgba(255, 255, 255, 0.08)", height: "6px", borderRadius: "3px", overflow: "hidden", marginBottom: "0.8rem" }}>
              <div style={{ width: `${data?.vehicle_breakdown?.cars_pct ?? 20}%`, height: "100%", background: VEHICLE_COLORS.cars }} />
            </div>
            <p style={{ fontSize: "11.5px", color: "var(--mist)", margin: 0, lineHeight: 1.45 }}>
              Private petrol, diesel, and CNG passenger cars and commercial taxis. Congestion idling at intersections and non-exhaust brake/tire wear account for continuous baseline urban emissions.
            </p>
          </div>
        </div>

        {/* Diurnal Traffic Simulator Controls (When Manual Mode Active) */}
        {isManual && (
          <div style={{ marginTop: "1.3rem", padding: "1.1rem", background: "rgba(245, 158, 11, 0.07)", border: "1px solid rgba(245, 158, 11, 0.35)", borderRadius: "8px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.6rem", marginBottom: "0.9rem" }}>
              <span style={{ fontSize: "12px", fontWeight: 700, color: "var(--amber)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                🛠️ Interactive Traffic &amp; Policy Scenario Engine
              </span>
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                <button
                  type="button"
                  onClick={() => { setManualNo2(18); setManualHour(14); }}
                  style={{ fontSize: "11px", padding: "0.3rem 0.65rem", background: "var(--slab-hi)", border: "1px solid var(--hairline)", borderRadius: "4px", color: "var(--bone)", cursor: "pointer" }}
                >
                  Strict Traffic Ban / Strike (NO₂=18)
                </button>
                <button
                  type="button"
                  onClick={() => { setManualNo2(60); setManualHour(2); }}
                  style={{ fontSize: "11px", padding: "0.3rem 0.65rem", background: "var(--slab-hi)", border: "1px solid var(--hairline)", borderRadius: "4px", color: "var(--bone)", cursor: "pointer" }}
                >
                  Night Truck Entry (02:00 IST)
                </button>
                <button
                  type="button"
                  onClick={() => { setManualNo2(75); setManualHour(9); }}
                  style={{ fontSize: "11px", padding: "0.3rem 0.65rem", background: "var(--slab-hi)", border: "1px solid var(--hairline)", borderRadius: "4px", color: "var(--bone)", cursor: "pointer" }}
                >
                  Rush Hour Gridlock (09:00 IST)
                </button>
                <button
                  type="button"
                  onClick={() => { setManualNo2(currentNo2); setManualHour(new Date().getHours()); setIsManual(false); }}
                  style={{ fontSize: "11px", padding: "0.3rem 0.65rem", background: "rgba(255, 255, 255, 0.08)", border: "1px solid var(--hairline)", borderRadius: "4px", color: "var(--cyan)", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: "3px" }}
                >
                  <RotateCcw size={11} /> Reset
                </button>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1.2rem" }}>
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.35rem" }}>
                  <label style={{ fontSize: "11px", color: "var(--bone)", fontWeight: 600 }}>Adjust Ambient NO₂ Tracer:</label>
                  <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--amber)", fontWeight: 700 }}>{manualNo2} µg/m³</span>
                </div>
                <input
                  type="range"
                  min="5"
                  max="120"
                  step="1"
                  value={manualNo2}
                  onChange={(e) => setManualNo2(parseFloat(e.target.value))}
                  style={{ width: "100%", accentColor: "var(--amber)", cursor: "pointer" }}
                />
              </div>

              <div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.35rem" }}>
                  <label style={{ fontSize: "11px", color: "var(--bone)", fontWeight: 600 }}>Simulate Hour of Day (IST):</label>
                  <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--cyan)", fontWeight: 700 }}>{manualHour.toString().padStart(2, "0")}:00 hrs</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="23"
                  step="1"
                  value={manualHour}
                  onChange={(e) => setManualHour(parseInt(e.target.value, 10))}
                  style={{ width: "100%", accentColor: "var(--cyan)", cursor: "pointer" }}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── STAGE 4: ULTRA-PREMIUM 72-HOUR PREDICTIVE SOURCE TIME-SERIES CHART ── */}
      <article className="realism-box" style={{ width: "100%" }}>
        <div className="realism-topglow" />
        <div className="realism-blob" style={{ background: "radial-gradient(circle, #38bdf866 0%, transparent 70%)" }} />
        <div className="realism-inner" style={{ padding: "clamp(1.2rem, 2vw, 1.8rem)" }}>
          <div className="realism-inner-glow" />

          {/* Chart Header & Controls */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "1rem", marginBottom: "1.2rem" }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <span className="daily-pulse-dot" style={{ background: "#38bdf8", boxShadow: "0 0 10px #38bdf8" }} />
                <span style={{ fontSize: "11px", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.14em", color: "var(--cyan)", fontWeight: 700 }}>
                  STEP 3 · 72-Hour Continuous Atmospheric Trajectory
                </span>
              </div>
              <h3 style={{ fontSize: "1.35rem", fontWeight: 600, color: "var(--bone)", margin: "0.25rem 0 0", letterSpacing: "-0.02em" }}>
                {t("sourceApportionment.timeSeriesTitle")}
              </h3>
            </div>

            {/* Premium Metallic Segmented Switcher */}
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
                onClick={() => setTimeSeriesMode("fleet")}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "0.45rem 0.95rem",
                  borderRadius: "6px",
                  fontSize: "12px",
                  fontFamily: "var(--mono)",
                  fontWeight: 700,
                  cursor: "pointer",
                  border: "none",
                  background: timeSeriesMode === "fleet" ? "linear-gradient(135deg, #38bdf8, #0284c7)" : "transparent",
                  color: timeSeriesMode === "fleet" ? "#04111d" : "var(--mist)",
                  boxShadow: timeSeriesMode === "fleet" ? "0 2px 10px rgba(56, 189, 248, 0.4)" : "none",
                  transition: "all 0.2s ease",
                }}
              >
                <Truck size={14} /> Fleet Zoom (6 Layers)
              </button>
              <button
                type="button"
                onClick={() => setTimeSeriesMode("macro")}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "0.45rem 0.95rem",
                  borderRadius: "6px",
                  fontSize: "12px",
                  fontFamily: "var(--mono)",
                  fontWeight: 700,
                  cursor: "pointer",
                  border: "none",
                  background: timeSeriesMode === "macro" ? "linear-gradient(135deg, #38bdf8, #0284c7)" : "transparent",
                  color: timeSeriesMode === "macro" ? "#04111d" : "var(--mist)",
                  boxShadow: timeSeriesMode === "macro" ? "0 2px 10px rgba(56, 189, 248, 0.4)" : "none",
                  transition: "all 0.2s ease",
                }}
              >
                <Layers size={14} /> Macro Sectors (4 Layers)
              </button>
            </div>
          </div>

          {/* Interactive Luminous Legend Chips */}
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "0.6rem",
              marginBottom: "1.4rem",
              padding: "0.65rem 0.85rem",
              background: "rgba(10, 16, 26, 0.7)",
              borderRadius: "8px",
              border: "1px solid rgba(255, 255, 255, 0.06)",
            }}
          >
            <button
              type="button"
              onMouseEnter={() => setHighlightedKey("dust_mcg")}
              onMouseLeave={() => setHighlightedKey(null)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                padding: "0.3rem 0.7rem",
                borderRadius: "5px",
                background: highlightedKey === "dust_mcg" ? "rgba(251, 191, 36, 0.2)" : "rgba(255, 255, 255, 0.03)",
                border: `1px solid ${highlightedKey === "dust_mcg" ? SECTOR_COLORS.dust : "rgba(255, 255, 255, 0.08)"}`,
                color: "var(--bone)",
                fontSize: "11px",
                fontFamily: "var(--mono)",
                cursor: "pointer",
                transition: "all 0.2s ease",
              }}
            >
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: SECTOR_COLORS.dust, boxShadow: `0 0 8px ${SECTOR_COLORS.dust}` }} />
              Road Dust: <strong style={{ color: SECTOR_COLORS.dust }}>{data?.dust_mcg?.toFixed(1) ?? "46.2"} µg/m³</strong> (30%)
            </button>

            <button
              type="button"
              onMouseEnter={() => setHighlightedKey("biomass_mcg")}
              onMouseLeave={() => setHighlightedKey(null)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                padding: "0.3rem 0.7rem",
                borderRadius: "5px",
                background: highlightedKey === "biomass_mcg" ? "rgba(249, 115, 22, 0.2)" : "rgba(255, 255, 255, 0.03)",
                border: `1px solid ${highlightedKey === "biomass_mcg" ? SECTOR_COLORS.biomass : "rgba(255, 255, 255, 0.08)"}`,
                color: "var(--bone)",
                fontSize: "11px",
                fontFamily: "var(--mono)",
                cursor: "pointer",
                transition: "all 0.2s ease",
              }}
            >
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: SECTOR_COLORS.biomass, boxShadow: `0 0 8px ${SECTOR_COLORS.biomass}` }} />
              Biomass / Stubble: <strong style={{ color: SECTOR_COLORS.biomass }}>{data?.biomass_mcg?.toFixed(1) ?? "38.5"} µg/m³</strong> (25%)
            </button>

            <button
              type="button"
              onMouseEnter={() => setHighlightedKey("industry_mcg")}
              onMouseLeave={() => setHighlightedKey(null)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                padding: "0.3rem 0.7rem",
                borderRadius: "5px",
                background: highlightedKey === "industry_mcg" ? "rgba(192, 132, 252, 0.2)" : "rgba(255, 255, 255, 0.03)",
                border: `1px solid ${highlightedKey === "industry_mcg" ? SECTOR_COLORS.industry : "rgba(255, 255, 255, 0.08)"}`,
                color: "var(--bone)",
                fontSize: "11px",
                fontFamily: "var(--mono)",
                cursor: "pointer",
                transition: "all 0.2s ease",
              }}
            >
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: SECTOR_COLORS.industry, boxShadow: `0 0 8px ${SECTOR_COLORS.industry}` }} />
              Industry &amp; Power: <strong style={{ color: SECTOR_COLORS.industry }}>{data?.industry_mcg?.toFixed(1) ?? "30.8"} µg/m³</strong> (20%)
            </button>

            {timeSeriesMode === "fleet" ? (
              <>
                <button
                  type="button"
                  onMouseEnter={() => setHighlightedKey("trucks_mcg")}
                  onMouseLeave={() => setHighlightedKey(null)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "0.3rem 0.7rem",
                    borderRadius: "5px",
                    background: highlightedKey === "trucks_mcg" ? "rgba(244, 63, 94, 0.2)" : "rgba(255, 255, 255, 0.03)",
                    border: `1px solid ${highlightedKey === "trucks_mcg" ? VEHICLE_COLORS.trucks : "rgba(255, 255, 255, 0.08)"}`,
                    color: "var(--bone)",
                    fontSize: "11px",
                    fontFamily: "var(--mono)",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: VEHICLE_COLORS.trucks, boxShadow: `0 0 8px ${VEHICLE_COLORS.trucks}` }} />
                  Heavy Trucks: <strong style={{ color: VEHICLE_COLORS.trucks }}>{data?.vehicle_breakdown?.heavy_trucks_mcg?.toFixed(1) ?? "11.6"} µg/m³</strong>
                </button>

                <button
                  type="button"
                  onMouseEnter={() => setHighlightedKey("two_wheelers_mcg")}
                  onMouseLeave={() => setHighlightedKey(null)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "0.3rem 0.7rem",
                    borderRadius: "5px",
                    background: highlightedKey === "two_wheelers_mcg" ? "rgba(56, 189, 248, 0.2)" : "rgba(255, 255, 255, 0.03)",
                    border: `1px solid ${highlightedKey === "two_wheelers_mcg" ? VEHICLE_COLORS.twoWheelers : "rgba(255, 255, 255, 0.08)"}`,
                    color: "var(--bone)",
                    fontSize: "11px",
                    fontFamily: "var(--mono)",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: VEHICLE_COLORS.twoWheelers, boxShadow: `0 0 8px ${VEHICLE_COLORS.twoWheelers}` }} />
                  2 &amp; 3-Wheelers: <strong style={{ color: VEHICLE_COLORS.twoWheelers }}>{data?.vehicle_breakdown?.two_three_wheelers_mcg?.toFixed(1) ?? "19.3"} µg/m³</strong>
                </button>

                <button
                  type="button"
                  onMouseEnter={() => setHighlightedKey("cars_mcg")}
                  onMouseLeave={() => setHighlightedKey(null)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "0.3rem 0.7rem",
                    borderRadius: "5px",
                    background: highlightedKey === "cars_mcg" ? "rgba(52, 211, 153, 0.2)" : "rgba(255, 255, 255, 0.03)",
                    border: `1px solid ${highlightedKey === "cars_mcg" ? VEHICLE_COLORS.cars : "rgba(255, 255, 255, 0.08)"}`,
                    color: "var(--bone)",
                    fontSize: "11px",
                    fontFamily: "var(--mono)",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: VEHICLE_COLORS.cars, boxShadow: `0 0 8px ${VEHICLE_COLORS.cars}` }} />
                  Cars &amp; Taxis: <strong style={{ color: VEHICLE_COLORS.cars }}>{data?.vehicle_breakdown?.cars_mcg?.toFixed(1) ?? "7.7"} µg/m³</strong>
                </button>
              </>
            ) : (
              <button
                type="button"
                onMouseEnter={() => setHighlightedKey("transport_mcg")}
                onMouseLeave={() => setHighlightedKey(null)}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "0.3rem 0.7rem",
                  borderRadius: "5px",
                  background: highlightedKey === "transport_mcg" ? "rgba(56, 189, 248, 0.2)" : "rgba(255, 255, 255, 0.03)",
                  border: `1px solid ${highlightedKey === "transport_mcg" ? SECTOR_COLORS.transport : "rgba(255, 255, 255, 0.08)"}`,
                  color: "var(--bone)",
                  fontSize: "11px",
                  fontFamily: "var(--mono)",
                  cursor: "pointer",
                  transition: "all 0.2s ease",
                }}
              >
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: SECTOR_COLORS.transport, boxShadow: `0 0 8px ${SECTOR_COLORS.transport}` }} />
                Total Vehicular Transport: <strong style={{ color: SECTOR_COLORS.transport }}>{data?.transport_mcg?.toFixed(1) ?? "38.5"} µg/m³</strong> (25%)
              </button>
            )}
          </div>

          {/* High-Fidelity Area Chart */}
          <div style={{ width: "100%", height: "320px" }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={formattedTimeSeries} margin={{ top: 12, right: 12, left: -10, bottom: 0 }}>
                <defs>
                  {/* Road Dust Luminous Gradient */}
                  <linearGradient id="area-dust" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#fbbf24" stopOpacity={highlightedKey && highlightedKey !== "dust_mcg" ? 0.2 : 0.85} />
                    <stop offset="95%" stopColor="#d97706" stopOpacity={0.15} />
                  </linearGradient>

                  {/* Biomass Stubble Luminous Gradient */}
                  <linearGradient id="area-biomass" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f97316" stopOpacity={highlightedKey && highlightedKey !== "biomass_mcg" ? 0.2 : 0.85} />
                    <stop offset="95%" stopColor="#c2410c" stopOpacity={0.15} />
                  </linearGradient>

                  {/* Industry Luminous Gradient */}
                  <linearGradient id="area-industry" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#c084fc" stopOpacity={highlightedKey && highlightedKey !== "industry_mcg" ? 0.2 : 0.85} />
                    <stop offset="95%" stopColor="#7e22ce" stopOpacity={0.15} />
                  </linearGradient>

                  {/* Heavy Trucks Luminous Gradient */}
                  <linearGradient id="area-trucks" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f43f5e" stopOpacity={highlightedKey && highlightedKey !== "trucks_mcg" ? 0.2 : 0.9} />
                    <stop offset="95%" stopColor="#be123c" stopOpacity={0.2} />
                  </linearGradient>

                  {/* 2 & 3-Wheelers Luminous Gradient */}
                  <linearGradient id="area-twowheelers" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#38bdf8" stopOpacity={highlightedKey && highlightedKey !== "two_wheelers_mcg" ? 0.2 : 0.85} />
                    <stop offset="95%" stopColor="#0369a1" stopOpacity={0.15} />
                  </linearGradient>

                  {/* Cars Luminous Gradient */}
                  <linearGradient id="area-cars" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#34d399" stopOpacity={highlightedKey && highlightedKey !== "cars_mcg" ? 0.2 : 0.85} />
                    <stop offset="95%" stopColor="#047857" stopOpacity={0.15} />
                  </linearGradient>

                  {/* Total Transport Luminous Gradient */}
                  <linearGradient id="area-transport" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#38bdf8" stopOpacity={highlightedKey && highlightedKey !== "transport_mcg" ? 0.2 : 0.85} />
                    <stop offset="95%" stopColor="#0284c7" stopOpacity={0.15} />
                  </linearGradient>
                </defs>

                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.08)" vertical={false} />
                <XAxis
                  dataKey="timestamp"
                  stroke="rgba(255, 255, 255, 0.5)"
                  fontSize={11}
                  fontFamily="var(--mono)"
                  tickLine={false}
                  interval={5}
                />
                <YAxis
                  stroke="rgba(255, 255, 255, 0.5)"
                  fontSize={11}
                  fontFamily="var(--mono)"
                  tickLine={false}
                  unit=" µg"
                />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload || !payload.length) return null;
                    const totalVal = payload.reduce((acc, curr) => acc + (Number(curr.value) || 0), 0);
                    return (
                      <div
                        style={{
                          background: "rgba(10, 16, 26, 0.95)",
                          border: "1px solid rgba(255, 255, 255, 0.18)",
                          borderRadius: "10px",
                          padding: "0.85rem 1rem",
                          boxShadow: "0 14px 35px rgba(0, 0, 0, 0.75)",
                          backdropFilter: "blur(12px)",
                          fontFamily: "var(--mono)",
                          fontSize: "12px",
                          minWidth: "220px",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid rgba(255,255,255,0.1)", paddingBottom: "0.4rem", marginBottom: "0.5rem" }}>
                          <span style={{ color: "var(--mist)", fontSize: "11px" }}>{label}</span>
                          <span style={{ color: "var(--cyan)", fontWeight: 700 }}>{totalVal.toFixed(1)} µg/m³</span>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                          {payload.map((entry, idx) => {
                            const nameMap: Record<string, string> = {
                              dust_mcg: "Road Dust",
                              biomass_mcg: "Biomass / Stubble",
                              industry_mcg: "Industry & Power",
                              trucks_mcg: "Heavy Diesel Trucks",
                              two_wheelers_mcg: "2 & 3-Wheelers",
                              cars_mcg: "Cars & Taxis",
                              transport_mcg: "Total Transport",
                            };
                            const displayName = nameMap[String(entry.dataKey)] || String(entry.dataKey);
                            const val = Number(entry.value) || 0;
                            const pct = totalVal > 0 ? ((val / totalVal) * 100).toFixed(0) : "0";
                            return (
                              <div key={idx} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.8rem" }}>
                                <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", color: "var(--bone)", fontSize: "11.5px" }}>
                                  <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: entry.color }} />
                                  {displayName}
                                </span>
                                <span style={{ color: entry.color, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
                                  {val.toFixed(1)} µg ({pct}%)
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  }}
                />

                <Area
                  type="monotone"
                  dataKey="dust_mcg"
                  stackId="1"
                  stroke={SECTOR_COLORS.dust}
                  strokeWidth={2}
                  fill="url(#area-dust)"
                />
                <Area
                  type="monotone"
                  dataKey="biomass_mcg"
                  stackId="1"
                  stroke={SECTOR_COLORS.biomass}
                  strokeWidth={2}
                  fill="url(#area-biomass)"
                />
                <Area
                  type="monotone"
                  dataKey="industry_mcg"
                  stackId="1"
                  stroke={SECTOR_COLORS.industry}
                  strokeWidth={2}
                  fill="url(#area-industry)"
                />

                {timeSeriesMode === "fleet" ? (
                  <>
                    <Area
                      type="monotone"
                      dataKey="trucks_mcg"
                      stackId="1"
                      stroke={VEHICLE_COLORS.trucks}
                      strokeWidth={2.2}
                      fill="url(#area-trucks)"
                    />
                    <Area
                      type="monotone"
                      dataKey="two_wheelers_mcg"
                      stackId="1"
                      stroke={VEHICLE_COLORS.twoWheelers}
                      strokeWidth={2.2}
                      fill="url(#area-twowheelers)"
                    />
                    <Area
                      type="monotone"
                      dataKey="cars_mcg"
                      stackId="1"
                      stroke={VEHICLE_COLORS.cars}
                      strokeWidth={2.2}
                      fill="url(#area-cars)"
                    />
                  </>
                ) : (
                  <Area
                    type="monotone"
                    dataKey="transport_mcg"
                    stackId="1"
                    stroke={SECTOR_COLORS.transport}
                    strokeWidth={2.5}
                    fill="url(#area-transport)"
                  />
                )}
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </article>
    </section>
  );
}
export default SourceApportionment;
