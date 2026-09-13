import { useCallback, useEffect, useRef, useState } from "react";

import {
  getHealth,
  getInversion,
  getMlForecast72hr,
  getOverview,
  getPlume,
  getStations,
} from "@/lib/api";
import type {
  CityOverview,
  InversionStatus,
  MlForecast72hrResponse,
  PlumeVectorsResponse,
  StationReading,
} from "@/lib/types";

export type PanelStatus = "loading" | "ok" | "error";

export interface Panel<T> {
  status: PanelStatus;
  data: T | null;
  error: string | null;
}

function loading<T>(): Panel<T> {
  return { status: "loading", data: null, error: null };
}
function ok<T>(data: T): Panel<T> {
  return { status: "ok", data, error: null };
}
function failed<T>(error: string): Panel<T> {
  return { status: "error", data: null, error };
}

export type StepKey = "api" | "met" | "inv" | "fire" | "obs";
export type StepState = "pending" | "ok" | "fail";

export const BOOT_STEP_ORDER: readonly StepKey[] = ["api", "met", "inv", "fire", "obs"];
export const BOOT_STEP_LABEL: Record<StepKey, string> = {
  api: "reach forecast service",
  met: "meteorology · coupled column",
  inv: "inversion diagnostics",
  fire: "fire detections · plume transport",
  obs: "live station network",
};

export interface BootState {
  steps: Record<StepKey, StepState>;
  message: string;
  error: string | null;
}

function freshBoot(): BootState {
  return {
    steps: { api: "pending", met: "pending", inv: "pending", fire: "pending", obs: "pending" },
    message: "reaching forecast service",
    error: null,
  };
}

export type Led = "on" | "off" | "pending";
export interface Feeds {
  met: Led;
  obs: Led;
  fire: Led;
}

export interface ForecastData {
  ready: boolean;
  boot: BootState;
  forecast: Panel<MlForecast72hrResponse>;
  inversion: Panel<InversionStatus[]>;
  plume: Panel<PlumeVectorsResponse>;
  overview: Panel<CityOverview>;
  stations: Panel<StationReading[]>;
  feeds: Feeds;
  refresh: () => void;
}

function errMsg(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function useForecastData(): ForecastData {
  const [ready, setReady] = useState(false);
  const [boot, setBoot] = useState<BootState>(freshBoot);
  const [forecast, setForecast] = useState<Panel<MlForecast72hrResponse>>(loading);
  const [inversion, setInversion] = useState<Panel<InversionStatus[]>>(loading);
  const [plume, setPlume] = useState<Panel<PlumeVectorsResponse>>(loading);
  const [overview, setOverview] = useState<Panel<CityOverview>>(loading);
  const [stations, setStations] = useState<Panel<StationReading[]>>(loading);
  const abortRef = useRef<AbortController | null>(null);

  const setStep = useCallback((key: StepKey, state: StepState) => {
    setBoot((current) => ({
      ...current,
      steps: { ...current.steps, [key]: state },
    }));
  }, []);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    setReady(false);
    setBoot(freshBoot());
    setForecast(loading());
    setInversion(loading());
    setPlume(loading());
    setOverview(loading());
    setStations(loading());

    try {
      await getHealth(signal);
      if (!signal.aborted) setStep("api", "ok");
    } catch {
      if (!signal.aborted) setStep("api", "fail");
    }

    if (signal.aborted) return;
    setBoot((current) => ({ ...current, message: "running ML forecast" }));
    try {
      const liveForecast = await getMlForecast72hr({}, signal);
      if (signal.aborted) return;
      setForecast(ok(liveForecast));
      setStep("met", "ok");
    } catch (error) {
      if (signal.aborted) return;
      const message = errMsg(error);
      setForecast(failed(message));
      setStep("met", "fail");
      setBoot((current) => ({
        ...current,
        message: "live forecast unavailable",
        error: `Live forecast unavailable (${message}).`,
      }));
    }
    setReady(true);

    const tasks = [
      getInversion(signal)
        .then((value) => {
          if (!signal.aborted) {
            setInversion(ok(value));
            setStep("inv", "ok");
          }
        })
        .catch((error) => {
          if (!signal.aborted) {
            setInversion(failed(errMsg(error)));
            setStep("inv", "fail");
          }
        }),
      getPlume(signal)
        .then((value) => {
          if (!signal.aborted) {
            setPlume(ok(value));
            setStep("fire", "ok");
          }
        })
        .catch((error) => {
          if (!signal.aborted) {
            setPlume(failed(errMsg(error)));
            setStep("fire", "fail");
          }
        }),
      getStations(signal)
        .then((value) => {
          if (!signal.aborted) {
            setStations(ok(value));
            setStep("obs", "ok");
          }
        })
        .catch((error) => {
          if (!signal.aborted) {
            setStations(failed(errMsg(error)));
            setStep("obs", "fail");
          }
        }),
      getOverview(signal)
        .then((value) => {
          if (!signal.aborted) setOverview(ok(value));
        })
        .catch((error) => {
          if (!signal.aborted) setOverview(failed(errMsg(error)));
        }),
    ];
    await Promise.allSettled(tasks);
  }, [setStep]);

  const refresh = useCallback(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  const ledFor = (status: PanelStatus): Led =>
    status === "ok" ? "on" : status === "error" ? "off" : "pending";

  return {
    ready,
    boot,
    forecast,
    inversion,
    plume,
    overview,
    stations,
    feeds: {
      met: ledFor(forecast.status),
      fire: ledFor(plume.status),
      obs: ledFor(stations.status),
    },
    refresh,
  };
}
