import { useCallback, useEffect, useRef, useState } from "react";
import { getConsensus } from "@/lib/api";
import type { AqiCategory, ConsensusResponse } from "@/lib/types";

function category(aqi: number): AqiCategory {
  if (aqi <= 50) return "Good";
  if (aqi <= 100) return "Moderate";
  if (aqi <= 150) return "Unhealthy for Sensitive Groups";
  if (aqi <= 200) return "Unhealthy";
  if (aqi <= 300) return "Very Unhealthy";
  return "Hazardous";
}

export function useConsensus() {
  const [data, setData] = useState<ConsensusResponse | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus("loading");
    setError(null);

    void getConsensus(controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        const hasT0 = response.forecast.some((f) => f.horizon_hours === 0);
        const forecast = hasT0
          ? response.forecast
          : [
              {
                horizon_hours: 0,
                timestamp: response.generated_at,
                pm25: response.metrics.pm25,
                aqi: response.metrics.aqi,
                category: category(response.metrics.aqi),
                wind_speed: response.metrics.wind,
                temperature: response.metrics.temp,
                rule: "Current",
                explanation: "Current consensus observation",
              },
              ...response.forecast,
            ];
        setData({ ...response, forecast });
        setStatus("ok");
      })
      .catch((reason) => {
        if (controller.signal.aborted) return;
        setStatus("error");
        setError(reason instanceof Error ? reason.message : String(reason));
      });
  }, []);

  useEffect(() => {
    refresh();
    return () => abortRef.current?.abort();
  }, [refresh]);

  return { data, status, error, refresh };
}
