import { useEffect, useMemo, useState } from "react";
import { BrainCircuit, RefreshCw } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { getChronosForecast } from "@/lib/api";
import { aqiColor } from "@/lib/aqi";
import type { ChronosForecastResponse, ChronosHour } from "@/lib/types";

/** Checkpoint hours rendered in the strip — +1h, +6h, +24h, +48h, +72h. */
const CHECKPOINTS = [0, 5, 23, 47, 71];

const POLLUTANT_LABELS: Record<string, string> = {
  pm2_5: "PM2.5",
  pm10: "PM10",
  no2: "NO₂",
  o3: "O₃",
  so2: "SO₂",
  co: "CO",
};

function fmtHour(timestamp: string): string {
  try {
    const d = new Date(timestamp);
    return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
  } catch {
    return "";
  }
}

/**
 * Foundation-model (Chronos T5) forecast panel.
 *
 * Deliberately self-fetching: the Chronos endpoint is the slow call (token
 * generation on CPU) and must not hold the console boot sequence hostage.
 * A failed load renders an honest inline error, never sample data.
 */
export function ChronosForecastPanel() {
  const [data, setData] = useState<ChronosForecastResponse | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setStatus("loading");
    setError(null);
    getChronosForecast(ctrl.signal)
      .then((payload) => {
        setData(payload);
        setStatus("ok");
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
        setStatus("error");
      });
    return () => ctrl.abort();
  }, [reloadKey]);

  const checkpoints = useMemo<ChronosHour[]>(() => {
    if (!data?.hourly?.length) return [];
    return CHECKPOINTS.map((i) => data.hourly[Math.min(i, data.hourly.length - 1)]).filter(Boolean);
  }, [data]);

  const verification = data?.verification ?? {};
  const comparison = verification.model_comparison ?? null;

  return (
    <section
      id="chronos-forecast"
      className="mx-auto w-full max-w-6xl px-4 py-10"
      aria-label="Chronos foundation model 72-hour forecast"
    >
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/5">
          <BrainCircuit className="h-5 w-5 text-sky-300" aria-hidden />
        </div>
        <div className="flex-1">
          <h2 className="text-lg font-semibold tracking-tight text-white/90">
            Foundation-Model Forecast · Next 72 Hours
          </h2>
          <p className="text-xs text-white/50">
            Amazon Chronos T5 — tokenised time-series: 4096-token vocabulary, 168 h context,
            autoregressive token generation with p10–p90 bands
          </p>
        </div>
        {data && (
          <span className="rounded-full border border-sky-400/20 bg-sky-400/10 px-3 py-1 text-[11px] font-medium text-sky-200">
            {data.fallback_used
              ? "fallback: v3/v4 ML (Chronos unavailable)"
              : String(data.model_name || "").includes("Chronos-2")
                ? "Chronos-2 · live"
                : "token model · live"}
          </span>
        )}
        <button
          type="button"
          onClick={() => setReloadKey((k) => k + 1)}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-white/60 transition hover:text-white"
          aria-label="Refresh foundation-model forecast"
        >
          <RefreshCw className={`h-4 w-4 ${status === "loading" ? "animate-spin" : ""}`} aria-hidden />
        </button>
      </header>

      {status === "loading" && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {CHECKPOINTS.map((i) => (
            <Skeleton key={i} className="h-40 rounded-2xl" />
          ))}
        </div>
      )}

      {status === "error" && (
        <p className="rounded-2xl border border-amber-400/20 bg-amber-400/5 px-4 py-3 text-xs text-amber-200/80">
          Foundation-model feed unavailable — {error}. The v3/v4 ML forecast above remains live.
        </p>
      )}

      {status === "ok" && data && checkpoints.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {checkpoints.map((h, idx) => (
              <article
                key={h.hour_index}
                className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 backdrop-blur"
              >
                <div className="flex items-baseline justify-between">
                  <span className="text-[11px] uppercase tracking-wider text-white/40">
                    {idx === 0 ? "Now+1h" : `+${h.hour_index}h`}
                  </span>
                  <span className="text-[11px] text-white/40">{fmtHour(h.timestamp)}</span>
                </div>
                <div
                  className="mt-2 text-4xl font-bold tabular-nums"
                  style={{ color: aqiColor(h.aqi_cpcb) }}
                >
                  {Math.round(h.aqi_cpcb)}
                </div>
                <div className="text-xs text-white/50">{h.aqi_category}</div>
                <div className="mt-3 space-y-1 text-[11px] text-white/60">
                  {(["pm2_5", "pm10", "o3", "no2"] as const).map((key) => {
                    const q = h.pollutants[key];
                    if (!q) return null;
                    const band =
                      q.p10 != null && q.p90 != null
                        ? `${Math.round(q.p10)}–${Math.round(q.p90)}`
                        : `${Math.round(q.p50)} µg/m³`;
                    return (
                      <div key={key} className="flex items-center justify-between gap-2">
                        <span>{POLLUTANT_LABELS[key]}</span>
                        <span className="tabular-nums text-white/80">{band}</span>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-3 border-t border-white/10 pt-2 text-[11px] text-white/50">
                  dominant: <span className="text-white/80">{h.dominant_pollutant}</span>
                </div>
              </article>
            ))}
          </div>

          <footer className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-1 text-[11px] text-white/40">
            <span>
              context {data.context_hours}h ·{" "}
              {data.vocabulary_size
                ? `vocab ${data.vocabulary_size.toLocaleString()} · `
                : "quantile heads · "}
              horizon {data.forecast_horizon_hours}h
            </span>
            {typeof verification.cpcb_aqi_mae === "number" && (
              <span>
                holdout CPCB AQI MAE <span className="text-white/70">{verification.cpcb_aqi_mae}</span>
                {typeof verification.persistence_cpcb_aqi_mae === "number" && (
                  <>
                    {" "}
                    vs persistence <span className="text-white/70">{verification.persistence_cpcb_aqi_mae}</span>
                  </>
                )}
              </span>
            )}
            {comparison && typeof comparison.chronos2_zero_shot_with_covariates?.cpcb_aqi_mae === "number" && (
              <span>
                Chronos-2 (zero-shot+covariates) MAE{" "}
                <span className="text-white/70">
                  {comparison.chronos2_zero_shot_with_covariates.cpcb_aqi_mae}
                </span>
              </span>
            )}
          </footer>

          {data.fallback_used && data.chronos_status?.reason && (
            <p className="mt-2 text-[11px] text-amber-200/60">{String(data.chronos_status.reason)}</p>
          )}
        </>
      )}
    </section>
  );
}
