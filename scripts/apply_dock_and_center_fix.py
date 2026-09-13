import re

# 1. Update Rail.tsx
rail_code = r"""import { useState } from "react";
import {
  RotateCw,
  Menu,
  X,
  TrendingUp,
  History,
  CloudRain,
  Thermometer,
  MapPin,
  LayoutGrid,
  CheckCircle2,
  ChevronRight,
  HeartPulse,
  BarChart3,
  Layers,
  Bot,
} from "lucide-react";

import { HERO_VIDEOS } from "@/components/Hero";
import { Button } from "@/components/ui/button";
import type { Feeds } from "@/hooks/useForecastData";

export type PageType =
  | "overview"
  | "forecast-datas"
  | "historic-data"
  | "atmospheric-dynamics"
  | "exposure-tracker"
  | "health-assistant";

export interface RailProps {
  feeds?: Feeds;
  stamp: string;
  onRefresh: () => void;
  currentPage?: PageType;
  onPageChange?: (page: PageType) => void;
  activeVideo?: number;
  onVideoChange?: (index: number) => void;
}

export function Rail({
  stamp,
  onRefresh,
  currentPage = "overview",
  onPageChange,
  activeVideo = 0,
  onVideoChange,
}: RailProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  const overviewNavItems = [
    { id: "forecast-hero", label: "72-Hour Prognostic Forecast", icon: TrendingUp, desc: "Hourly AQI outlook & CPCB sub-indices" },
    { id: "pollutant-card-stack", label: "3D Pollutant Particle Stack", icon: Layers, desc: "Interactive 6-species criteria breakdown" },
    { id: "consensus-dashboard", label: "Delhi NCR Live Conditions", icon: CheckCircle2, desc: "5-source multi-provider ensemble & confidence" },
    { id: "station-map-view", label: "Spatial Dispersion Map", icon: MapPin, desc: "Plume vector contours & 43 CAAQMS stations" },
    { id: "source-apportionment", label: "Source Apportionment", icon: Thermometer, desc: "Vehicular, dust, industrial & biomass attribution" },
    { id: "stations-grid", label: "Real-Time Stations Network", icon: LayoutGrid, desc: "Continuous ambient monitoring network metrics" },
  ];

  const handleSelectPage = (page: PageType) => {
    setMenuOpen(false);
    if (onPageChange) {
      onPageChange(page);
    }
  };

  return (
    <>
      <header className="rail" style={{ position: "relative", width: "100%" }}>
        {/* Left: Brand & Menu */}
        <div style={{ display: "flex", alignItems: "center", gap: "1.2rem", zIndex: 10 }}>
          {/* Navigation Menu Button */}
          <button
            type="button"
            className="btn btn--solid"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.4rem",
              padding: "0.4rem 0.8rem",
              background: menuOpen ? "var(--slab-hi)" : "var(--slab)",
              border: "1px solid var(--hairline-2)",
              borderRadius: "4px",
              color: "var(--bone)",
              fontFamily: "var(--mono)",
              fontSize: "12px",
              cursor: "pointer",
            }}
            onClick={() => setMenuOpen(!menuOpen)}
            aria-expanded={menuOpen}
            aria-label="Navigation Menu"
          >
            {menuOpen ? <X size={15} /> : <Menu size={15} />}
            <span>Menu</span>
          </button>

          <div
            className="rail__brand"
            style={{ cursor: "pointer" }}
            onClick={() => handleSelectPage("overview")}
            title="Return to Main Overview Console"
          >
            <span className="rail__mark" aria-hidden="true" />
            <span className="rail__name">
              NCR<span className="rail__dot">·</span>72
            </span>
            <span className="rail__sub">coupled aqi forecast</span>
          </div>
        </div>

        {/* Center: EXACT 100% Dead-Centered Liquid-Glass Video Theme Switcher */}
        {onVideoChange && (
          <div
            style={{
              position: "absolute",
              left: "50%",
              top: "50%",
              transform: "translate(-50%, -50%)",
              zIndex: 50,
              pointerEvents: "auto",
            }}
          >
            <div
              className="liquid-glass"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.25rem",
                padding: "0.22rem 0.32rem",
                borderRadius: "9999px",
                background: "rgba(15, 20, 30, 0.7)",
                backdropFilter: "blur(20px) saturate(180%)",
                WebkitBackdropFilter: "blur(20px) saturate(180%)",
                border: "1px solid rgba(255, 255, 255, 0.22)",
                boxShadow: "0 8px 32px rgba(0,0,0,0.4), inset 0 1px 1px rgba(255,255,255,0.25)",
              }}
            >
              {HERO_VIDEOS.map((v, i) => {
                const isActive = activeVideo === i;
                return (
                  <button
                    key={v.id}
                    type="button"
                    onClick={() => onVideoChange(i)}
                    style={{
                      padding: "0.25rem 0.75rem",
                      borderRadius: "9999px",
                      fontSize: "11px",
                      fontFamily: "var(--mono)",
                      fontWeight: isActive ? 600 : 400,
                      color: isActive ? "#FFFFFF" : "rgba(255, 255, 255, 0.75)",
                      background: isActive ? "rgba(255, 255, 255, 0.22)" : "transparent",
                      border: `1px solid ${isActive ? "rgba(255, 255, 255, 0.38)" : "transparent"}`,
                      boxShadow: isActive ? "0 2px 8px rgba(0, 0, 0, 0.25), inset 0 1px 1px rgba(255, 255, 255, 0.3)" : "none",
                      cursor: "pointer",
                      transition: "all 0.25s ease",
                      outline: "none",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {v.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Right: Timestamp & Refresh */}
        <div className="rail__right" style={{ zIndex: 10 }}>
          <span className="rail__stamp">{stamp}</span>
          <Button onClick={onRefresh}>
            <RotateCw className="btn__icon" aria-hidden="true" />
            <span>Refresh</span>
          </Button>
        </div>
      </header>

      {/* Navigation Menu Drawer / Dropdown */}
      {menuOpen && (
        <div
          style={{
            position: "fixed",
            top: "48px",
            left: "0",
            right: "0",
            bottom: "0",
            background: "rgba(0, 0, 0, 0.8)",
            backdropFilter: "blur(8px)",
            zIndex: 9999,
            display: "flex",
            justifyContent: "flex-start",
          }}
          onClick={() => setMenuOpen(false)}
        >
          <div
            style={{
              width: "100%",
              maxWidth: "440px",
              height: "100%",
              background: "var(--abyss)",
              borderRight: "1px solid var(--hairline)",
              padding: "1.5rem",
              overflowY: "auto",
              boxShadow: "4px 0 24px rgba(0, 0, 0, 0.6)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "1.2rem",
                paddingBottom: "1rem",
                borderBottom: "1px solid var(--hairline)",
              }}
            >
              <div>
                <h3 style={{ margin: 0, fontSize: "1.1rem", color: "var(--bone)" }}>Navigation Index</h3>
                <p style={{ margin: "0.2rem 0 0", fontSize: "12px", color: "var(--mist-faint)" }}>
                  Navigate between pages and analytical modules
                </p>
              </div>
              <button
                type="button"
                className="btn btn--solid"
                style={{ padding: "0.3rem 0.5rem", cursor: "pointer" }}
                onClick={() => setMenuOpen(false)}
                aria-label="Close menu"
              >
                <X size={16} />
              </button>
            </div>

            {/* Dedicated Pages Selector */}
            <div style={{ marginBottom: "1.8rem" }}>
              <div
                style={{
                  fontSize: "10.5px",
                  fontFamily: "var(--mono)",
                  color: "var(--mist-dim)",
                  textTransform: "uppercase",
                  letterSpacing: "0.18em",
                  marginBottom: "0.75rem",
                }}
              >
                Select Page View
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "0.55rem" }}>
                <button
                  type="button"
                  onClick={() => handleSelectPage("overview")}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0.8rem 0.95rem",
                    background: currentPage === "overview" ? "var(--slab-hi)" : "var(--slab)",
                    border: `1px solid ${currentPage === "overview" ? "var(--live)" : "var(--hairline)"}`,
                    borderRadius: "4px",
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "all 0.2s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem" }}>
                    <Layers size={18} style={{ color: currentPage === "overview" ? "var(--live)" : "var(--mist)", marginTop: "2px" }} />
                    <div>
                      <div style={{ color: "var(--bone)", fontSize: "13px", fontWeight: 600, display: "flex", alignItems: "center", gap: "0.4rem" }}>
                        <span>Overview &amp; Live Console</span>
                        {currentPage === "overview" && (
                          <span style={{ fontSize: "10px", background: "var(--live)", color: "#000", padding: "1px 5px", borderRadius: "3px", fontWeight: 700 }}>
                            ACTIVE
                          </span>
                        )}
                      </div>
                      <div style={{ color: "var(--mist-dim)", fontSize: "11.5px", marginTop: "2px" }}>
                        Main coupled 72h forecast, CPCB particle cardstack, consensus &amp; maps
                      </div>
                    </div>
                  </div>
                  <ChevronRight size={16} style={{ color: "var(--mist-faint)" }} />
                </button>

                <button
                  type="button"
                  onClick={() => handleSelectPage("forecast-datas")}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0.8rem 0.95rem",
                    background: currentPage === "forecast-datas" ? "var(--slab-hi)" : "var(--slab)",
                    border: `1px solid ${currentPage === "forecast-datas" ? "var(--live)" : "var(--hairline)"}`,
                    borderRadius: "4px",
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "all 0.2s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem" }}>
                    <BarChart3 size={18} style={{ color: currentPage === "forecast-datas" ? "var(--live)" : "var(--mist)", marginTop: "2px" }} />
                    <div>
                      <div style={{ color: "var(--bone)", fontSize: "13px", fontWeight: 600, display: "flex", alignItems: "center", gap: "0.4rem" }}>
                        <span>Forecast &amp; Model Dynamics</span>
                        {currentPage === "forecast-datas" && (
                          <span style={{ fontSize: "10px", background: "var(--live)", color: "#000", padding: "1px 5px", borderRadius: "3px", fontWeight: 700 }}>
                            ACTIVE
                          </span>
                        )}
                      </div>
                      <div style={{ color: "var(--mist-dim)", fontSize: "11.5px", marginTop: "2px" }}>
                        Deep multi-model forecast charts, confidence bands &amp; hourly trajectories
                      </div>
                    </div>
                  </div>
                  <ChevronRight size={16} style={{ color: "var(--mist-faint)" }} />
                </button>

                <button
                  type="button"
                  onClick={() => handleSelectPage("historic-data")}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0.8rem 0.95rem",
                    background: currentPage === "historic-data" ? "var(--slab-hi)" : "var(--slab)",
                    border: `1px solid ${currentPage === "historic-data" ? "var(--live)" : "var(--hairline)"}`,
                    borderRadius: "4px",
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "all 0.2s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem" }}>
                    <History size={18} style={{ color: currentPage === "historic-data" ? "var(--live)" : "var(--mist)", marginTop: "2px" }} />
                    <div>
                      <div style={{ color: "var(--bone)", fontSize: "13px", fontWeight: 600, display: "flex", alignItems: "center", gap: "0.4rem" }}>
                        <span>Historic Trends &amp; Archives</span>
                        {currentPage === "historic-data" && (
                          <span style={{ fontSize: "10px", background: "var(--live)", color: "#000", padding: "1px 5px", borderRadius: "3px", fontWeight: 700 }}>
                            ACTIVE
                          </span>
                        )}
                      </div>
                      <div style={{ color: "var(--mist-dim)", fontSize: "11.5px", marginTop: "2px" }}>
                        Retrospective historical records, multi-year comparisons &amp; seasonal baselines
                      </div>
                    </div>
                  </div>
                  <ChevronRight size={16} style={{ color: "var(--mist-faint)" }} />
                </button>

                <button
                  type="button"
                  onClick={() => handleSelectPage("atmospheric-dynamics")}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0.8rem 0.95rem",
                    background: currentPage === "atmospheric-dynamics" ? "var(--slab-hi)" : "var(--slab)",
                    border: `1px solid ${currentPage === "atmospheric-dynamics" ? "var(--live)" : "var(--hairline)"}`,
                    borderRadius: "4px",
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "all 0.2s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem" }}>
                    <CloudRain size={18} style={{ color: currentPage === "atmospheric-dynamics" ? "var(--live)" : "var(--mist)", marginTop: "2px" }} />
                    <div>
                      <div style={{ color: "var(--bone)", fontSize: "13px", fontWeight: 600, display: "flex", alignItems: "center", gap: "0.4rem" }}>
                        <span>Atmospheric Dynamics</span>
                        {currentPage === "atmospheric-dynamics" && (
                          <span style={{ fontSize: "10px", background: "var(--live)", color: "#000", padding: "1px 5px", borderRadius: "3px", fontWeight: 700 }}>
                            ACTIVE
                          </span>
                        )}
                      </div>
                      <div style={{ color: "var(--mist-dim)", fontSize: "11.5px", marginTop: "2px" }}>
                        Boundary layer inversion, ventilation coefficient, wind vectors &amp; humidity
                      </div>
                    </div>
                  </div>
                  <ChevronRight size={16} style={{ color: "var(--mist-faint)" }} />
                </button>

                <button
                  type="button"
                  onClick={() => handleSelectPage("exposure-tracker")}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0.8rem 0.95rem",
                    background: currentPage === "exposure-tracker" ? "var(--slab-hi)" : "var(--slab)",
                    border: `1px solid ${currentPage === "exposure-tracker" ? "var(--live)" : "var(--hairline)"}`,
                    borderRadius: "4px",
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "all 0.2s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem" }}>
                    <HeartPulse size={18} style={{ color: currentPage === "exposure-tracker" ? "var(--live)" : "var(--mist)", marginTop: "2px" }} />
                    <div>
                      <div style={{ color: "var(--bone)", fontSize: "13px", fontWeight: 600, display: "flex", alignItems: "center", gap: "0.4rem" }}>
                        <span>Health &amp; Exposure Tracker</span>
                        {currentPage === "exposure-tracker" && (
                          <span style={{ fontSize: "10px", background: "var(--live)", color: "#000", padding: "1px 5px", borderRadius: "3px", fontWeight: 700 }}>
                            ACTIVE
                          </span>
                        )}
                      </div>
                      <div style={{ color: "var(--mist-dim)", fontSize: "11.5px", marginTop: "2px" }}>
                        Dosage calculation, activity guidance &amp; vulnerable population warnings
                      </div>
                    </div>
                  </div>
                  <ChevronRight size={16} style={{ color: "var(--mist-faint)" }} />
                </button>

                <button
                  type="button"
                  onClick={() => handleSelectPage("health-assistant")}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0.8rem 0.95rem",
                    background: currentPage === "health-assistant" ? "var(--slab-hi)" : "var(--slab)",
                    border: `1px solid ${currentPage === "health-assistant" ? "var(--live)" : "var(--hairline)"}`,
                    borderRadius: "4px",
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "all 0.2s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem" }}>
                    <Bot size={18} style={{ color: currentPage === "health-assistant" ? "var(--live)" : "var(--mist)", marginTop: "2px" }} />
                    <div>
                      <div style={{ color: "var(--bone)", fontSize: "13px", fontWeight: 600, display: "flex", alignItems: "center", gap: "0.4rem" }}>
                        <span>Health Care Assistant</span>
                        {currentPage === "health-assistant" && (
                          <span style={{ fontSize: "10px", background: "var(--live)", color: "#000", padding: "1px 5px", borderRadius: "3px", fontWeight: 700 }}>
                            ACTIVE
                          </span>
                        )}
                      </div>
                      <div style={{ color: "var(--mist-dim)", fontSize: "11.5px", marginTop: "2px" }}>
                        AI-powered real-time respiratory health advisory, mask recommendations &amp; clinical insights
                      </div>
                    </div>
                  </div>
                  <ChevronRight size={16} style={{ color: "var(--mist-faint)" }} />
                </button>
              </div>
            </div>

            {/* Overview Anchors */}
            <div>
              <div
                style={{
                  fontSize: "10.5px",
                  fontFamily: "var(--mono)",
                  color: "var(--mist-dim)",
                  textTransform: "uppercase",
                  letterSpacing: "0.18em",
                  marginBottom: "0.75rem",
                }}
              >
                Overview Page Jump Links
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
                {overviewNavItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <a
                      key={item.id}
                      href={`#${item.id}`}
                      onClick={() => {
                        handleSelectPage("overview");
                        setTimeout(() => {
                          const el = document.getElementById(item.id);
                          if (el) el.scrollIntoView({ behavior: "smooth" });
                        }, 100);
                      }}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.75rem",
                        padding: "0.6rem 0.8rem",
                        color: "var(--mist)",
                        textDecoration: "none",
                        borderRadius: "3px",
                        fontSize: "12px",
                        background: "rgba(255, 255, 255, 0.02)",
                      }}
                    >
                      <Icon size={14} style={{ color: "var(--live)", flexShrink: 0 }} />
                      <div>
                        <div style={{ color: "var(--bone)", fontWeight: 500 }}>{item.label}</div>
                        <div style={{ color: "var(--mist-faint)", fontSize: "10.5px" }}>{item.desc}</div>
                      </div>
                    </a>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
"""

with open("webapp/src/components/Rail.tsx", "w", encoding="utf-8") as f:
    f.write(rail_code)

# 2. Update Hero.tsx with permanently anchored bottom navigation dock
hero_code = r"""import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Activity,
  AlertCircle,
  Sparkles,
  Wind,
  Clock,
  ShieldCheck,
  Layers,
  BarChart3,
  History,
  CloudRain,
  HeartPulse,
  Bot
} from "lucide-react";
import type { Panel } from "@/hooks/useForecastData";
import { aqiColor, aqiToCategory, pollutantSubIndex } from "@/lib/aqi";
import { dayClock, int, leadLabel } from "@/lib/format";
import type {
  CityAggregateResponse,
  ConsensusResponse,
  ForecastResponse,
  HourlyForecast,
  PollutantSubIndex,
} from "@/lib/types";
import { POLLUTANTS } from "@/lib/types";
import { Skeleton } from "@/components/ui/skeleton";
import { FoldText } from "@/components/ui/FoldText";
import type { PageType } from "@/components/Rail";

export interface HeroVideoConfig {
  id: string;
  label: string;
  url: string;
}

export const HERO_VIDEOS: readonly HeroVideoConfig[] = [
  {
    id: "golden-hour",
    label: "Golden Hour",
    url: "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260702_081127_0992a171-d3c6-4978-8213-0ec5df8b6d63.mp4",
  },
  {
    id: "still-water",
    label: "Still Water",
    url: "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260702_092026_dd05b805-ea0f-40b2-8c52-332b88502592.mp4",
  },
  {
    id: "deep-woods",
    label: "Deep Woods",
    url: "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260702_081042_df7202bf-bd80-4b2b-bbc6-1f09ba2870e9.mp4",
  },
  {
    id: "quiet-dawn",
    label: "Quiet Dawn",
    url: "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260702_080959_4cac5234-3573-464e-a5b7-76b94b8a7d61.mp4",
  },
] as const;

interface HeroProps {
  forecast: Panel<ForecastResponse>;
  hour: HourlyForecast | null;
  cursor: number;
  consensus?: ConsensusResponse | null;
  cityAggregate?: CityAggregateResponse | null;
  activeVideo?: number;
  onVideoChange?: (index: number) => void;
  ready?: boolean;
  currentPage?: PageType;
  onPageChange?: (page: PageType) => void;
}

interface AqiLevelSegment {
  name: string;
  min: number;
  max: number;
  color: string;
  label: string;
}

const AQI_LEVELS: readonly AqiLevelSegment[] = [
  { name: "Good", min: 0, max: 50, color: "#00B050", label: "0-50" },
  { name: "Moderate", min: 51, max: 100, color: "#92D050", label: "51-100" },
  { name: "Poor", min: 101, max: 200, color: "#FFD700", label: "101-200" },
  { name: "Unhealthy", min: 201, max: 300, color: "#FF9900", label: "201-300" },
  { name: "Severe", min: 301, max: 400, color: "#FF0000", label: "301-400" },
  { name: "Hazardous", min: 401, max: 500, color: "#700020", label: "301+" },
] as const;

function aqiToScalePercent(aqi: number): number {
  if (aqi <= 0) return 2;
  if (aqi >= 500) return 98;
  if (aqi <= 50) {
    return (aqi / 50) * 16.66;
  } else if (aqi <= 100) {
    return 16.66 + ((aqi - 50) / 50) * 16.67;
  } else if (aqi <= 200) {
    return 33.33 + ((aqi - 100) / 100) * 16.67;
  } else if (aqi <= 300) {
    return 50.0 + ((aqi - 200) / 100) * 16.66;
  } else if (aqi <= 400) {
    return 66.66 + ((aqi - 300) / 100) * 16.67;
  } else {
    return 83.33 + Math.min(1, (aqi - 400) / 100) * 14.5;
  }
}

export function Hero({
  forecast,
  hour,
  cursor,
  consensus,
  cityAggregate,
  activeVideo = 0,
  ready = false,
  currentPage = "overview",
  onPageChange,
}: HeroProps) {
  const videoRefs = useRef<(HTMLVideoElement | null)[]>([]);

  // Intro fold animation state with robust timer refs
  const [showIntro, setShowIntro] = useState<boolean>(true);
  const [introFading, setIntroFading] = useState<boolean>(false);
  const [introReady, setIntroReady] = useState<boolean>(false);

  const holdTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const completedRef = useRef<boolean>(false);

  // Clear timers on unmount
  useEffect(() => {
    return () => {
      if (holdTimerRef.current) clearTimeout(holdTimerRef.current);
      if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current);
    };
  }, []);

  // Wait until boot overlay lifts before starting the 3D unfolding animation
  useEffect(() => {
    if (ready) {
      const timer = setTimeout(() => {
        setIntroReady(true);
      }, 400); // 400ms after boot finishes
      return () => clearTimeout(timer);
    }
  }, [ready]);

  // Stable callback when GSAP timeline finishes unfolding all 27 characters
  const handleIntroComplete = useCallback(() => {
    if (completedRef.current) return;
    completedRef.current = true;
    if (holdTimerRef.current) clearTimeout(holdTimerRef.current);
    // Hold full text for 1.5 seconds so user can read "Lets Decode The Atmosphere"
    holdTimerRef.current = setTimeout(() => {
      setIntroFading(true);
      if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current);
      fadeTimerRef.current = setTimeout(() => {
        setShowIntro(false);
      }, 700);
    }, 1500);
  }, []);

  const handleSkipIntro = useCallback(() => {
    completedRef.current = true;
    if (holdTimerRef.current) clearTimeout(holdTimerRef.current);
    if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current);
    setIntroFading(true);
    fadeTimerRef.current = setTimeout(() => {
      setShowIntro(false);
    }, 250);
  }, []);

  // Autoplay and keep videos active
  useEffect(() => {
    videoRefs.current.forEach((video, idx) => {
      if (!video) return;
      video.muted = true;
      video.defaultMuted = true;
      if (idx === activeVideo) {
        const p = video.play();
        if (p !== undefined) {
          p.catch(() => {
            const onInteract = () => {
              video.play().catch(() => {});
              window.removeEventListener("click", onInteract);
            };
            window.addEventListener("click", onInteract, { once: true });
          });
        }
      }
    });
  }, [activeVideo]);

  const loc = forecast.data?.location;
  const coords = loc ? `${loc.lat.toFixed(2)}°N ${loc.lon.toFixed(2)}°E` : "28.61°N 77.21°E";
  const isLoading = forecast.status === "loading" && !hour && !cityAggregate;

  // Single source of truth for Sub-indices
  const subIndices: PollutantSubIndex[] = useMemo(() => {
    if (cursor === 0 && cityAggregate?.sub_indices) {
      return POLLUTANTS.map((p) => {
        const detail = cityAggregate.sub_indices[p];
        const subIdx = detail ? detail.index : 0;
        const conc = detail ? detail.conc : 0;
        return {
          pollutant: p,
          concentration: conc,
          sub_index: subIdx,
          category: aqiToCategory(subIdx),
        };
      });
    }

    if (hour?.sub_indices && hour.sub_indices.length > 0) {
      return POLLUTANTS.map((p) => {
        const found = hour.sub_indices.find((s) => s.pollutant === p);
        if (found) return found;
        return {
          pollutant: p,
          concentration: 0,
          sub_index: 0,
          category: "Good",
        };
      });
    }

    if (consensus?.metrics) {
      const m = consensus.metrics;
      return POLLUTANTS.map((p) => {
        let conc = 0;
        if (p === "PM2.5") conc = m.pm25;
        else if (p === "PM10") conc = m.pm10;
        else if (p === "NO2") conc = m.no2 ?? 38.5;
        else if (p === "O3") conc = m.o3 ?? 54.0;
        else if (p === "SO2") conc = m.so2 ?? 14.2;
        else if (p === "CO") conc = m.co ?? 0.82;
        const subIdx = pollutantSubIndex(p, conc);
        return {
          pollutant: p,
          concentration: conc,
          sub_index: subIdx,
          category: aqiToCategory(subIdx),
        };
      });
    }

    return [];
  }, [cursor, cityAggregate, hour, consensus]);

  const maxSub = subIndices.reduce(
    (max, cur) => (cur.sub_index > max.sub_index ? cur : max),
    subIndices[0] || { pollutant: "PM2.5", sub_index: 0, category: "Good", concentration: 0 }
  );

  const isLiveNow = cursor === 0;
  const displayAqi = isLiveNow
    ? (cityAggregate?.overall_aqi ?? (hour ? hour.aqi : consensus?.metrics ? Math.round(consensus.metrics.aqi) : maxSub.sub_index || 0))
    : (hour ? hour.aqi : maxSub.sub_index || 0);

  const displayCategory = isLiveNow
    ? (cityAggregate?.aqi_category ?? (hour ? hour.category : aqiToCategory(displayAqi)))
    : (hour ? hour.category : aqiToCategory(displayAqi));

  const dominantPollutant = isLiveNow
    ? (cityAggregate?.dominant_pollutant ?? (hour?.dominant_pollutant ?? maxSub.pollutant))
    : (hour?.dominant_pollutant ?? maxSub.pollutant);

  const activeColor = cityAggregate?.color && isLiveNow ? cityAggregate.color : aqiColor(displayAqi);
  const locationLabel = isLiveNow
    ? (cityAggregate?.location_label ?? "DELHI NCR · 43-STATION NETWORK AGGREGATE")
    : `DELHI NCR (+${cursor}h FORECAST)`;

  return (
    <div
      style={{
        position: "relative",
        isolation: "isolate",
        overflow: "hidden",
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        paddingTop: "3.5rem",
        paddingBottom: "5.5rem",
        paddingLeft: "1.5rem",
        paddingRight: "1.5rem",
        width: "100%",
      }}
    >
      {/* ── 1. STACKED FULLSCREEN VIDEOS (Z -3) ── */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          overflow: "hidden",
          pointerEvents: "none",
          zIndex: -3,
        }}
      >
        {HERO_VIDEOS.map((video, idx) => (
          <video
            key={video.id}
            ref={(el) => {
              videoRefs.current[idx] = el;
            }}
            src={video.url}
            autoPlay
            muted
            loop
            playsInline
            preload="auto"
            aria-hidden="true"
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              objectFit: "cover",
              transition: "opacity 1000ms ease-in-out",
              opacity: activeVideo === idx ? 1 : 0,
            }}
          />
        ))}
      </div>

      {/* ── 2. TRANSPARENT PNG OVERLAY WITH TRAIN-BOB MOTION (Z -2) ── */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          pointerEvents: "none",
          zIndex: -2,
          overflow: "hidden",
        }}
      >
        <img
          src="https://soft-zoom-63098134.figma.site/_assets/v11/0b4a435b2df2747593c43d7a1c9b4578f7d8d90c.png"
          alt=""
          className="animate-train-bob"
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }}
        />
      </div>

      {/* ── 3. Ultra-Minimal Vignette (Z -1) ── */}
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          inset: 0,
          zIndex: -1,
          background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 0%, rgba(0,0,0,0.18) 100%)",
          pointerEvents: "none",
        }}
      />

      {/* ── 4. Main Centerpiece: FoldText Intro Sequence -> Seamlessly reveals AQI Box ── */}
      <AnimatePresence mode="wait">
        {showIntro ? (
          <motion.div
            key="fold-intro-sequence"
            initial={{ opacity: 0, scale: 0.95, y: 15 }}
            animate={{
              opacity: introFading ? 0 : 1,
              scale: introFading ? 0.95 : 1,
              y: introFading ? -20 : 0,
            }}
            exit={{ opacity: 0, scale: 0.9, y: -30 }}
            transition={{ duration: 0.65, ease: [0.16, 1, 0.3, 1] }}
            style={{
              position: "relative",
              zIndex: 10,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              textAlign: "center",
              padding: "2rem 1.5rem",
              cursor: "pointer",
              userSelect: "none",
            }}
            onClick={handleSkipIntro}
            title="Click anywhere to proceed directly to live console"
          >
            <div
              style={{
                position: "relative",
                display: "inline-block",
                padding: "1rem 2rem",
                minHeight: "120px",
              }}
            >
              {introReady ? (
                <FoldText
                  text="Lets Decode The Atmosphere"
                  splitBy="char"
                  hinge="top"
                  trigger="mount"
                  duration={0.75}
                  stagger={0.045}
                  ease="power3.out"
                  perspective={750}
                  creaseShading={0.55}
                  fontSize="clamp(2.4rem, 6.2vw, 4.6rem)"
                  fontWeight={800}
                  color="#FFFFFF"
                  style={{
                    textShadow:
                      "0 8px 40px rgba(0,0,0,0.85), 0 0 50px rgba(255,255,255,0.45)",
                  }}
                  onComplete={handleIntroComplete}
                />
              ) : null}
            </div>

            <motion.span
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: introFading ? 0 : 0.75, y: 0 }}
              transition={{ delay: 0.8, duration: 0.6 }}
              style={{
                marginTop: "1.2rem",
                fontSize: "11.5px",
                fontFamily: "var(--mono)",
                color: "rgba(255, 255, 255, 0.75)",
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                textShadow: "0 2px 8px rgba(0,0,0,0.8)",
              }}
            >
              • Initializing Coupled Forecast Matrix •
            </motion.span>
          </motion.div>
        ) : (
          <motion.div
            key="aqi-crystal-showcase"
            style={{
              width: "100%",
              maxWidth: "650px",
              transform: "translateY(-16px)",
              zIndex: 5,
            }}
            initial={{ opacity: 0, scale: 0.93, y: 25 }}
            animate={{ opacity: 1, scale: 1, y: -16 }}
            transition={{ duration: 0.95, ease: [0.16, 1, 0.3, 1] }}
          >
            <div
              style={{
                width: "100%",
                borderRadius: "24px",
                padding: "1.6rem 2.2rem",
                background: "rgba(255, 255, 255, 0.015)",
                backdropFilter: "blur(3px)",
                WebkitBackdropFilter: "blur(3px)",
                border: "1px solid rgba(255, 255, 255, 0.14)",
                boxShadow:
                  "inset 0 1px 1px rgba(255, 255, 255, 0.2), 0 12px 36px rgba(0, 0, 0, 0.2)",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                textAlign: "center",
                gap: "0.95rem",
                position: "relative",
                overflow: "hidden",
                transition: "all 0.4s ease",
              }}
            >
              {/* Top Integrated Location & Coordinates Line */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "0.45rem",
                  fontSize: "10.5px",
                  fontFamily: "var(--mono)",
                  color: "rgba(255, 255, 255, 0.85)",
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  textShadow: "0 1px 4px rgba(0,0,0,0.6)",
                }}
              >
                <span
                  style={{
                    width: "6.5px",
                    height: "6.5px",
                    borderRadius: "50%",
                    backgroundColor: activeColor,
                    boxShadow: `0 0 8px ${activeColor}`,
                  }}
                />
                <span style={{ color: "#FFFFFF", fontWeight: 600 }}>{locationLabel}</span>
                <span style={{ opacity: 0.4 }}>/</span>
                <span>{coords}</span>
              </div>

              {/* Centerpiece: Huge Glowing AQI Number + Category Subtitle */}
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.1rem" }}>
                <h1
                  id="hero-h"
                  style={{
                    fontSize: "clamp(4.2rem, 10vw, 6.2rem)",
                    lineHeight: 0.9,
                    fontWeight: 800,
                    fontFamily: "var(--mono)",
                    letterSpacing: "-0.04em",
                    margin: "0",
                    display: "flex",
                    alignItems: "baseline",
                    justifyContent: "center",
                  }}
                >
                  <span className="sr-only">Air quality index </span>
                  {isLoading ? (
                    <Skeleton style={{ width: "14rem", height: "5.5rem", borderRadius: "14px" }} />
                  ) : (
                    <output
                      style={{
                        color: activeColor,
                        textShadow: `0 0 35px ${activeColor}80, 0 0 70px ${activeColor}40, 0 2px 10px rgba(0,0,0,0.8)`,
                      }}
                    >
                      {int(displayAqi)}
                    </output>
                  )}
                </h1>

                {/* Category Text */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.35rem",
                    color: activeColor,
                    fontSize: "12.5px",
                    fontFamily: "var(--mono)",
                    fontWeight: 800,
                    letterSpacing: "0.14em",
                    textTransform: "uppercase",
                    textShadow: `0 0 14px ${activeColor}, 0 1px 6px rgba(0,0,0,0.7)`,
                    marginTop: "0.15rem",
                  }}
                >
                  <Sparkles size={13} />
                  <span>{displayCategory}</span>
                </div>
              </div>

              {/* Telemetry Details Row */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "1rem",
                  fontSize: "11px",
                  fontFamily: "var(--mono)",
                  color: "rgba(255, 255, 255, 0.8)",
                  flexWrap: "wrap",
                  textShadow: "0 1px 4px rgba(0,0,0,0.6)",
                }}
              >
                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
                  <Wind size={12} style={{ color: activeColor }} />
                  <span>Dominant: <strong style={{ color: "#FFFFFF" }}>{dominantPollutant}</strong></span>
                </span>

                <span style={{ opacity: 0.35 }}>•</span>

                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
                  <Clock size={12} style={{ color: "rgba(255, 255, 255, 0.65)" }} />
                  <span>Valid: <strong style={{ color: "#FFFFFF" }}>{hour ? dayClock(hour.timestamp) : "Nowcast"}</strong></span>
                </span>

                <span style={{ opacity: 0.35 }}>•</span>

                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
                  <ShieldCheck size={12} style={{ color: "var(--live)" }} />
                  <span>{isLiveNow ? `${cityAggregate?.station_count ?? 43} Stations` : `${leadLabel(cursor)} (T+${cursor}h)`}</span>
                </span>
              </div>

              {/* Integrated AQI Level Spectrum Gauge */}
              <div
                style={{
                  width: "100%",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.65rem",
                  marginTop: "0.2rem",
                }}
              >
                {/* Header row */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.35rem" }}>
                    <Activity size={12} style={{ color: activeColor }} />
                    <span style={{ fontSize: "10.5px", fontFamily: "var(--mono)", letterSpacing: "0.08em", textTransform: "uppercase", color: "rgba(255, 255, 255, 0.75)", fontWeight: 600, textShadow: "0 1px 4px rgba(0,0,0,0.6)" }}>
                      CPCB AQI Scale Spectrum
                    </span>
                  </div>
                  <span
                    style={{
                      fontSize: "10.5px",
                      fontFamily: "var(--mono)",
                      color: activeColor,
                      fontWeight: 700,
                      textShadow: `0 0 8px ${activeColor}, 0 1px 4px rgba(0,0,0,0.7)`,
                    }}
                  >
                    Pointer @ {int(displayAqi)}
                  </span>
                </div>

                {/* Gauge Component */}
                <div style={{ position: "relative", width: "100%", padding: "0.85rem 0 0.35rem 0" }}>
                  {/* Category names row on top */}
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(6, 1fr)",
                      textAlign: "center",
                      fontSize: "10.5px",
                      fontFamily: "var(--mono)",
                      fontWeight: 600,
                      marginBottom: "0.55rem",
                    }}
                  >
                    {AQI_LEVELS.map((lvl) => {
                      const isCurrent = displayCategory.toLowerCase() === lvl.name.toLowerCase() ||
                        (lvl.name === "Moderate" && displayCategory.toLowerCase() === "satisfactory") ||
                        (lvl.name === "Unhealthy" && displayCategory.toLowerCase() === "poor") ||
                        (lvl.name === "Hazardous" && displayCategory.toLowerCase() === "severe");
                      return (
                        <span
                          key={lvl.name}
                          style={{
                            color: isCurrent ? lvl.color : "rgba(255, 255, 255, 0.6)",
                            fontWeight: isCurrent ? 700 : 500,
                            transform: isCurrent ? "scale(1.08)" : "scale(1)",
                            transition: "all 0.3s ease",
                            textShadow: isCurrent ? `0 0 12px ${lvl.color}, 0 1px 6px rgba(0,0,0,0.8)` : "0 1px 3px rgba(0,0,0,0.6)",
                            lineHeight: 1.2,
                          }}
                        >
                          {lvl.name}
                        </span>
                      );
                    })}
                  </div>

                  {/* Multi-segment continuous bar track */}
                  <div
                    style={{
                      position: "relative",
                      width: "100%",
                      height: "9px",
                      borderRadius: "9999px",
                      display: "flex",
                      overflow: "visible",
                      boxShadow: "inset 0 1px 2.5px rgba(0,0,0,0.5)",
                    }}
                  >
                    {AQI_LEVELS.map((lvl, idx) => (
                      <div
                        key={lvl.name}
                        style={{
                          flex: 1,
                          height: "100%",
                          backgroundColor: lvl.color,
                          borderTopLeftRadius: idx === 0 ? "9999px" : "0",
                          borderBottomLeftRadius: idx === 0 ? "9999px" : "0",
                          borderTopRightRadius: idx === AQI_LEVELS.length - 1 ? "9999px" : "0",
                          borderBottomRightRadius: idx === AQI_LEVELS.length - 1 ? "9999px" : "0",
                        }}
                      />
                    ))}

                    {/* Animated Indicator Pin / Orb */}
                    <motion.div
                      style={{
                        position: "absolute",
                        top: "50%",
                        left: `${aqiToScalePercent(displayAqi)}%`,
                        transform: "translate(-50%, -50%)",
                        pointerEvents: "none",
                        zIndex: 10,
                      }}
                      animate={{
                        left: `${aqiToScalePercent(displayAqi)}%`,
                      }}
                      transition={{
                        type: "spring",
                        stiffness: 240,
                        damping: 26,
                      }}
                    >
                      {/* Floating Current AQI Value Badge */}
                      <div
                        style={{
                          position: "absolute",
                          bottom: "15px",
                          left: "50%",
                          transform: "translateX(-50%)",
                          padding: "0.15rem 0.5rem",
                          borderRadius: "4px",
                          fontSize: "10.5px",
                          fontFamily: "var(--mono)",
                          fontWeight: 800,
                          color: "#000",
                          backgroundColor: activeColor,
                          boxShadow: `0 0 16px ${activeColor}`,
                          whiteSpace: "nowrap",
                        }}
                      >
                        {int(displayAqi)}
                      </div>

                      {/* Pulsing Target Ring & Solid Center Pin */}
                      <div
                        style={{
                          width: "20px",
                          height: "20px",
                          borderRadius: "50%",
                          backgroundColor: "#FFFFFF",
                          border: `3.5px solid ${activeColor}`,
                          boxShadow: `0 0 14px ${activeColor}, 0 0 26px ${activeColor}`,
                          position: "relative",
                        }}
                      >
                        <div
                          className="animate-ping"
                          style={{
                            position: "absolute",
                            inset: "-4px",
                            borderRadius: "50%",
                            border: `2px solid ${activeColor}`,
                            opacity: 0.8,
                          }}
                        />
                      </div>
                    </motion.div>
                  </div>

                  {/* Ticks & Numbers row below */}
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: "9.5px",
                      fontFamily: "var(--mono)",
                      color: "rgba(255, 255, 255, 0.6)",
                      marginTop: "0.65rem",
                      padding: "0 2px",
                      textShadow: "0 1px 3px rgba(0,0,0,0.6)",
                    }}
                  >
                    <span>0</span>
                    <span>50</span>
                    <span>100</span>
                    <span>150</span>
                    <span>200</span>
                    <span>300</span>
                    <span>301+</span>
                  </div>
                </div>

                {/* Health & Advisory Footnote */}
                <div
                  style={{
                    fontSize: "10.5px",
                    color: "rgba(255, 255, 255, 0.85)",
                    lineHeight: 1.4,
                    display: "flex",
                    alignItems: "flex-start",
                    gap: "0.4rem",
                    textAlign: "left",
                    marginTop: "0.1rem",
                    textShadow: "0 1px 4px rgba(0,0,0,0.7)",
                  }}
                >
                  <AlertCircle size={13} style={{ color: activeColor, flexShrink: 0, marginTop: "1px" }} />
                  <span>
                    {displayAqi <= 50
                      ? "Good — Ideal air quality for all outdoor activities and exercise."
                      : displayAqi <= 100
                      ? "Moderate — Minor breathing discomfort to sensitive individuals with respiratory ailments."
                      : displayAqi <= 200
                      ? "Poor — Breathing discomfort to people with asthma, lung, and heart disease."
                      : displayAqi <= 300
                      ? "Unhealthy — Breathing discomfort to most people on prolonged outdoor exposure."
                      : displayAqi <= 400
                      ? "Severe — High risk of respiratory illness on prolonged exposure. Avoid outdoor activities."
                      : "Hazardous — Emergency health conditions. Severe pulmonary and cardiovascular impact across entire population."}
                  </span>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── 5. Permanently Docked Liquid-Glass Navigation Bar on the Front Hero Page ── */}
      {onPageChange && (
        <div
          style={{
            position: "absolute",
            bottom: "1.5rem",
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 20,
            pointerEvents: "auto",
            maxWidth: "calc(100vw - 2rem)",
          }}
        >
          <div
            className="liquid-glass"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.3rem",
              padding: "0.35rem 0.45rem",
              borderRadius: "9999px",
              background: "rgba(12, 16, 26, 0.65)",
              backdropFilter: "blur(24px) saturate(180%)",
              WebkitBackdropFilter: "blur(24px) saturate(180%)",
              border: "1px solid rgba(255, 255, 255, 0.24)",
              boxShadow: "0 16px 48px rgba(0, 0, 0, 0.6), inset 0 1px 1.5px rgba(255, 255, 255, 0.35)",
              overflowX: "auto",
              maxWidth: "100%",
            }}
          >
            {[
              { id: "overview", label: "Overview", icon: Layers },
              { id: "forecast-datas", label: "Forecast", icon: BarChart3 },
              { id: "historic-data", label: "Historic", icon: History },
              { id: "atmospheric-dynamics", label: "Atmosphere", icon: CloudRain },
              { id: "exposure-tracker", label: "Exposure", icon: HeartPulse },
              { id: "health-assistant", label: "Health Assistant", icon: Bot },
            ].map((btn) => {
              const isActive = currentPage === btn.id;
              const Icon = btn.icon;
              return (
                <button
                  key={btn.id}
                  type="button"
                  onClick={() => onPageChange(btn.id as PageType)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.38rem",
                    padding: "0.38rem 0.85rem",
                    borderRadius: "9999px",
                    background: isActive ? "rgba(255, 255, 255, 0.2)" : "transparent",
                    border: `1px solid ${isActive ? "rgba(255, 255, 255, 0.38)" : "transparent"}`,
                    boxShadow: isActive
                      ? "0 2px 10px rgba(0, 0, 0, 0.3), inset 0 1px 1px rgba(255, 255, 255, 0.35)"
                      : "none",
                    color: isActive ? "#FFFFFF" : "rgba(255, 255, 255, 0.75)",
                    fontFamily: "var(--mono)",
                    fontSize: "12px",
                    fontWeight: isActive ? 600 : 400,
                    cursor: "pointer",
                    transition: "all 0.25s cubic-bezier(0.16, 1, 0.3, 1)",
                    whiteSpace: "nowrap",
                    outline: "none",
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) {
                      e.currentTarget.style.color = "#FFFFFF";
                      e.currentTarget.style.background = "rgba(255, 255, 255, 0.08)";
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) {
                      e.currentTarget.style.color = "rgba(255, 255, 255, 0.75)";
                      e.currentTarget.style.background = "transparent";
                    }
                  }}
                >
                  <Icon
                    size={13.5}
                    style={{
                      color: isActive ? "var(--live)" : "rgba(255, 255, 255, 0.6)",
                      transition: "color 0.25s ease",
                    }}
                  />
                  <span>{btn.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
"""

with open("webapp/src/components/Hero.tsx", "w", encoding="utf-8") as f:
    f.write(hero_code)

# 3. Update App.tsx to pass currentPage and onPageChange to Hero
with open("webapp/src/App.tsx", "r", encoding="utf-8") as f:
    app_content = f.read()

app_content = app_content.replace(
    'ready={data.ready}\n            />',
    'ready={data.ready}\n              currentPage={currentPage}\n              onPageChange={handlePageChange}\n            />'
)

with open("webapp/src/App.tsx", "w", encoding="utf-8") as f:
    f.write(app_content)

print("Dock and top theme switcher centering applied successfully!")
