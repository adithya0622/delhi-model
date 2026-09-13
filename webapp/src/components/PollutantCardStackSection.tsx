import * as React from "react";
import { CardStack, type CardStackItem } from "@/components/ui/card-stack";
import { aqiColor, aqiToCategory, pollutantSubIndex } from "@/lib/aqi";
import type { CityAggregateResponse, ConsensusResponse, HourlyForecast } from "@/lib/types";
import type { WeatherapiRealtimeResponse, IqairRealtimeResponse } from "@/lib/api";
import { Sparkles, Wind, Layers, Activity, AlertTriangle } from "lucide-react";
import { useTranslation } from "@/i18n";

interface PollutantCardItem extends CardStackItem {
  species: string;
  chemicalFormula: string;
  concentration: number;
  unit: string;
  subIndex: number;
  category: string;
  color: string;
  standard24h: number;
  sources: string;
  healthEffect: string;
}

interface PollutantCardStackSectionProps {
  cityAggregate?: CityAggregateResponse | null;
  consensus?: ConsensusResponse | null;
  hour?: HourlyForecast | null;
  cursor?: number;
  weatherapi?: WeatherapiRealtimeResponse | null;
  realtimeIqair?: IqairRealtimeResponse | null;
}

export function PollutantCardStackSection({
  cityAggregate,
  consensus,
  hour,
  cursor = 0,
  weatherapi,
  realtimeIqair,
}: PollutantCardStackSectionProps) {
  const { t } = useTranslation();
  // Extract live metrics for all 6 CPCB pollutant species
  const items: PollutantCardItem[] = React.useMemo(() => {
    const isLive = cursor === 0;
    const subIndices = cityAggregate?.sub_indices;
    const m = consensus?.metrics;
    const hourSubs = hour?.sub_indices;
    const wAq = weatherapi?.air_quality;

    const getHourConc = (species: string, fallback: number) => {
      const found = hourSubs?.find((s) => s.pollutant === species);
      return found?.concentration ?? fallback;
    };

    // PM2.5
    const livePm25 = wAq?.pm2_5 ?? (realtimeIqair?.pm25 ?? (subIndices?.["PM2.5"]?.conc ?? (m?.pm25 ?? 90.0)));
    const pm25Conc = isLive ? livePm25 : getHourConc("PM2.5", livePm25);
    const pm25Idx = pollutantSubIndex("PM2.5", pm25Conc);
    const pm25Cat = aqiToCategory(pm25Idx);

    // PM10 (Grounded in WeatherAPI live measurement)
    const rawPm10 = wAq?.pm10 ?? (realtimeIqair?.pm10 ?? (subIndices?.["PM10"]?.conc ?? (m?.pm10 ?? Math.round(pm25Conc * 1.8))));
    const livePm10 = rawPm10 > 300 ? Math.round(pm25Conc * 1.8) : rawPm10;
    const pm10Conc = isLive ? livePm10 : getHourConc("PM10", livePm10);
    const pm10Idx = pollutantSubIndex("PM10", pm10Conc);
    const pm10Cat = aqiToCategory(pm10Idx);

    // NO2
    const liveNo2 = wAq?.no2 ?? (subIndices?.["NO2"]?.conc ?? (m?.no2 ?? 32.0));
    const no2Conc = isLive ? liveNo2 : getHourConc("NO2", liveNo2);
    const no2Idx = pollutantSubIndex("NO2", no2Conc);
    const no2Cat = aqiToCategory(no2Idx);

    // O3
    const liveO3 = wAq?.o3 ?? (subIndices?.["O3"]?.conc ?? (m?.o3 ?? 48.0));
    const o3Conc = isLive ? liveO3 : getHourConc("O3", liveO3);
    const o3Idx = pollutantSubIndex("O3", o3Conc);
    const o3Cat = aqiToCategory(o3Idx);

    // SO2
    const liveSo2 = wAq?.so2 ?? (subIndices?.["SO2"]?.conc ?? (m?.so2 ?? 14.0));
    const so2Conc = isLive ? liveSo2 : getHourConc("SO2", liveSo2);
    const so2Idx = pollutantSubIndex("SO2", so2Conc);
    const so2Cat = aqiToCategory(so2Idx);

    // CO
    const rawCo = wAq?.co != null ? (wAq.co > 50 ? Math.round((wAq.co / 1000) * 100) / 100 : wAq.co) : null;
    const liveCo = rawCo ?? (subIndices?.["CO"]?.conc ?? (m?.co ?? 0.88));
    const coConc = isLive ? liveCo : getHourConc("CO", liveCo);
    const coIdx = pollutantSubIndex("CO", coConc);
    const coCat = aqiToCategory(coIdx);


    return [
      {
        id: "pm25",
        title: "PM2.5 — Fine Particulate Matter",
        species: "PM2.5",
        chemicalFormula: "PM₂.₅",
        concentration: pm25Conc,
        unit: "µg/m³",
        subIndex: pm25Idx,
        category: pm25Cat,
        color: aqiColor(pm25Idx),
        standard24h: 60,
        description: "Fine inhalable particles (≤ 2.5 µm) that penetrate deep into alveolar sacs and the bloodstream.",
        sources: "Diesel vehicles, stubble burning, coal plants & secondary inorganic aerosols.",
        healthEffect: "Triggers asthma exacerbations, systemic vascular inflammation and acute bronchitis.",
        imageSrc: "https://images.unsplash.com/photo-1534088568595-a066f410bcda?auto=format&fit=crop&w=1200&q=80",
        href: "#forecast-datas",
      },
      {
        id: "pm10",
        title: "PM10 — Coarse Inhalable Matter",
        species: "PM10",
        chemicalFormula: "PM₁₀",
        concentration: pm10Conc,
        unit: "µg/m³",
        subIndex: pm10Idx,
        category: pm10Cat,
        color: aqiColor(pm10Idx),
        standard24h: 100,
        description: "Coarse respirable dust particles (≤ 10 µm) depositing in upper airways and trachea.",
        sources: "Resuspended road silt, construction excavation, demolition and topsoil entrainment.",
        healthEffect: "Causes upper respiratory mucosal irritation, severe coughing and throat dryness.",
        imageSrc: "https://images.unsplash.com/photo-1509114397022-ed747cca3f65?auto=format&fit=crop&w=1200&q=80",
        href: "#forecast-datas",
      },
      {
        id: "no2",
        title: "NO2 — Nitrogen Dioxide",
        species: "NO2",
        chemicalFormula: "NO₂",
        concentration: no2Conc,
        unit: "µg/m³",
        subIndex: no2Idx,
        category: no2Cat,
        color: aqiColor(no2Idx),
        standard24h: 80,
        description: "Pungent reddish-brown gas produced during high-temperature internal combustion.",
        sources: "Heavy-duty truck corridors, gas turbines and industrial boilers.",
        healthEffect: "Inflames airway lining and significantly increases susceptibility to pulmonary infections.",
        imageSrc: "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1200&q=80",
        href: "#forecast-datas",
      },
      {
        id: "o3",
        title: "O3 — Ground-Level Ozone",
        species: "O3",
        chemicalFormula: "O₃",
        concentration: o3Conc,
        unit: "µg/m³",
        subIndex: o3Idx,
        category: o3Cat,
        color: aqiColor(o3Idx),
        standard24h: 100,
        description: "Secondary photochemical oxidant formed by sunlight reacting with NOx and volatile organics.",
        sources: "Afternoon photochemical smog reactions over transport corridors and industrial zones.",
        healthEffect: "Causes direct oxidative lung damage, chest tightness and reduces forced vital capacity.",
        imageSrc: "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1200&q=80",
        href: "#forecast-datas",
      },
      {
        id: "so2",
        title: "SO2 — Sulphur Dioxide",
        species: "SO2",
        chemicalFormula: "SO₂",
        concentration: so2Conc,
        unit: "µg/m³",
        subIndex: so2Idx,
        category: so2Cat,
        color: aqiColor(so2Idx),
        standard24h: 80,
        description: "Corrosive gas from combustion of sulphur-bearing fossil fuels and smelting.",
        sources: "Coal thermal power stations, brick kilns and heavy furnace oil burners.",
        healthEffect: "Constricts bronchial airways within minutes of exposure, triggering severe asthmatic spasms.",
        imageSrc: "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=1200&q=80",
        href: "#forecast-datas",
      },
      {
        id: "co",
        title: "CO — Carbon Monoxide",
        species: "CO",
        chemicalFormula: "CO",
        concentration: coConc,
        unit: "mg/m³",
        subIndex: coIdx,
        category: coCat,
        color: aqiColor(coIdx),
        standard24h: 2.0,
        description: "Colourless, odourless asphyxiant gas reducing cellular oxygen delivery capacity.",
        sources: "Incomplete fuel combustion in congested idling traffic and open biomass heaters.",
        healthEffect: "Binds strongly to hemoglobin (forming carboxyhemoglobin) and impairs cardiovascular oxygenation.",
        imageSrc: "https://images.unsplash.com/photo-1470246973918-29a93221c455?auto=format&fit=crop&w=1200&q=80",
        href: "#forecast-datas",
      },
    ];
  }, [cityAggregate, consensus, hour, cursor]);

  return (
    <section
      id="pollutant-card-stack"
      className="relative w-full pt-16 pb-24 px-4 sm:px-6 lg:px-8 overflow-hidden"
      style={{
        background: "linear-gradient(180deg, rgba(5,7,10,0.95) 0%, rgba(10,14,20,1) 50%, rgba(5,7,10,0.95) 100%)",
        borderTop: "1px solid var(--hairline-2)",
        borderBottom: "1px solid var(--hairline-2)",
      }}
    >
      {/* Background ambient lighting */}
      <div
        className="pointer-events-none absolute -top-24 left-1/2 -translate-x-1/2 w-[800px] h-[350px] rounded-full blur-[120px] opacity-20"
        style={{ background: "radial-gradient(circle, var(--live) 0%, transparent 70%)" }}
      />

      <div className="max-w-6xl mx-auto">
        {/* Section Header */}
        <div className="flex flex-col items-center text-center mb-10">
          <div
            className="liquid-glass px-3.5 py-1 rounded-full mb-3.5 inline-flex items-center gap-2"
            style={{
              border: "1px solid rgba(255, 255, 255, 0.15)",
              background: "rgba(255, 255, 255, 0.03)",
            }}
          >
            <Sparkles size={13} className="text-[var(--live)]" />
            <span className="text-[11px] font-mono tracking-wider uppercase text-[var(--bone)]">
              {t("cardstack.activeTelemetry")}
            </span>
          </div>

          <h2 className="text-2xl sm:text-4xl font-bold font-sans text-[var(--bone)] tracking-tight">
            {t("cardstack.title")}
          </h2>

          <p className="mt-2.5 text-xs sm:text-sm text-[var(--mist)] max-w-2xl leading-relaxed">
            {t("cardstack.subtitle")}
          </p>

          <div className="mt-4 flex items-center gap-4 text-xs font-mono text-[var(--mist-dim)]">
            <span className="inline-flex items-center gap-1.5">
              <Layers size={13} className="text-[var(--live)]" />
              <span>6 Species Stack</span>
            </span>
            <span>•</span>
            <span className="inline-flex items-center gap-1.5">
              <Activity size={13} className="text-green-400" />
              <span>43 Telemetry Stations</span>
            </span>
            <span>•</span>
            <span className="inline-flex items-center gap-1.5">
              <Wind size={13} className="text-cyan-400" />
              <span>Interactive 3D Carousel</span>
            </span>
          </div>
        </div>

        {/* 3D Card Stack Component — Extended to Screen Margins */}
        <div className="w-full max-w-6xl mx-auto flex justify-center py-4">
          <CardStack<PollutantCardItem>
            items={items}
            initialIndex={0}
            autoAdvance={true}
            intervalMs={3500}
            pauseOnHover={true}
            maxVisible={5}
            cardWidth={500}
            cardHeight={310}
            overlap={0.55}
            spreadDeg={28}
            perspectivePx={1150}
            depthPx={95}
            tiltXDeg={8}
            activeLiftPx={20}
            showDots={true}
            renderCard={(item, { active }) => (
              <div
                className="relative w-full h-full rounded-2xl overflow-hidden select-none flex flex-col justify-between p-5 sm:p-6 transition-all duration-300"
                style={{

                  background: `linear-gradient(145deg, ${item.color}26 0%, rgba(10, 14, 22, 0.94) 45%, ${item.color}18 100%)`,
                  border: `1.5px solid ${item.color}${active ? "90" : "55"}`,
                  boxShadow: active
                    ? `0 20px 45px -8px ${item.color}45, 0 0 28px -2px ${item.color}35, inset 0 1px 2px ${item.color}80`
                    : `0 12px 30px -8px ${item.color}30, 0 0 16px -4px ${item.color}20, inset 0 1px 1px ${item.color}40`,
                }}
              >
                {/* Background Image with Danger-Tinted Gradient Scrim */}
                <div className="absolute inset-0 z-0 overflow-hidden pointer-events-none">
                  <img
                    src={item.imageSrc}
                    alt={item.title}
                    className="w-full h-full object-cover opacity-25 transition-transform duration-700"
                    style={{
                      transform: active ? "scale(1.05)" : "scale(1.0)",
                    }}
                    draggable={false}
                  />
                  <div
                    className="absolute inset-0"
                    style={{
                      background: `linear-gradient(180deg, ${item.color}20 0%, rgba(8,12,18,0.85) 45%, rgba(4,6,10,0.96) 100%)`,
                    }}
                  />
                  {/* Top-Right Glowing Ambient Danger Orb */}
                  <div
                    className="absolute -top-14 -right-14 w-44 h-44 rounded-full blur-3xl opacity-40 pointer-events-none transition-all duration-500"
                    style={{ backgroundColor: item.color }}
                  />
                  {/* Bottom-Left Subtle Ambient Glow */}
                  <div
                    className="absolute -bottom-14 -left-14 w-36 h-36 rounded-full blur-3xl opacity-25 pointer-events-none"
                    style={{ backgroundColor: item.color }}
                  />
                </div>

                {/* Card Top: Formula Badge + Sub-Index Badge */}
                <div className="relative z-10 flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <div
                      className="px-2.5 py-0.5 rounded-lg font-mono font-bold text-xs"
                      style={{
                        background: `${item.color}22`,
                        border: `1px solid ${item.color}70`,
                        color: item.color,
                        boxShadow: `0 0 10px ${item.color}30`,
                        backdropFilter: "blur(8px)",
                      }}
                    >
                      {item.chemicalFormula}
                    </div>
                    <div>
                      <div className="text-xs font-semibold text-white/95 leading-tight">
                        {item.title}
                      </div>
                      <div className="text-[10px] font-mono text-white/60">
                        {t("cardstack.safeLimit")}: {item.standard24h} {item.unit}
                      </div>
                    </div>
                  </div>

                  {/* Sub-Index Danger Pill */}
                  <div
                    className="px-2.5 py-0.5 rounded-full flex items-center gap-1.5 font-mono text-[11px] font-semibold flex-shrink-0"
                    style={{
                      backgroundColor: `${item.color}25`,
                      border: `1.5px solid ${item.color}90`,
                      color: item.color,
                      boxShadow: `0 0 14px ${item.color}40`,
                    }}
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full animate-pulse"
                      style={{ backgroundColor: item.color }}
                    />
                    <span>{t("cardstack.subIndex")} {Math.round(item.subIndex)}</span>
                  </div>
                </div>

                {/* Card Middle: Live Concentration Readout */}
                <div className="relative z-10 my-auto py-1">
                  <div className="flex items-baseline gap-2">
                    <span
                      className="text-3xl sm:text-4xl font-black font-mono tracking-tight"
                      style={{
                        color: item.color,
                        textShadow: `0 0 20px ${item.color}50`,
                      }}
                    >
                      {item.concentration < 10
                        ? item.concentration.toFixed(1)
                        : Math.round(item.concentration)}
                    </span>
                    <span className="text-xs sm:text-sm font-mono text-white/70 font-medium">
                      {item.unit}
                    </span>
                    {item.concentration > item.standard24h && (
                      <span
                        className="ml-auto inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded font-semibold"
                        style={{
                          backgroundColor: `${item.color}25`,
                          border: `1px solid ${item.color}60`,
                          color: item.color,
                        }}
                      >
                        <AlertTriangle size={10} />
                        {(item.concentration / item.standard24h).toFixed(1)}{t("cardstack.ratioToStandard")}
                      </span>
                    )}
                  </div>

                  {/* Progress Bar against Standard with Danger Fill */}
                  <div
                    className="w-full h-1.5 rounded-full overflow-hidden mt-1.5"
                    style={{ backgroundColor: `${item.color}20` }}
                  >
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${Math.min(100, (item.concentration / (item.standard24h * 2.5)) * 100)}%`,
                        backgroundColor: item.color,
                        boxShadow: `0 0 10px ${item.color}`,
                      }}
                    />
                  </div>

                  <p className="mt-2 text-[11px] text-white/85 line-clamp-2 leading-snug font-sans">
                    {item.description}
                  </p>
                </div>

                {/* Card Bottom: Sources & Health Warning */}
                <div
                  className="relative z-10 pt-2 grid grid-cols-2 gap-2 text-[10.5px] font-sans"
                  style={{ borderTop: `1px solid ${item.color}30` }}
                >
                  <div>
                    <span
                      className="block font-mono text-[9px] uppercase font-semibold"
                      style={{ color: `${item.color}bb` }}
                    >
                      {t("cardstack.primarySources")}:
                    </span>
                    <span className="text-white/85 line-clamp-1">
                      {item.sources}
                    </span>
                  </div>
                  <div>
                    <span
                      className="block font-mono text-[9px] uppercase font-semibold"
                      style={{ color: `${item.color}bb` }}
                    >
                      {t("cardstack.healthImpact")}:
                    </span>
                    <span className="text-white/85 line-clamp-1">
                      {item.healthEffect}
                    </span>
                  </div>
                </div>
              </div>
            )}

          />
        </div>

      </div>
    </section>
  );
}
