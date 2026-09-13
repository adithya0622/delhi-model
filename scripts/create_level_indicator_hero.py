hero_code = r"""import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Activity, AlertCircle, Sparkles } from "lucide-react";
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

interface HeroProps {
  forecast: Panel<ForecastResponse>;
  hour: HourlyForecast | null;
  cursor: number;
  consensus?: ConsensusResponse | null;
  cityAggregate?: CityAggregateResponse | null;
}

interface HeroVideoConfig {
  id: string;
  label: string;
  url: string;
}

const HERO_VIDEOS: readonly HeroVideoConfig[] = [
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
    return 83.33 + Math.min(1, (aqi - 400) / 100) * 15.0;
  }
}

export function Hero({ forecast, hour, cursor, consensus, cityAggregate }: HeroProps) {
  const [activeVideo, setActiveVideo] = useState<number>(0);
  const [isTransitioning, setIsTransitioning] = useState<boolean>(false);
  const videoRefs = useRef<(HTMLVideoElement | null)[]>([]);

  // Video switching handler with 1000ms transition cooldown
  const handleVideoSwitch = (index: number) => {
    if (index === activeVideo || isTransitioning) return;
    setIsTransitioning(true);
    setActiveVideo(index);
    setTimeout(() => {
      setIsTransitioning(false);
    }, 1000);
  };

  // Autoplay all looping video elements
  useEffect(() => {
    videoRefs.current.forEach((video) => {
      if (!video) return;
      video.muted = true;
      video.defaultMuted = true;
      const playPromise = video.play();
      if (playPromise !== undefined) {
        playPromise.catch(() => {
          const onInteract = () => {
            video.play().catch(() => {});
            window.removeEventListener("click", onInteract);
            window.removeEventListener("scroll", onInteract);
          };
          window.addEventListener("click", onInteract, { once: true });
          window.addEventListener("scroll", onInteract, { once: true });
        });
      }
    });
  }, []);

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
    ? (cityAggregate?.location_label ?? "DELHI NCR / CITY AGGREGATE (43 STATIONS)")
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
        justifyContent: "flex-end",
        paddingTop: "4.5rem",
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

      {/* ── 3. Subtle Vignette Scrim (Z -1) ── */}
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          inset: 0,
          zIndex: -1,
          background: "radial-gradient(ellipse at center, rgba(0,0,0,0.1) 0%, rgba(0,0,0,0.5) 100%)",
          pointerEvents: "none",
        }}
      />

      {/* ── 4. Floating Cinematic Video Theme Switcher Pill ── */}
      <div
        style={{
          position: "absolute",
          top: "5rem",
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 10,
        }}
      >
        <div
          className="liquid-glass"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.4rem",
            padding: "0.35rem 0.5rem",
            borderRadius: "9999px",
            boxShadow: "0 8px 32px rgba(0,0,0,0.35)",
          }}
        >
          {HERO_VIDEOS.map((v, i) => {
            const isActive = activeVideo === i;
            return (
              <button
                key={v.id}
                type="button"
                onClick={() => handleVideoSwitch(i)}
                disabled={isTransitioning}
                style={{
                  padding: "0.35rem 0.75rem",
                  borderRadius: "9999px",
                  fontSize: "11px",
                  fontFamily: "var(--mono)",
                  fontWeight: isActive ? 600 : 400,
                  color: isActive ? "var(--bone)" : "var(--mist)",
                  background: isActive ? "rgba(255, 255, 255, 0.18)" : "transparent",
                  border: `1px solid ${isActive ? "rgba(255, 255, 255, 0.3)" : "transparent"}`,
                  cursor: "pointer",
                  transition: "all 0.25s ease",
                  outline: "none",
                }}
              >
                {v.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── 5. Main Air Quality Hero Content ── */}
      <motion.div
        style={{ width: "100%" }}
        initial={{ opacity: 0, y: 40 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1], delay: 0.15 }}
      >
        <section className="hero" aria-labelledby="hero-h" style={{ alignItems: "center", gap: "2.5rem" }}>
          {/* Left AQI Headline & Meta */}
          <div className="hero__left">
            <p className="eyebrow" style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
              {isLiveNow && (
                <span
                  style={{
                    display: "inline-block",
                    width: "8px",
                    height: "8px",
                    borderRadius: "50%",
                    backgroundColor: activeColor,
                    boxShadow: `0 0 8px ${activeColor}`,
                  }}
                  title="Live 43-Station Network Aggregate"
                />
              )}
              <span>{locationLabel}</span>
              <span className="eyebrow__sep" aria-hidden="true">
                /
              </span>
              <span>{coords}</span>
            </p>

            <h1 className="hero__h" id="hero-h">
              <span className="sr-only">Air quality index </span>
              {isLoading ? (
                <Skeleton style={{ width: "clamp(9rem,28vw,20rem)", height: "clamp(5rem,15vw,12rem)" }} />
              ) : (
                <output className="hero__num" style={{ color: activeColor }}>
                  {int(displayAqi)}
                </output>
              )}
            </h1>

            <p className="hero__cat" style={{ color: activeColor }}>
              {displayCategory}
            </p>

            <dl className="hero__meta">
              <div className="hero__metaItem">
                <dt>dominant</dt>
                <dd style={{ color: activeColor, fontWeight: 700 }}>{dominantPollutant}</dd>
              </div>

              <div className="hero__metaItem">
                <dt>valid</dt>
                <dd>{hour ? dayClock(hour.timestamp) : "—"}</dd>
              </div>

              <div className="hero__metaItem">
                <dt>scope</dt>
                <dd>
                  {isLiveNow ? (
                    `${cityAggregate?.station_count ?? 43} Stations`
                  ) : (
                    <span>
                      {leadLabel(cursor)} <span style={{ opacity: 0.65 }}>(T+{cursor}h)</span>
                    </span>
                  )}
                </dd>
              </div>
            </dl>
          </div>

          {/* Right: Animated Liquid Glass AQI Level Indicator Gauge */}
          <div
            className="liquid-glass"
            style={{
              flex: "1 1 440px",
              maxWidth: "580px",
              padding: "1.4rem 1.6rem",
              borderRadius: "16px",
              boxShadow: `0 16px 40px rgba(0,0,0,0.45), 0 0 24px -4px ${activeColor}25, inset 0 1px 1px rgba(255,255,255,0.2)`,
              backdropFilter: "blur(16px)",
              WebkitBackdropFilter: "blur(16px)",
              background: `linear-gradient(145deg, ${activeColor}15 0%, rgba(10, 14, 22, 0.9) 45%, ${activeColor}10 100%)`,
              border: `1px solid ${activeColor}55`,
              display: "flex",
              flexDirection: "column",
              gap: "1.1rem",
              transition: "all 0.4s ease",
            }}
          >
            {/* Header info row */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.5rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <Activity size={14} style={{ color: activeColor }} />
                <span style={{ fontSize: "11px", fontFamily: "var(--mono)", letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--bone)", fontWeight: 600 }}>
                  AQI Level Indicator
                </span>
              </div>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.35rem",
                  fontSize: "11px",
                  fontFamily: "var(--mono)",
                  fontWeight: 700,
                  padding: "0.22rem 0.65rem",
                  borderRadius: "9999px",
                  backgroundColor: `${activeColor}25`,
                  border: `1px solid ${activeColor}80`,
                  color: activeColor,
                  boxShadow: `0 0 12px ${activeColor}35`,
                }}
              >
                <Sparkles size={11} />
                <span>Level: {displayCategory}</span>
              </div>
            </div>

            {/* Gauge Component (Categories above + Multi-segment track + Animated Pin + Numbers below) */}
            <div style={{ position: "relative", width: "100%", padding: "1.2rem 0 0.6rem 0" }}>
              {/* Category names row on top */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(6, 1fr)",
                  textAlign: "center",
                  fontSize: "11px",
                  fontFamily: "var(--mono)",
                  fontWeight: 600,
                  marginBottom: "0.75rem",
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
                        color: isCurrent ? lvl.color : "rgba(255, 255, 255, 0.55)",
                        fontWeight: isCurrent ? 700 : 500,
                        transform: isCurrent ? "scale(1.08)" : "scale(1)",
                        transition: "all 0.3s ease",
                        textShadow: isCurrent ? `0 0 10px ${lvl.color}` : "none",
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
                  height: "10px",
                  borderRadius: "9999px",
                  display: "flex",
                  overflow: "visible",
                  boxShadow: "inset 0 1px 3px rgba(0,0,0,0.6)",
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
                      bottom: "16px",
                      left: "50%",
                      transform: "translateX(-50%)",
                      padding: "0.15rem 0.5rem",
                      borderRadius: "4px",
                      fontSize: "11px",
                      fontFamily: "var(--mono)",
                      fontWeight: 800,
                      color: "#000",
                      backgroundColor: activeColor,
                      boxShadow: `0 0 14px ${activeColor}`,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {int(displayAqi)}
                  </div>

                  {/* Pulsing Target Ring & Solid Center Pin */}
                  <div
                    style={{
                      width: "22px",
                      height: "22px",
                      borderRadius: "50%",
                      backgroundColor: "#FFFFFF",
                      border: `4px solid ${activeColor}`,
                      boxShadow: `0 0 16px ${activeColor}, 0 0 30px ${activeColor}`,
                      position: "relative",
                    }}
                  >
                    <div
                      className="animate-ping"
                      style={{
                        position: "absolute",
                        inset: "-5px",
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
                  fontSize: "10px",
                  fontFamily: "var(--mono)",
                  color: "rgba(255, 255, 255, 0.5)",
                  marginTop: "0.75rem",
                  padding: "0 2px",
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
                fontSize: "11px",
                color: "var(--mist)",
                lineHeight: 1.45,
                padding: "0.55rem 0.75rem",
                borderRadius: "8px",
                background: "rgba(255, 255, 255, 0.03)",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                display: "flex",
                alignItems: "flex-start",
                gap: "0.4rem",
              }}
            >
              <AlertCircle size={14} style={{ color: activeColor, flexShrink: 0, marginTop: "1px" }} />
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
        </section>
      </motion.div>
    </div>
  );
}
"""

with open("webapp/src/components/Hero.tsx", "w", encoding="utf-8") as f:
    f.write(hero_code)

print("Hero.tsx successfully updated with animated AQI level spectrum indicator!")
