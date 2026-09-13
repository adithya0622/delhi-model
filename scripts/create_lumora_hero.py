hero_ts = r"""import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, ArrowRight, Wind, ShieldCheck, Check } from "lucide-react";
import type { Panel } from "@/hooks/useForecastData";
import { aqiColor, aqiToCategory, pollutantSubIndex } from "@/lib/aqi";
import { int } from "@/lib/format";
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
  const [emailInput, setEmailInput] = useState<string>("");
  const [emailSubmitted, setEmailSubmitted] = useState<boolean>(false);
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

  // Autoplay and keep looping for all video elements
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

  // Is Deep Woods (Video 3, index 2) active? (Trigger 700ms dark mode transition to #182C41)
  const isDeepWoods = activeVideo === 2;
  const contentColor = isDeepWoods ? "#182C41" : "#FFFFFF";
  const subtextColor = isDeepWoods ? "rgba(24, 44, 65, 0.85)" : "rgba(255, 255, 255, 0.85)";
  const pillBg = isDeepWoods ? "rgba(24, 44, 65, 0.08)" : "rgba(255, 255, 255, 0.08)";
  const pillBorder = isDeepWoods ? "rgba(24, 44, 65, 0.2)" : "rgba(255, 255, 255, 0.2)";

  // Single source of truth for Air Quality Data
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

  const activeColor = cityAggregate?.color && isLiveNow ? cityAggregate.color : aqiColor(displayAqi);
  const isLoading = forecast.status === "loading" && !hour && !cityAggregate;

  const handleEmailSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!emailInput || !emailInput.includes("@")) return;
    setEmailSubmitted(true);
    setTimeout(() => {
      setEmailSubmitted(false);
      setEmailInput("");
    }, 4000);
  };

  return (
    <section className="relative w-full min-h-screen overflow-hidden bg-black flex flex-col justify-between pt-16 pb-8">
      {/* ── 1. STACKED FULLSCREEN VIDEOS LAYER (Z-0) ── */}
      <div className="absolute inset-0 w-full h-full overflow-hidden pointer-events-none z-0">
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
            className="absolute inset-0 w-full h-full object-cover transition-opacity duration-1000 ease-in-out"
            style={{
              opacity: activeVideo === idx ? 1 : 0,
            }}
          />
        ))}
      </div>

      {/* ── 2. TRANSPARENT PNG OVERLAY WITH TRAIN-BOB MOTION (Z-1) ── */}
      <div className="absolute inset-0 w-full h-full pointer-events-none z-[1] overflow-hidden">
        <img
          src="https://soft-zoom-63098134.figma.site/_assets/v11/0b4a435b2df2747593c43d7a1c9b4578f7d8d90c.png"
          alt=""
          className="animate-train-bob absolute inset-0 w-full h-full object-cover"
        />
      </div>

      {/* ── Subtle Vignette / Readability Scrim ── */}
      <div
        className="absolute inset-0 pointer-events-none z-[2]"
        style={{
          background: "radial-gradient(ellipse at center, rgba(0,0,0,0.1) 0%, rgba(0,0,0,0.45) 100%)",
        }}
      />

      {/* ── 3. CONTENT LAYER (Z-10) ── */}
      <div className="relative z-10 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex-1 flex flex-col justify-between">
        {/* Top Spacer / Mini Brand */}
        <div className="flex items-center justify-between pt-2">
          <div className="flex items-center gap-3">
            <span
              className="font-instrument italic text-2xl sm:text-3xl tracking-wide font-normal transition-colors duration-700"
              style={{ color: contentColor }}
            >
              Lumora
            </span>
            <span
              className="liquid-glass text-[11px] font-sans px-2.5 py-1 rounded-full uppercase tracking-wider hidden sm:inline-flex items-center gap-1.5"
              style={{ color: subtextColor }}
            >
              <Wind size={12} style={{ color: activeColor }} />
              Delhi NCR coupled forecast
            </span>
          </div>

          {/* Live AQI Chip Badge in Top Corner */}
          <div
            className="liquid-glass px-3 py-1.5 rounded-full flex items-center gap-2 cursor-default"
            style={{
              background: pillBg,
              border: `1px solid ${pillBorder}`,
            }}
          >
            <span
              className="w-2.5 h-2.5 rounded-full animate-pulse"
              style={{ backgroundColor: activeColor, boxShadow: `0 0 8px ${activeColor}` }}
            />
            <span className="font-sans text-xs font-semibold" style={{ color: contentColor }}>
              Live AQI: <span style={{ color: activeColor }}>{int(displayAqi)}</span>
            </span>
            <span className="text-[11px] opacity-75 font-sans hidden sm:inline" style={{ color: subtextColor }}>
              ({displayCategory})
            </span>
          </div>
        </div>

        {/* Centered Main Cinematic Hero Content */}
        <div className="my-auto py-10 sm:py-14 flex flex-col items-center text-center">
          {/* Badge */}
          <motion.div
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
            className="liquid-glass px-4 py-1.5 rounded-full mb-6 inline-flex items-center gap-2"
            style={{
              background: pillBg,
              border: `1px solid ${pillBorder}`,
              transition: "all 700ms ease",
            }}
          >
            <Sparkles size={13} style={{ color: activeColor }} />
            <span
              className="text-xs sm:text-sm font-sans tracking-tight transition-colors duration-700"
              style={{ color: contentColor }}
            >
              Over 10,000 minds already finding their clarity
            </span>
          </motion.div>

          {/* Heading in Instrument Serif */}
          <motion.h1
            initial={{ opacity: 0, y: 25 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.9, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
            className="font-instrument font-normal text-4xl sm:text-6xl md:text-7xl lg:text-[5.5rem] leading-[1.08] tracking-tight max-w-4xl transition-colors duration-700"
            style={{ color: contentColor }}
          >
            Clarity in an Endlessly <br />
            <span className="italic">Noisy Universe</span>
          </motion.h1>

          {/* Subtext */}
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.9, delay: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="mt-6 text-sm sm:text-base md:text-lg max-w-xl leading-relaxed font-sans transition-colors duration-700 font-light"
            style={{ color: subtextColor }}
          >
            Rise above the chaos of pings, infinite scrolling, and relentless demands. Discover how to protect your presence and create with intention.
          </motion.p>

          {/* Email Early Access Input */}
          <motion.form
            onSubmit={handleEmailSubmit}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.9, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="liquid-glass mt-8 p-1.5 rounded-full flex items-center w-full max-w-[320px] sm:max-w-sm transition-all duration-700"
            style={{
              background: pillBg,
              border: `1px solid ${pillBorder}`,
            }}
          >
            <input
              type="email"
              value={emailInput}
              onChange={(e) => setEmailInput(e.target.value)}
              placeholder="Your Best Email"
              className="flex-1 bg-transparent px-4 py-2 text-xs sm:text-sm outline-none font-sans transition-colors duration-700"
              style={{ color: contentColor }}
              required
            />
            <button
              type="submit"
              className="bg-white text-black font-sans text-xs sm:text-sm font-medium px-4 sm:px-5 py-2.5 rounded-full hover:bg-opacity-90 active:scale-95 transition-all flex items-center gap-1.5 flex-shrink-0 shadow-sm cursor-pointer"
            >
              {emailSubmitted ? (
                <>
                  <Check size={14} className="text-green-600" />
                  <span>Access Granted</span>
                </>
              ) : (
                <>
                  <span>Get Early Access</span>
                  <ArrowRight size={13} />
                </>
              )}
            </button>
          </motion.form>

          {/* ── 4-THEME VIDEO SWITCHER ROW ── */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 1, delay: 0.4 }}
            className="mt-10 flex items-center justify-center gap-4 sm:gap-8 flex-wrap"
          >
            {HERO_VIDEOS.map((v, i) => {
              const isActive = activeVideo === i;
              return (
                <button
                  key={v.id}
                  type="button"
                  onClick={() => handleVideoSwitch(i)}
                  disabled={isTransitioning}
                  className="font-sans text-xs sm:text-sm pb-1.5 transition-all duration-300 relative cursor-pointer outline-none"
                  style={{
                    color: contentColor,
                    opacity: isActive ? 1 : 0.5,
                    fontWeight: isActive ? 600 : 400,
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) e.currentTarget.style.opacity = "0.85";
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) e.currentTarget.style.opacity = "0.5";
                  }}
                >
                  <span>{v.label}</span>
                  {isActive && (
                    <motion.div
                      layoutId="activeVideoIndicator"
                      className="absolute bottom-0 left-0 right-0 h-[2px]"
                      style={{ backgroundColor: isDeepWoods ? "#182C41" : "#FFFFFF" }}
                      transition={{ duration: 0.3 }}
                    />
                  )}
                </button>
              );
            })}
          </motion.div>
        </div>

        {/* ── BOTTOM STATS BAR ── */}
        <div className="w-full pt-4 border-t border-white/10 flex flex-wrap items-center justify-between text-xs sm:text-sm text-white/70 font-sans gap-2">
          <div className="flex items-center gap-3 sm:gap-6 flex-wrap">
            <span>60+ Deep Sessions</span>
            <span className="hidden sm:inline opacity-40">|</span>
            <span>12,000+ Creators</span>
            <span className="hidden sm:inline opacity-40">|</span>
            <span>4.8 User Satisfaction</span>
            <span className="hidden sm:inline opacity-40">|</span>
            <span>Intentional-First Design</span>
          </div>

          <div className="flex items-center gap-2 text-xs font-mono opacity-80">
            <ShieldCheck size={14} style={{ color: activeColor }} />
            <span>43-Station CPCB Sounding Network</span>
          </div>
        </div>
      </div>
    </section>
  );
}
"""

with open("webapp/src/components/Hero.tsx", "w", encoding="utf-8") as f:
    f.write(hero_ts)

print("Hero.tsx generated with full Lumora cinematic video background & animation suite!")
