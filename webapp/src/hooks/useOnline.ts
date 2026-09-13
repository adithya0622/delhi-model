import { useEffect, useState } from "react";

/**
 * Tracks `navigator.onLine`, updating on the browser's `online` / `offline`
 * events. The station map uses this to choose its renderer in `auto` mode:
 * real Leaflet tiles when connected, the self-contained Canvas schematic when
 * not. SSR-safe (assumes online when `navigator` is absent).
 */
export function useOnline(): boolean {
  const [online, setOnline] = useState(() =>
    typeof navigator === "undefined" ? true : navigator.onLine,
  );

  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  return online;
}
