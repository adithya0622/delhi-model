import { useCallback, useEffect, useRef, useState } from "react";
import { getCityAggregate } from "@/lib/api";
import type { CityAggregateResponse } from "@/lib/types";

export interface CityAggregateState {
  data: CityAggregateResponse | null;
  status: "loading" | "ok" | "error";
  error: string | null;
  refresh: () => void;
}

export function useCityAggregate(): CityAggregateState {
  const [data, setData] = useState<CityAggregateResponse | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const ctrlRef = useRef<AbortController | null>(null);

  const fetchAggregate = useCallback(async () => {
    ctrlRef.current?.abort();
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;

    setStatus("loading");
    setError(null);

    try {
      const res = await getCityAggregate(ctrl.signal);
      setData(res);
      setStatus("ok");
    } catch (e: any) {
      if (e?.name === "AbortError") return;
      setError(e?.message || "Failed to fetch city aggregate");
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    fetchAggregate();
    // Poll every 60 seconds
    const timer = setInterval(fetchAggregate, 60_000);
    return () => {
      ctrlRef.current?.abort();
      clearInterval(timer);
    };
  }, [fetchAggregate]);

  return {
    data,
    status,
    error,
    refresh: fetchAggregate,
  };
}
