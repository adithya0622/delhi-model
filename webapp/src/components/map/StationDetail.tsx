import { useMemo } from "react";
import { aqiColor } from "@/lib/aqi";
import { clock, compass, fixed, int, pct } from "@/lib/format";
import { normalizeDominant, windStat } from "@/lib/mapgeo";
import type {
  CityAggregateResponse,
  CityOverview,
  ForecastResponse,
  PlumeVectorsResponse,
  StationReading,
} from "@/lib/types";
import { Lanyard, type LanyardCardData } from "@/components/ui/Lanyard";
import { useTranslation } from "@/i18n";
import { getTranslatedStationName, type StationLang } from "@/lib/stationTranslations";

interface StationDetailProps {
  /** The clicked station, or null for the default network view. */
  station: StationReading | null;
  overview: CityOverview | null;
  plume: PlumeVectorsResponse | null;
  forecast: ForecastResponse | null;
  cursor: number;
  /** Count of live stations on the map, for the aggregate caption. */
  stationCount: number;
  cityAggregate?: CityAggregateResponse | null;
  onClear: () => void;
}

// Preferred display order; anything unrecognised sorts after, alphabetically.
const POLL_ORDER = ["PM2.5", "PM10", "O3", "NO2", "SO2", "CO"];
function pollRank(k: string): number {
  const i = POLL_ORDER.indexOf(normalizeDominant(k));
  return i === -1 ? POLL_ORDER.length : i;
}

/**
 * 3D Physics Lanyard Hanging Card for the Station Map Section.
 * Renders the live station telemetry or network aggregate on an interactive
 * swinging 3D badge with real-time dynamic texture rendering and physics.
 */
export function StationDetail({
  station,
  overview,
  plume,
  forecast,
  cursor,
  stationCount,
  cityAggregate,
  onClear,
}: StationDetailProps) {
  const { language } = useTranslation();
  const cardData: LanyardCardData = useMemo(() => {
    if (station) {
      const pollutants = (Object.entries(station.pollutants) as Array<[string, number | undefined]>)
        .filter((e): e is [string, number] => e[1] != null && !Number.isNaN(e[1]))
        .sort((a, b) => pollRank(a[0]) - pollRank(b[0]))
        .map(([k, v]) => ({ name: normalizeDominant(k), value: `${fixed(v, 1)}` }));

      const c = aqiColor(station.aqi);
      const aqiNum = Math.round(station.aqi);

      return {
        title: getTranslatedStationName(station.name, (language as StationLang) || "en"),
        subtitle: station.source || "IQAir Live AQI · WeatherAPI Telemetry",
        aqi: aqiNum,
        category: station.category,
        color: c,
        meta: [
          { label: "Dominant", value: normalizeDominant(String(station.dominant_pollutant)) },
          { label: "Updated", value: station.updated ? clock(station.updated) : "Live" },
          { label: "Temperature", value: station.weather?.temperature != null ? `${station.weather.temperature}°C` : `${fixed(station.lat, 2)}°N` },
          { label: "Wind", value: station.weather?.wind_speed != null ? `${station.weather.wind_speed} km/h` : `${fixed(station.lon, 2)}°E` },
        ],
        pollutants,
        isStation: true,
      };
    }

    // Default: city aggregate + stubble-transport stats
    const hours = forecast?.forecast_hours ?? [];
    const curHour = hours[cursor] ?? null;
    const isLiveNow = cursor === 0;

    const displayAqi = isLiveNow
      ? (cityAggregate?.overall_aqi ?? overview?.aqi ?? curHour?.aqi ?? 320)
      : (curHour?.aqi ?? cityAggregate?.overall_aqi ?? overview?.aqi ?? 320);

    const displayCategory = isLiveNow
      ? (cityAggregate?.aqi_category ?? overview?.category ?? curHour?.category ?? "Very Poor")
      : (curHour?.category ?? overview?.category ?? "Very Poor");

    const color = cityAggregate?.color && isLiveNow ? cityAggregate.color : aqiColor(displayAqi);
    const shareNow = hours[cursor]?.plume_contribution ?? null;
    const sharePeak = hours.length ? Math.max(...hours.map((h) => h.plume_contribution)) : null;
    const uv = plume ? plume.wind_series[cursor] ?? [plume.wind_850hpa_u, plume.wind_850hpa_v] : null;
    const wind = uv ? windStat(uv[0], uv[1]) : null;

    return {
      title: "Delhi NCR Network",
      subtitle: isLiveNow ? `${stationCount || 43} Live CAAQMS Stations` : `+${cursor}h Horizon Forecast`,
      aqi: Math.round(displayAqi),
      category: displayCategory,
      color,
      meta: [
        { label: "Fire Detections", value: plume ? `${int(plume.hotspot_count_total)}` : "0" },
        { label: "Plume Share", value: shareNow != null ? pct(shareNow * 100, 1) : "0.0%" },
        { label: "Peak Share", value: sharePeak != null ? pct(sharePeak * 100, 1) : "0.0%" },
        { label: "850 hPa Wind", value: wind ? `${fixed(wind.speed, 1)} m/s ${compass(wind.from)}` : "1.0 m/s NE" },
      ],
      pollutants: [
        { name: "PM2.5", value: "Primary" },
        { name: "PM10", value: "Coarse" },
        { name: "NO2", value: "Vehicular" },
        { name: "O3", value: "Photochem" },
      ],
      isStation: false,
    };
  }, [station, overview, plume, forecast, cursor, stationCount, cityAggregate, language]);

  return <Lanyard data={cardData} onClear={onClear} />;
}
