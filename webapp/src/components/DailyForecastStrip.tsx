import { useMemo, useState } from "react";
import { aqiColor, aqiToCategory } from "@/lib/aqi";
import type { CityAggregateResponse, ConsensusResponse, ForecastResponse, HourlyForecast } from "@/lib/types";
import { useTranslation } from "@/i18n";

interface DailyForecastStripProps {
  forecast?: ForecastResponse | null;
  hours?: HourlyForecast[];
  consensus?: ConsensusResponse | null;
  cityAggregate?: CityAggregateResponse | null;
  onSelectDay?: (dayIndex: number) => void;
}

export interface DayForecastItem {
  dayIndex: number;
  dayLabel: string;
  dateLabel: string;
  aqi: number;
  category: string;
  color: string;
  trend: "up" | "down" | "steady";
  trendSymbol: string;
  isToday: boolean;
  pm25: number;
  temp: number;
  wind: number;
}

export function DailyForecastStrip({
  forecast,
  hours = [],
  consensus: _consensus,
  cityAggregate: _cityAggregate,
  onSelectDay,
}: DailyForecastStripProps) {
  const { t } = useTranslation();
  const [selectedDay, setSelectedDay] = useState<number>(0);

  const daysData = useMemo<DayForecastItem[]>(() => {
    const rawHours = forecast?.forecast_hours ?? hours;
    if (!rawHours || rawHours.length === 0) return [];

    const checkpoints = [0, 6, 12, 18, 24, 36, 48, 71];
    const result: DayForecastItem[] = [];
    let prevAqi = rawHours[0]?.aqi ?? 0;

    for (let i = 0; i < checkpoints.length; i++) {
      const hIdx = Math.min(checkpoints[i], rawHours.length - 1);
      const h = rawHours[hIdx];
      if (!h) continue;

      const isToday = i === 0;
      const dayName = isToday ? t("dailyForecast.today") : `+${checkpoints[i]}h`;

      let dateStr = "";
      if (h.timestamp) {
        try {
          const d = new Date(h.timestamp);
          const hoursStr = d.getHours().toString().padStart(2, "0");
          const minsStr = d.getMinutes().toString().padStart(2, "0");
          dateStr = `${hoursStr}:${minsStr}`;
        } catch {
          dateStr = `+${checkpoints[i]}h`;
        }
      } else {
        dateStr = `+${checkpoints[i]}h`;
      }

      const dayAqi = Math.round(h.aqi);
      const pmObj = h.sub_indices?.find((s) => s.pollutant === "PM2.5");
      const dayPm25 = Math.round(pmObj?.concentration ?? (dayAqi * 0.45));
      const dayTemp = Math.round(h.temperature_2m_c ?? 26);
      const dayWind = Number((h.wind_speed_ms ?? 3.5).toFixed(1));

      // Determine Trend compared to previous checkpoint
      let trend: "up" | "down" | "steady" = "steady";
      let trendSymbol = "→";
      if (dayAqi > prevAqi + 4) {
        trend = "up";
        trendSymbol = "↑";
      } else if (dayAqi < prevAqi - 4) {
        trend = "down";
        trendSymbol = "↓";
      }

      const cat = h.category || aqiToCategory(dayAqi);
      const col = aqiColor(dayAqi);

      result.push({
        dayIndex: checkpoints[i],
        dayLabel: dayName,
        dateLabel: dateStr,
        aqi: dayAqi,
        category: cat,
        color: col,
        trend,
        trendSymbol,
        isToday,
        pm25: dayPm25,
        temp: dayTemp,
        wind: dayWind,
      });

      prevAqi = dayAqi;
    }

    return result;
  }, [forecast, hours, t]);

  const handleCardClick = (idx: number) => {
    setSelectedDay(idx);
    if (onSelectDay) onSelectDay(idx);
  };

  const getCategoryLabel = (cat: string) => {
    switch (cat.toLowerCase()) {
      case "good": return t("hero.categories.good");
      case "satisfactory": return t("hero.categories.satisfactory");
      case "moderate": return t("hero.categories.moderate");
      case "poor": return t("hero.categories.poor");
      case "very poor": return t("hero.categories.veryPoor");
      case "severe": return t("hero.categories.severe");
      case "hazardous": return t("hero.categories.hazardous");
      default: return cat;
    }
  };

  return (
    <div className="daily-strip-wrap" aria-label="72-Hour Prognostic Hourly Outlook">
      <div className="daily-strip-head">
        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
          <span className="daily-pulse-dot" />
          <span className="daily-strip-title">{t("dailyForecast.title")}</span>
        </div>
        <span className="daily-strip-sub">{t("dailyForecast.subtitle")}</span>
      </div>

      <div className="daily-strip-grid">
        {daysData.map((d) => {
          const isSelected = selectedDay === d.dayIndex;
          return (
            <button
              key={d.dayIndex}
              type="button"
              className={`daily-card ${isSelected ? "daily-card--selected" : ""}`}
              onClick={() => handleCardClick(d.dayIndex)}
              style={{
                borderColor: isSelected ? d.color : undefined,
              }}
            >
              {/* Top Specular Shiny Border Highlight */}
              <div className="daily-card-topglow" />
              
              {/* Bottom Neon Accent Bloom */}
              <div
                className="daily-card-blob"
                style={{
                  background: `radial-gradient(circle, ${d.color}77 0%, ${d.color}00 70%)`,
                }}
              />

              {/* Inner Card Surface */}
              <div className="daily-card-inner">
                {/* Header: Day Name + Date */}
                <div className="daily-card-header">
                  <span className={`daily-card-day ${d.isToday ? "daily-card-day--today" : ""}`}>
                    {d.dayLabel}
                  </span>
                  <span className="daily-card-date">{d.dateLabel}</span>
                </div>

                {/* Big Bold AQI Number in category color */}
                <div className="daily-card-aqi-wrap">
                  <span className="daily-card-aqi" style={{ color: d.color }}>
                    {d.aqi}
                  </span>
                </div>

                {/* Category Label */}
                <div className="daily-card-cat" style={{ color: d.color }}>
                  {getCategoryLabel(d.category)}
                </div>

                {/* Trend Symbol */}
                <div className="daily-card-trend" title={`Trend: ${d.trend}`}>
                  <span
                    className={`daily-trend-sym daily-trend-${d.trend}`}
                    style={{
                      color: d.trend === "up" ? "#f43f5e" : d.trend === "down" ? "#10b981" : "#eab308",
                    }}
                  >
                    {d.trendSymbol}
                  </span>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
export default DailyForecastStrip;
