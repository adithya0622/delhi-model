import { useMemo } from "react";
import { Wind, Thermometer, Droplets, Gauge, Cpu, Sparkles } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CityAggregateResponse, ConsensusResponse, MlForecast72hrResponse } from "@/lib/types";
import type { IqairRealtimeResponse } from "@/lib/api";
import { DailyForecastStrip } from "@/components/DailyForecastStrip";
import { useTranslation } from "@/i18n";

interface Props {
  data: ConsensusResponse | null;
  forecast?: MlForecast72hrResponse | null;
  loading: boolean;
  error: string | null;
  cityAggregate?: CityAggregateResponse | null;
  realtimeIqair?: IqairRealtimeResponse | null;
}

function metric(value: number | undefined, unit: string) {
  return value == null ? "—" : `${value.toFixed(1)}${unit}`;
}

export function ConsensusDashboard({ data, forecast, loading, error, cityAggregate, realtimeIqair }: Props) {
  const { t } = useTranslation();
  const metrics = data?.metrics;

  const liveAqi = realtimeIqair?.aqi ?? (cityAggregate?.overall_aqi ?? (metrics ? Math.round(metrics.aqi) : 0));
  const livePm25 = cityAggregate?.sub_indices?.["PM2.5"]?.conc ?? metrics?.pm25;
  const livePm10 = cityAggregate?.sub_indices?.["PM10"]?.conc ?? metrics?.pm10;
  const liveTemp = metrics?.temp;
  const liveWind = metrics?.wind;

  // Single source of truth for the chart's t=0 point and forecast decay
  const chartData = useMemo(() => {
    const mlHours = forecast?.forecast_hours;
    if (mlHours && mlHours.length > 0) {
      const checkpoints = [0, 6, 12, 18, 24, 36, 48, 60, 71];
      return checkpoints.map((hIdx) => {
        const h = mlHours[Math.min(hIdx, mlHours.length - 1)];
        const pm = h.sub_indices?.find((s) => s.pollutant === "PM2.5")?.concentration ?? Math.round(h.aqi * 0.45);
        return {
          horizon_hours: hIdx,
          timestamp: h.timestamp,
          pm25: Math.round(pm),
          aqi: Math.round(h.aqi),
          category: h.category,
          wind_speed: Number((h.wind_speed_ms ?? 3.5).toFixed(1)),
          temperature: Math.round(h.temperature_2m_c ?? 26),
          rule: hIdx === 0 ? "Current (Now)" : `+${hIdx}h Prognosis`,
          explanation: `Predicted by 72h Chemical Regime ML Model (${h.pm25_source || "HistGradientBoostingRegressor"})`,
        };
      });
    }

    const raw = data?.forecast ?? [];
    if (raw.length === 0) {
      return [
        {
          horizon_hours: 0,
          timestamp: new Date().toISOString(),
          pm25: livePm25 ?? 0,
          aqi: liveAqi,
          category: "Very Unhealthy" as const,
          wind_speed: liveWind ?? 0,
          temperature: liveTemp ?? 0,
          rule: "Current",
          explanation: "Current unified network observation",
        },
      ];
    }

    const pm25Now = livePm25 ?? raw[0]?.pm25 ?? 0;
    const offsetPm = pm25Now - (raw[0]?.pm25 ?? pm25Now);
    const offsetAqi = liveAqi - (raw[0]?.aqi ?? liveAqi);

    return raw.map((item) => {
      const h = item.horizon_hours;
      if (h === 0) {
        return {
          ...item,
          pm25: pm25Now,
          aqi: liveAqi,
        };
      }
      const decay = Math.exp(-h / 24);
      return {
        ...item,
        pm25: Math.max(10, Math.round(item.pm25 + offsetPm * decay)),
        aqi: Math.max(10, Math.round(item.aqi + offsetAqi * decay)),
      };
    });
  }, [forecast, data, livePm25, liveAqi, liveWind, liveTemp]);

  return (
    <section className="consensus-wrap" aria-label="Live consensus forecast">
      <div className="consensus-head">
        <div>
          <p className="eyebrow">{t("consensus.fiveSourceConsensus")}</p>
          <h2 className="section__h section__h--sm">{t("consensus.title")}</h2>
          <p className="section__lede section__lede--sm">{t("consensus.subtitle")}</p>
        </div>
        <span className="source-count">
          {t("consensus.aggregatedAcross")} {cityAggregate?.station_count ?? 0} {t("consensus.stationsCount")} + {data?.source_count ?? 0} {t("consensus.meteoFeeds")}.
        </span>
      </div>
      {error && <p className="consensus-error">Consensus feed unavailable: {error}</p>}
      
      {/* 5-Source Top Metric Cards with Realism Shiny Borders */}
      <div className="consensus-grid">
        {/* 1. AQI Card */}
        <article className="realism-box">
          <div className="realism-topglow" />
          <div className="realism-blob" />
          <div className="realism-inner consensus-card-inner">
            <div className="realism-inner-glow" />
            <div style={{ display: "flex", alignItems: "center", gap: "0.55rem" }}>
              <Gauge size={16} style={{ color: "#3fff75" }} />
              <span style={{ color: "var(--mist-dim)", font: "0.7rem var(--mono)", textTransform: "uppercase", letterSpacing: "0.08em" }}>AQI</span>
            </div>
            <strong style={{ fontSize: "1.8rem", fontWeight: 600, color: "var(--bone)", margin: "0.25rem 0 0.1rem" }}>
              {loading ? "—" : liveAqi}
            </strong>
            <small style={{ color: "var(--mist-faint)", fontSize: "0.72rem" }}>
              {cityAggregate?.dominant_pollutant ? `${t("hero.dominant")} ${cityAggregate.dominant_pollutant}` : "CPCB Max"}
            </small>
          </div>
        </article>

        {/* 2. PM2.5 Card */}
        <article className="realism-box">
          <div className="realism-topglow" />
          <div className="realism-blob" />
          <div className="realism-inner consensus-card-inner">
            <div className="realism-inner-glow" />
            <div style={{ display: "flex", alignItems: "center", gap: "0.55rem" }}>
              <Droplets size={16} style={{ color: "#3fff75" }} />
              <span style={{ color: "var(--mist-dim)", font: "0.7rem var(--mono)", textTransform: "uppercase", letterSpacing: "0.08em" }}>PM2.5</span>
            </div>
            <strong style={{ fontSize: "1.8rem", fontWeight: 600, color: "var(--bone)", margin: "0.25rem 0 0.1rem" }}>
              {loading ? "—" : metric(livePm25, "")}
            </strong>
            <small style={{ color: "var(--mist-faint)", fontSize: "0.72rem" }}>µg/m³</small>
          </div>
        </article>

        {/* 3. PM10 Card */}
        <article className="realism-box">
          <div className="realism-topglow" />
          <div className="realism-blob" />
          <div className="realism-inner consensus-card-inner">
            <div className="realism-inner-glow" />
            <div style={{ display: "flex", alignItems: "center", gap: "0.55rem" }}>
              <Droplets size={16} style={{ color: "#3fff75" }} />
              <span style={{ color: "var(--mist-dim)", font: "0.7rem var(--mono)", textTransform: "uppercase", letterSpacing: "0.08em" }}>PM10</span>
            </div>
            <strong style={{ fontSize: "1.8rem", fontWeight: 600, color: "var(--bone)", margin: "0.25rem 0 0.1rem" }}>
              {loading ? "—" : metric(livePm10, "")}
            </strong>
            <small style={{ color: "var(--mist-faint)", fontSize: "0.72rem" }}>µg/m³</small>
          </div>
        </article>

        {/* 4. Temperature Card */}
        <article className="realism-box">
          <div className="realism-topglow" />
          <div className="realism-blob" />
          <div className="realism-inner consensus-card-inner">
            <div className="realism-inner-glow" />
            <div style={{ display: "flex", alignItems: "center", gap: "0.55rem" }}>
              <Thermometer size={16} style={{ color: "#3fff75" }} />
              <span style={{ color: "var(--mist-dim)", font: "0.7rem var(--mono)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{t("consensus.temperature")}</span>
            </div>
            <strong style={{ fontSize: "1.8rem", fontWeight: 600, color: "var(--bone)", margin: "0.25rem 0 0.1rem" }}>
              {loading ? "—" : metric(liveTemp, "°")}
            </strong>
            <small style={{ color: "var(--mist-faint)", fontSize: "0.72rem" }}>°C</small>
          </div>
        </article>

        {/* 5. Wind Card */}
        <article className="realism-box">
          <div className="realism-topglow" />
          <div className="realism-blob" />
          <div className="realism-inner consensus-card-inner">
            <div className="realism-inner-glow" />
            <div style={{ display: "flex", alignItems: "center", gap: "0.55rem" }}>
              <Wind size={16} style={{ color: "#3fff75" }} />
              <span style={{ color: "var(--mist-dim)", font: "0.7rem var(--mono)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{t("consensus.wind")}</span>
            </div>
            <strong style={{ fontSize: "1.8rem", fontWeight: 600, color: "var(--bone)", margin: "0.25rem 0 0.1rem" }}>
              {loading ? "—" : metric(liveWind, "")}
            </strong>
            <small style={{ color: "var(--mist-faint)", fontSize: "0.72rem" }}>km/h</small>
          </div>
        </article>
      </div>

      {/* 7-Day Daily Predictable AQI Outlook Strip */}
      <DailyForecastStrip
        forecast={forecast as any}
        hours={chartData as any}
        consensus={data}
        cityAggregate={cityAggregate}
      />

      {/* 2 Lower Panels with Realism Shiny Borders */}
      <div className="consensus-panels">
        {/* Explainability Engine Panel */}
        <article className="realism-box explain-panel">
          <div className="realism-topglow" />
          <div className="realism-blob" />
          <div className="realism-inner">
            <div className="realism-inner-glow" />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.2rem" }}>
              <p className="eyebrow" style={{ margin: 0 }}>{t("consensus.explainabilityEngine")}</p>
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.35rem",
                  fontSize: "10px",
                  fontFamily: "var(--mono)",
                  padding: "2px 7px",
                  borderRadius: "4px",
                  background: "rgba(56, 189, 248, 0.12)",
                  color: "#38bdf8",
                  border: "1px solid rgba(56, 189, 248, 0.25)",
                }}
              >
                <Sparkles size={11} />
                <span>ML Model Active</span>
              </span>
            </div>

            <h3 style={{ margin: "0.35rem 0 0.5rem", fontSize: "1.05rem", fontWeight: 500, color: "var(--bone)" }}>
              {t("consensus.whyModelExpects")}
            </h3>

            {/* Current Atmospheric Context Rationale */}
            <p style={{ color: "var(--mist)", lineHeight: 1.55, fontSize: "0.85rem", margin: "0 0 0.75rem" }}>
              {data?.explainability ?? "Evaluating multi-source meteorological convergence and diurnal stability."}
            </p>

            {/* Machine Learning Model Architecture & Telemetry Specs */}
            <div
              style={{
                borderTop: "1px solid rgba(255, 255, 255, 0.08)",
                paddingTop: "0.65rem",
                display: "flex",
                flexDirection: "column",
                gap: "0.5rem",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <Cpu size={14} style={{ color: "#38bdf8", flexShrink: 0 }} />
                <span style={{ fontSize: "11.5px", fontWeight: 600, color: "var(--bone)" }}>
                  HistGradientBoostingRegressor
                </span>
                <span style={{ fontSize: "10px", color: "var(--mist-dim)", marginLeft: "auto", fontFamily: "var(--mono)" }}>
                  v2.4 Chemical Regime
                </span>
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "0.35rem 0.5rem",
                  fontSize: "10px",
                  color: "var(--mist)",
                  background: "rgba(0, 0, 0, 0.22)",
                  padding: "0.45rem 0.6rem",
                  borderRadius: "6px",
                  border: "1px solid rgba(255, 255, 255, 0.05)",
                }}
              >
                <div>
                  <span style={{ color: "var(--mist-dim)" }}>Horizon: </span>
                  <strong style={{ color: "var(--bone)" }}>72h Prognostic</strong>
                </div>
                <div>
                  <span style={{ color: "var(--mist-dim)" }}>Granularity: </span>
                  <strong style={{ color: "var(--bone)" }}>Hourly Steps</strong>
                </div>
                <div>
                  <span style={{ color: "var(--mist-dim)" }}>Live Grounding: </span>
                  <strong style={{ color: "#38bdf8" }}>IQAir Station Feed</strong>
                </div>
                <div>
                  <span style={{ color: "var(--mist-dim)" }}>Met &amp; Chemistry: </span>
                  <strong style={{ color: "#34d399" }}>WeatherAPI</strong>
                </div>
              </div>

              {/* Key Features Pill Badges */}
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem", marginTop: "0.1rem" }}>
                <span style={{ fontSize: "9px", padding: "2px 5px", borderRadius: "3px", background: "rgba(255, 255, 255, 0.05)", color: "var(--mist)", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
                  6-Species Chemistry (PM2.5, PM10, NO2, O3, SO2, CO)
                </span>
                <span style={{ fontSize: "9px", padding: "2px 5px", borderRadius: "3px", background: "rgba(255, 255, 255, 0.05)", color: "var(--mist)", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
                  Thermal Inversion Lid (ΔT 925–1000 hPa)
                </span>
                <span style={{ fontSize: "9px", padding: "2px 5px", borderRadius: "3px", background: "rgba(255, 255, 255, 0.05)", color: "var(--mist)", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
                  PBL Ventilation Dynamics
                </span>
                <span style={{ fontSize: "9px", padding: "2px 5px", borderRadius: "3px", background: "rgba(255, 255, 255, 0.05)", color: "var(--mist)", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
                  Fourier Diurnal Harmonics
                </span>
              </div>
            </div>
          </div>
        </article>

        {/* 72-Hour PM2.5 & AQI Outlook Chart Panel */}
        <article className="realism-box chart-panel">
          <div className="realism-topglow" />
          <div className="realism-blob" />
          <div className="realism-inner">
            <div className="realism-inner-glow" />
            <div className="chart-title">
              <div>
                <p className="eyebrow">deterministic projection</p>
                <h3 style={{ margin: "0.35rem 0 0.8rem", fontSize: "1.05rem", fontWeight: 500, color: "var(--bone)" }}>72h PM2.5 &amp; AQI Outlook</h3>
              </div>
              <span style={{ color: "var(--mist-faint)", font: "0.68rem var(--mono)", whiteSpace: "nowrap" }}>
                72-Hour Continuous Atmospheric Trajectory
              </span>
            </div>
            <div className="forecast-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 12, right: 12, left: 0, bottom: 0 }}>
                  <XAxis dataKey="horizon_hours" tickFormatter={(v) => (v === 0 ? "Now" : `+${v}h`)} stroke="rgba(235,240,235,.45)" />
                  <YAxis yAxisId="left" stroke="#ffb86b" width={34} />
                  <YAxis yAxisId="right" orientation="right" stroke="#91c9ff" width={34} />
                  <Tooltip
                    contentStyle={{ background: "#111a20", border: "1px solid rgba(255,255,255,.16)", borderRadius: "6px", fontSize: "12px", fontFamily: "var(--mono)" }}
                    labelFormatter={(v) => (v === 0 ? "Current (Now)" : `Horizon +${v}h`)}
                    formatter={(value: any, name: any) => [
                      name === "PM2.5" ? `${value} µg/m³` : `${value} (CPCB AQI)`,
                      name,
                    ]}
                  />
                  <Line yAxisId="left" type="monotone" dataKey="pm25" name="PM2.5" stroke="#ffb86b" strokeWidth={2.5} dot={{ r: 3.5, fill: "#ffb86b" }} />
                  <Line yAxisId="right" type="monotone" dataKey="aqi" name="AQI" stroke="#91c9ff" strokeWidth={2.5} dot={{ r: 3.5, fill: "#91c9ff" }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </article>
      </div>
    </section>
  );
}
