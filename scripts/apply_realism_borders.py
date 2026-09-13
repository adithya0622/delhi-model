# 1. Update ConsensusDashboard.tsx
consensus_code = r"""import { useMemo } from "react";
import { AlertTriangle, Wind, Thermometer, Droplets, Gauge } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CityAggregateResponse, ConsensusResponse } from "@/lib/types";

interface Props {
  data: ConsensusResponse | null;
  loading: boolean;
  error: string | null;
  cityAggregate?: CityAggregateResponse | null;
}

function metric(value: number | undefined, unit: string) {
  return value == null ? "—" : `${value.toFixed(1)}${unit}`;
}

export function ConsensusDashboard({ data, loading, error, cityAggregate }: Props) {
  const metrics = data?.metrics;

  const liveAqi = cityAggregate?.overall_aqi ?? (metrics ? Math.round(metrics.aqi) : 320);
  const livePm25 = cityAggregate?.sub_indices?.["PM2.5"]?.conc ?? metrics?.pm25 ?? 73.8;
  const livePm10 = cityAggregate?.sub_indices?.["PM10"]?.conc ?? metrics?.pm10 ?? 97.8;
  const liveTemp = metrics?.temp ?? 19.0;
  const liveWind = metrics?.wind ?? 5.2;

  // Single source of truth for the chart's t=0 point and forecast decay
  const chartData = useMemo(() => {
    const raw = data?.forecast ?? [];
    if (raw.length === 0) {
      return [
        {
          horizon_hours: 0,
          timestamp: new Date().toISOString(),
          pm25: livePm25,
          aqi: liveAqi,
          category: "Very Poor" as const,
          wind_speed: liveWind,
          temperature: liveTemp,
          rule: "Current",
          explanation: "Current unified network observation",
        },
      ];
    }

    const offsetPm = livePm25 - (raw[0]?.pm25 ?? livePm25);
    const offsetAqi = liveAqi - (raw[0]?.aqi ?? liveAqi);

    return raw.map((item) => {
      const h = item.horizon_hours;
      if (h === 0) {
        return {
          ...item,
          pm25: livePm25,
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
  }, [data, livePm25, liveAqi, liveWind, liveTemp]);

  const severe = data?.severe_alert ?? chartData.some((item) => item.aqi > 400);

  return (
    <section className="consensus-wrap" aria-label="Live consensus forecast">
      {severe && (
        <div className="severe-alert" role="alert">
          <AlertTriangle size={18} aria-hidden="true" />
          <span>⚠️ SEVERE POLLUTION ALERT: AQI projected to exceed 400 in the next 72 hours. Activating emergency response protocols.</span>
        </div>
      )}
      <div className="consensus-head">
        <div>
          <p className="eyebrow">five-source consensus</p>
          <h2 className="section__h section__h--sm">Delhi NCR live conditions</h2>
          <p className="section__lede section__lede--sm">Physics-informed projection anchored to current observations.</p>
        </div>
        <span className="source-count">
          Aggregated across {cityAggregate?.station_count ?? 43} stations + {data?.source_count ?? 2} meteorological feeds.
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
              {cityAggregate?.dominant_pollutant ? `Dominant ${cityAggregate.dominant_pollutant}` : "CPCB Max"}
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
              <span style={{ color: "var(--mist-dim)", font: "0.7rem var(--mono)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Temperature</span>
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
              <span style={{ color: "var(--mist-dim)", font: "0.7rem var(--mono)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Wind</span>
            </div>
            <strong style={{ fontSize: "1.8rem", fontWeight: 600, color: "var(--bone)", margin: "0.25rem 0 0.1rem" }}>
              {loading ? "—" : metric(liveWind, "")}
            </strong>
            <small style={{ color: "var(--mist-faint)", fontSize: "0.72rem" }}>km/h</small>
          </div>
        </article>
      </div>

      {/* 2 Lower Panels with Realism Shiny Borders */}
      <div className="consensus-panels">
        {/* Explainability Engine Panel */}
        <article className="realism-box explain-panel">
          <div className="realism-topglow" />
          <div className="realism-blob" />
          <div className="realism-inner">
            <div className="realism-inner-glow" />
            <p className="eyebrow">explainability engine</p>
            <h3 style={{ margin: "0.35rem 0 0.8rem", fontSize: "1.05rem", fontWeight: 500, color: "var(--bone)" }}>Why the model expects this</h3>
            <p style={{ color: "var(--mist)", lineHeight: 1.65, fontSize: "0.9rem", margin: 0 }}>
              {data?.explainability ?? "Waiting for the consensus engine to evaluate wind, temperature, and particulate conditions."}
            </p>
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
                <h3 style={{ margin: "0.35rem 0 0.8rem", fontSize: "1.05rem", fontWeight: 500, color: "var(--bone)" }}>72-hour PM2.5 and AQI outlook</h3>
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
"""

with open("webapp/src/components/ConsensusDashboard.tsx", "w", encoding="utf-8") as f:
    f.write(consensus_code)

# 2. Append CSS to console.css
css_rules = r"""
/* ========================================================
   REALISM / SHINY BORDERS DESIGN SYSTEM (FORECAST BOXES)
   ======================================================== */

/* Outer Box Container */
.realism-box {
  position: relative !important;
  padding: 2px !important;
  border-radius: 20px !important;
  background: radial-gradient(circle 600px at 85% -10%, #ffffff, rgba(255,255,255,0.3) 30%, #14171a 70%) !important;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.6) !important;
  transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.3s ease !important;
  border: none !important;
  box-sizing: border-box;
}

.realism-box:hover {
  transform: translateY(-4px) scale(1.02);
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.75) !important;
}

/* Top-Right White Specular Shine */
.realism-topglow {
  position: absolute;
  top: 0;
  right: 0;
  width: 60%;
  height: 55%;
  border-top-right-radius: 20px;
  box-shadow: 0 0 35px rgba(255, 255, 255, 0.32);
  pointer-events: none;
  z-index: 1;
  transition: all 0.3s ease-out;
}

.realism-box:hover .realism-topglow {
  box-shadow: 0 0 55px rgba(255, 255, 255, 0.5);
}

/* Bottom-Left Neon Ambient Light */
.realism-blob {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 75px;
  height: 55%;
  border-bottom-left-radius: 20px;
  background: radial-gradient(circle 90px at 0% 100%, #3fff75, rgba(0, 255, 128, 0.35), transparent);
  box-shadow: -4px 9px 40px rgba(0, 255, 45, 0.45);
  pointer-events: none;
  z-index: 1;
  transition: all 0.3s ease-out;
}

.realism-box:hover .realism-blob {
  width: 120px;
  box-shadow: -6px 10px 55px rgba(0, 255, 45, 0.65);
}

/* Inner Dark Content Area */
.realism-inner {
  position: relative;
  z-index: 10;
  border-radius: 18px;
  background: radial-gradient(circle 700px at 80% -50%, #1e242c, #0b0d10);
  padding: 1.15rem 1.25rem;
  overflow: hidden;
  transition: all 0.3s ease;
  height: 100%;
  width: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.consensus-card-inner {
  min-height: 7.6rem;
}

/* Inner Cyan Atmospheric Glow */
.realism-inner-glow {
  position: absolute;
  inset: 0;
  border-radius: 18px;
  background: radial-gradient(circle 220px at 0% 100%, rgba(0, 225, 255, 0.1), rgba(0, 0, 255, 0.05), transparent);
  pointer-events: none;
  z-index: 0;
}
"""

with open("webapp/src/styles/console.css", "r", encoding="utf-8") as f:
    console_css = f.read()

if "/* ========================================================\n   REALISM / SHINY BORDERS DESIGN SYSTEM" not in console_css:
    console_css += "\n" + css_rules
    with open("webapp/src/styles/console.css", "w", encoding="utf-8") as f:
        f.write(console_css)

print("Realism shiny borders applied to Delhi NCR Live Condition section boxes successfully!")
