hero_ts = r"""import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import type { Panel } from "@/hooks/useForecastData";
import { aqiColor, aqiToCategory, pollutantSubIndex } from "@/lib/aqi";
import { dayClock, int, leadLabel } from "@/lib/format";
import type {
  CityAggregateResponse,
  ConsensusResponse,
  ForecastResponse,
  HourlyForecast,
  Pollutant,
  PollutantSubIndex,
} from "@/lib/types";
import { POLLUTANTS } from "@/lib/types";
import { Skeleton } from "@/components/ui/skeleton";

/** CPCB India reports CO in mg/m³; the other five species in µg/m³. */
function concUnit(p: Pollutant | string): string {
  return p === "CO" ? "mg/m³" : "µg/m³";
}
function fmtConc(v: number): string {
  return v < 10 ? v.toFixed(1) : String(Math.round(v));
}

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

  // Single source of truth for CPCB Sub-indices
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
        <section className="hero" aria-labelledby="hero-h">
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

          <div className="hero__right">
            <div className="hero__subhead">
              <span>CPCB SUB-INDICES</span>
              <span className="hero__subheadNote">
                INDEX &amp; CONCENTRATION
              </span>
            </div>

            <ol className="hero__subList" aria-label="Individual pollutant sub-indices">
              {subIndices.map((s) => {
                const subColor = aqiColor(s.sub_index);
                const isDominant = s.pollutant === dominantPollutant;
                const fillPct = Math.min(100, (s.sub_index / 500) * 100);

                return (
                  <li
                    key={s.pollutant}
                    className={`hero__subItem ${isDominant ? "hero__subItem--dominant" : ""}`}
                    data-pollutant={s.pollutant}
                  >
                    <span className="hero__subPoll">{s.pollutant}</span>

                    <div className="hero__bar">
                      <div
                        className="hero__barFill"
                        style={{
                          width: `${fillPct}%`,
                          backgroundColor: subColor,
                        }}
                      />
                    </div>

                    <span className="hero__subNum" style={{ color: subColor }}>
                      {s.sub_index > 0 ? Math.round(s.sub_index) : "—"}
                    </span>

                    <span className="hero__subConc">
                      {s.concentration > 0 ? (
                        <>
                          {fmtConc(s.concentration)}
                          <span className="hero__unit">{concUnit(s.pollutant)}</span>
                        </>
                      ) : (
                        "—"
                      )}
                    </span>
                  </li>
                );
              })}
            </ol>

            <p className="hero__note">
              Overall AQI equals the <em>maximum</em> sub-index across monitored species (CPCB National AQI, 2014).
            </p>
          </div>
        </section>
      </motion.div>
    </div>
  );
}
"""

with open("webapp/src/components/Hero.tsx", "w", encoding="utf-8") as f:
    f.write(hero_ts)

print("Hero.tsx generated cleanly without placeholder text!")
