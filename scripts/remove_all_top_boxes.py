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
      <header
        className="rail"
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0.85rem clamp(1rem, 3vw, 2.5rem)",
          background: "transparent",
          border: "none",
          boxShadow: "none",
          zIndex: 40,
        }}
      >
        {/* Left: Brand & Menu (Zero Dark Background) */}
        <div style={{ display: "flex", alignItems: "center", gap: "1.2rem", zIndex: 10 }}>
          {/* Transparent Menu Button */}
          <button
            type="button"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.4rem",
              padding: "0.35rem 0.7rem",
              background: "transparent",
              border: "1px solid rgba(255, 255, 255, 0.25)",
              borderRadius: "4px",
              color: "#FFFFFF",
              fontFamily: "var(--mono)",
              fontSize: "11.5px",
              fontWeight: 500,
              cursor: "pointer",
              transition: "all 0.2s ease",
              textShadow: "0 1px 4px rgba(0,0,0,0.8)",
            }}
            onClick={() => setMenuOpen(!menuOpen)}
            aria-expanded={menuOpen}
            aria-label="Navigation Menu"
          >
            {menuOpen ? <X size={14} /> : <Menu size={14} />}
            <span>Menu</span>
          </button>

          <div
            className="rail__brand"
            style={{ cursor: "pointer", display: "flex", alignItems: "baseline", gap: "0.5rem" }}
            onClick={() => handleSelectPage("overview")}
            title="Return to Main Overview Console"
          >
            <span
              style={{
                width: "8px",
                height: "8px",
                backgroundColor: "var(--live)",
                borderRadius: "1px",
                transform: "rotate(45deg)",
                boxShadow: "0 0 10px var(--live)",
                alignSelf: "center",
              }}
              aria-hidden="true"
            />
            <span style={{ fontFamily: "var(--mono)", fontWeight: 700, fontSize: "14px", color: "#FFFFFF", letterSpacing: "0.06em", textShadow: "0 1px 4px rgba(0,0,0,0.8)" }}>
              NCR<span style={{ color: "var(--live)" }}>·</span>72
            </span>
            <span style={{ fontFamily: "var(--mono)", fontSize: "10.5px", color: "rgba(255, 255, 255, 0.55)", letterSpacing: "0.15em", textTransform: "uppercase" }}>
              coupled aqi forecast
            </span>
          </div>
        </div>

        {/* Center: EXACT 100% Dead-Centered Clean Text Switcher (ZERO Background Boxes) */}
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
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "1.4rem",
                background: "transparent",
                border: "none",
                boxShadow: "none",
                padding: "0",
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
                      padding: "0.2rem 0",
                      background: "transparent",
                      border: "none",
                      borderBottom: isActive ? "2px solid #FFFFFF" : "2px solid transparent",
                      borderRadius: "0",
                      boxShadow: "none",
                      fontSize: "12px",
                      fontFamily: "var(--mono)",
                      fontWeight: isActive ? 700 : 400,
                      color: isActive ? "#FFFFFF" : "rgba(255, 255, 255, 0.55)",
                      cursor: "pointer",
                      transition: "all 0.2s ease",
                      outline: "none",
                      whiteSpace: "nowrap",
                      textShadow: isActive
                        ? "0 0 12px rgba(255,255,255,0.7), 0 1px 4px rgba(0,0,0,0.9)"
                        : "0 1px 4px rgba(0,0,0,0.8)",
                    }}
                  >
                    {v.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Right: Timestamp & Refresh (Pushed fully to right, Zero Dark Box) */}
        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
            gap: "1.1rem",
            zIndex: 10,
          }}
        >
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: "11px",
              color: "rgba(255, 255, 255, 0.6)",
              fontVariantNumeric: "tabular-nums",
              whiteSpace: "nowrap",
              textShadow: "0 1px 4px rgba(0,0,0,0.8)",
            }}
          >
            {stamp}
          </span>
          <button
            type="button"
            onClick={onRefresh}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.4rem",
              padding: "0.35rem 0.7rem",
              background: "transparent",
              border: "1px solid rgba(255, 255, 255, 0.25)",
              borderRadius: "4px",
              color: "#FFFFFF",
              fontFamily: "var(--mono)",
              fontSize: "11.5px",
              fontWeight: 500,
              cursor: "pointer",
              transition: "all 0.2s ease",
              textShadow: "0 1px 4px rgba(0,0,0,0.8)",
            }}
          >
            <RotateCw size={12} aria-hidden="true" />
            <span>Refresh</span>
          </button>
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

print("Rail.tsx updated with 100% clean, transparent typography and zero background boxes!")
