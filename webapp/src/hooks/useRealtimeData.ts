import { useCallback, useEffect, useRef, useState } from "react";
import { getIqairRealtime, getWeatherapiRealtime } from "@/lib/api";
import type { IqairRealtimeResponse, WeatherapiRealtimeResponse } from "@/lib/api";

export interface RealtimeDataState {
  iqair: {
    data: IqairRealtimeResponse | null;
    status: "loading" | "ok" | "error";
    error: string | null;
  };
  weatherapi: {
    data: WeatherapiRealtimeResponse | null;
    status: "loading" | "ok" | "error";
    error: string | null;
  };
  refresh: () => void;
}

export function useRealtimeData(): RealtimeDataState {
  const [iqairData, setIqairData] = useState<IqairRealtimeResponse | null>(null);
  const [iqairStatus, setIqairStatus] = useState<"loading" | "ok" | "error">("loading");
  const [iqairError, setIqairError] = useState<string | null>(null);

  const [weatherapiData, setWeatherapiData] = useState<WeatherapiRealtimeResponse | null>(null);
  const [weatherapiStatus, setWeatherapiStatus] = useState<"loading" | "ok" | "error">("loading");
  const [weatherapiError, setWeatherapiError] = useState<string | null>(null);

  const ctrlRef = useRef<AbortController | null>(null);

  const fetchAll = useCallback(async () => {
    ctrlRef.current?.abort();
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;

    setIqairStatus("loading");
    setWeatherapiStatus("loading");
    setIqairError(null);
    setWeatherapiError(null);

    // Fetch IQAir
    try {
      const res = await getIqairRealtime(ctrl.signal);
      if (!ctrl.signal.aborted) {
        setIqairData(res);
        setIqairStatus("ok");
      }
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        setIqairError(e?.message || "Failed to fetch IQAir data");
        setIqairStatus("error");
      }
    }

    // Fetch WeatherAPI
    try {
      const res = await getWeatherapiRealtime(ctrl.signal);
      if (!ctrl.signal.aborted) {
        setWeatherapiData(res);
        setWeatherapiStatus("ok");
      }
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        setWeatherapiError(e?.message || "Failed to fetch WeatherAPI data");
        setWeatherapiStatus("error");
      }
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const timer = setInterval(fetchAll, 60_000); // Poll every 60 seconds
    return () => {
      ctrlRef.current?.abort();
      clearInterval(timer);
    };
  }, [fetchAll]);

  return {
    iqair: { data: iqairData, status: iqairStatus, error: iqairError },
    weatherapi: { data: weatherapiData, status: weatherapiStatus, error: weatherapiError },
    refresh: fetchAll,
  };
}