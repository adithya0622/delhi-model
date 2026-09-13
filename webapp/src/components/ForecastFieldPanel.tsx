import { useEffect, useMemo, useState } from "react";

import { aqiColor } from "@/lib/aqi";
import { getForecastField } from "@/lib/api";
import type { ForecastFieldResponse } from "@/lib/types";

/**
 * N-station forecast field: one coupled column per station, IDW-interpolated
 * onto a grid. Fetched once (stations carry the full 72h series); the hour
 * slider re-interpolates client-side with the same inverse-distance math, so
 * scrubbing is instant and costs no refetch. The grid is interpolation, not
 * advection between columns — the caption says so.
 */

const LON_MIN = 76.5;
const LON_MAX = 77.8;
const LAT_MIN = 28.0;
const LAT_MAX = 29.0;
const GRID_N_LAT = 8;
const GRID_N_LON = 10;

function idw(lat: number, lon: number, pts: Array<[number, number, number]>): number {
  let num = 0;
  let den = 0;
  for (const [plat, plon, pval] of pts) {
    if (Math.abs(plat - lat) < 1e-9 && Math.abs(plon - lon) < 1e-9) return pval;
    const d = Math.max(
      1e-6,
      Math.hypot((plat - lat) * 111.0, (plon - lon) * 111.0 * Math.cos((lat * Math.PI) / 180))
    );
    const w = 1 / (d * d);
    num += w * pval;
    den += w;
  }
  return den > 0 ? num / den : pts[0][2];
}

const x = (lon: number) => ((lon - LON_MIN) / (LON_MAX - LON_MIN)) * 100;
const y = (lat: number) => (1 - (lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * 80;

export function ForecastFieldPanel() {
  const [hour, setHour] = useState(0);
  const [data, setData] = useState<ForecastFieldResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getForecastField(12, 0)
      .then((value) => {
        if (live) setData(value);
      })
      .catch((err: unknown) => {
        if (live) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      live = false;
    };
  }, []);

  const cells = useMemo(() => {
    if (!data) return [];
    const pts: Array<[number, number, number]> = data.stations.map((s) => [
      s.lat,
      s.lon,
      s.hourly_aqi[Math.min(hour, s.hourly_aqi.length - 1)] ?? s.current_aqi,
    ]);
    if (pts.length === 0) return [];
    const out: Array<{ lat: number; lon: number; v: number }> = [];
    for (let i = 0; i < GRID_N_LAT; i += 1) {
      const lat = LAT_MIN + ((LAT_MAX - LAT_MIN) * i) / (GRID_N_LAT - 1);
      for (let j = 0; j < GRID_N_LON; j += 1) {
        const lon = LON_MIN + ((LON_MAX - LON_MIN) * j) / (GRID_N_LON - 1);
        out.push({ lat, lon, v: Math.round(idw(lat, lon, pts)) });
      }
    }
    return out;
  }, [data, hour]);

  const hourMax = useMemo(() => {
    if (!data) return 0;
    return Math.max(
      ...data.stations.map((s) => s.hourly_aqi[Math.min(hour, s.hourly_aqi.length - 1)] ?? 0)
    );
  }, [data, hour]);

  return (
    <section
      style={{
        maxWidth: "1180px",
        margin: "0 auto",
        padding: "0 1.5rem 2rem",
        color: "#f1f5f9",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      <div
        style={{
          fontSize: "11px",
          letterSpacing: "0.2em",
          color: "#38bdf8",
          fontWeight: 700,
          marginBottom: "0.4rem",
        }}
      >
        72-HOUR FORECAST FIELD · {data ? `${data.station_count} COUPLED COLUMNS` : "LOADING"}
      </div>
      <h2 style={{ margin: "0 0 0.5rem", fontSize: "1.4rem", fontWeight: 800 }}>
        NCR at +{hour}h — worst column AQI {hourMax}
      </h2>

      {error ? (
        <p style={{ color: "#f87171" }}>Field feed unavailable ({error}). Live stations above stay real.</p>
      ) : !data ? (
        <p style={{ color: "#94a3b8" }}>Solving 12 coupled columns…</p>
      ) : (
        <>
          <input
            type="range"
            min={0}
            max={71}
            value={hour}
            onChange={(e) => setHour(Number(e.target.value))}
            aria-label="Forecast hour"
            style={{ width: "100%", margin: "0.5rem 0 1rem" }}
          />
          <svg viewBox="0 0 100 80" style={{ width: "100%", borderRadius: "12px", background: "#0b1220" }}>
            {cells.map((c, k) => (
              <rect
                key={k}
                x={x(c.lon) - 100 / GRID_N_LON / 2}
                y={y(c.lat) - 80 / GRID_N_LAT / 2}
                width={100 / GRID_N_LON + 0.2}
                height={80 / GRID_N_LAT + 0.2}
                fill={aqiColor(c.v)}
                opacity={0.55}
              />
            ))}
            {data.stations.map((s) => {
              const aqi = s.hourly_aqi[Math.min(hour, s.hourly_aqi.length - 1)] ?? s.current_aqi;
              return (
                <g key={s.uid}>
                  <circle cx={x(s.lon)} cy={y(s.lat)} r={1.6} fill={aqiColor(aqi)} stroke="#fff" strokeWidth={0.25} />
                  <text x={x(s.lon) + 2} y={y(s.lat) + 1} fontSize={2.6} fill="#e2e8f0">
                    {s.name} {aqi}
                  </text>
                </g>
              );
            })}
          </svg>
          <p style={{ color: "#94a3b8", fontSize: "12px", marginTop: "0.6rem" }}>
            Physics-only N-column field, shared centre meteorology, per-station live anchor. Grid is IDW
            interpolation ({data.weather_source}, {data.profile_source} profile) — not advection between
            columns. Method: {data.method}
          </p>
        </>
      )}
    </section>
  );
}
