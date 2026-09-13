import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The single 0..max hour cursor shared by every panel (atmosphere, readouts,
 * inversion strip, plume, hero). One source of truth so the whole console reads
 * the same hour.
 *
 * Interaction surface:
 *   - setCursor / setFromRatio  → pointer drag on the cross-section
 *   - onKeyDown                 → ←/→ = ±1h, PgUp/PgDn = ±6h, Home/End = 0/max
 *   - goNow                     → jump to hour 0 (the present)
 *   - toggle / play / stop      → autoplay "Sweep 72h" (rAF, single pass)
 *
 * Autoplay is a full 0→max sweep over SWEEP_MS. Under reduced motion it collapses
 * to an instant jump to max instead of animating.
 */

const SWEEP_MS = 9000;

function clampInt(v: number, max: number): number {
  if (Number.isNaN(v)) return 0;
  return Math.max(0, Math.min(max, Math.round(v)));
}

export interface Cursor {
  cursor: number;
  max: number;
  playing: boolean;
  setCursor: (i: number) => void;
  /** Set from a 0..1 position along the time axis (pointer drag). */
  setFromRatio: (t: number) => void;
  goNow: () => void;
  play: () => void;
  stop: () => void;
  toggle: () => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
}

export function useCursor(max: number, reducedMotion: boolean): Cursor {
  const [cursor, setCursorState] = useState(0);
  const [playing, setPlaying] = useState(false);

  const rafRef = useRef<number | null>(null);
  const startTsRef = useRef<number>(0);

  // Keep the cursor valid when the data length (max) changes.
  useEffect(() => {
    setCursorState((c) => clampInt(c, max));
  }, [max]);

  const cancelRaf = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    cancelRaf();
    setPlaying(false);
  }, [cancelRaf]);

  const setCursor = useCallback(
    (i: number) => {
      // Any explicit move ends an in-flight sweep.
      cancelRaf();
      setPlaying(false);
      setCursorState(clampInt(i, max));
    },
    [cancelRaf, max],
  );

  const setFromRatio = useCallback(
    (t: number) => {
      cancelRaf();
      setPlaying(false);
      setCursorState(clampInt(t * max, max));
    },
    [cancelRaf, max],
  );

  const goNow = useCallback(() => setCursor(0), [setCursor]);

  const play = useCallback(() => {
    if (reducedMotion) {
      // No animation budget — jump to the far end so the whole horizon is shown.
      setCursorState(max);
      return;
    }
    cancelRaf();
    setPlaying(true);
    startTsRef.current = performance.now();
    setCursorState(0);
    const step = (ts: number) => {
      const t = Math.min(1, (ts - startTsRef.current) / SWEEP_MS);
      setCursorState(clampInt(t * max, max));
      if (t >= 1) {
        rafRef.current = null;
        setPlaying(false);
        return;
      }
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
  }, [cancelRaf, max, reducedMotion]);

  const toggle = useCallback(() => {
    if (playing) stop();
    else play();
  }, [playing, play, stop]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      let next: number | null = null;
      switch (e.key) {
        case "ArrowLeft":
        case "ArrowDown":
          next = cursor - 1;
          break;
        case "ArrowRight":
        case "ArrowUp":
          next = cursor + 1;
          break;
        case "PageDown":
          next = cursor - 6;
          break;
        case "PageUp":
          next = cursor + 6;
          break;
        case "Home":
          next = 0;
          break;
        case "End":
          next = max;
          break;
        default:
          return;
      }
      e.preventDefault();
      setCursor(next);
    },
    [cursor, max, setCursor],
  );

  // Tidy up any running sweep on unmount.
  useEffect(() => cancelRaf, [cancelRaf]);

  return { cursor, max, playing, setCursor, setFromRatio, goNow, play, stop, toggle, onKeyDown };
}
