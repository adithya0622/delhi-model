hero_code = r"""import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Activity, AlertCircle, Sparkles, Wind, Clock, ShieldCheck } from "lucide-react";
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
}: HeroProps) {
  const videoRefs = useRef<(HTMLVideoElement | null)[]>([]);

  // Intro fold animation state with robust timer refs
  const [showIntro, setShowIntro] = useState<boolean>(true);
  const [introFading, setIntroFading] = useState<boolean>(false);
  const holdTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clear timers on unmount
  useEffect(() => {
    return () => {
      if (holdTimerRef.current) clearTimeout(holdTimerRef.current);
      if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current);
    };
  }, []);

  // Stable callback when GSAP timeline finishes unfolding all 27 characters
  const handleIntroComplete = useCallback(() => {
    if (holdTimerRef.current) clearTimeout(holdTimerRef.current);
    // Hold full text for 1.3 seconds so user can read "Lets Decode The Atmosphere"
    holdTimerRef.current = setTimeout(() => {
      setIntroFading(true);
      if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current);
      fadeTimerRef.current = setTimeout(() => {
        setShowIntro(false);
      }, 700);
    }, 1300);
  }, []);

  const handleSkipIntro = useCallback(() => {
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
            initial={{ opacity: 0, scale: 0.92, y: 15 }}
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
              }}
            >
              <FoldText
                text="Lets Decode The Atmosphere"
                splitBy="char"
                hinge="top"
                trigger="mount"
                duration={0.7}
                stagger={0.04}
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
            </div>

            <motion.span
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: introFading ? 0 : 0.75, y: 0 }}
              transition={{ delay: 1.2, duration: 0.6 }}
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
    </div>
  );
}
"""

with open("webapp/src/components/Hero.tsx", "w", encoding="utf-8") as f:
    f.write(hero_code)

print("Hero.tsx generated with bulletproof intro lifecycle management!")
