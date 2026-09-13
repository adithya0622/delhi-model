import { useEffect, useRef } from "react";

/**
 * Ambient particulate field. Density and tint track the scrubbed hour's PM2.5,
 * so the whole page literally hazes over as the air worsens. Purely decorative,
 * and not rendered at all under reduced motion (the CSS also hides `.haze`).
 */
export function HazeField({ pm25, reduced }: { pm25: number | null; reduced: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const pmRef = useRef(pm25 ?? 0);
  pmRef.current = pm25 ?? 0;

  useEffect(() => {
    if (reduced) return;
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    let w = 0;
    let h = 0;
    const MAX = 150;

    interface P {
      x: number;
      y: number;
      r: number;
      vx: number;
      vy: number;
      base: number;
    }
    let parts: P[] = [];

    const rand = (a: number, b: number) => a + Math.random() * (b - a);

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = Math.max(1, Math.floor(w * dpr));
      canvas.height = Math.max(1, Math.floor(h * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const seed = () => {
      parts = Array.from({ length: MAX }, () => ({
        x: rand(0, w),
        y: rand(0, h),
        r: rand(0.6, 2.4),
        vx: rand(-0.12, 0.12),
        vy: rand(-0.28, -0.05),
        base: rand(0.25, 1),
      }));
    };

    resize();
    seed();

    const draw = () => {
      const pm = pmRef.current;
      // Visible fraction ramps from a faint baseline to full at severe loads.
      const frac = Math.max(0.05, Math.min(1, pm / 260));
      const count = Math.round(MAX * frac);
      // Tint shifts cool mist → dusty ochre as concentration climbs.
      const warm = Math.min(1, pm / 320);
      const r = Math.round(140 + warm * 70);
      const g = Math.round(163 - warm * 40);
      const b = Math.round(182 - warm * 110);

      ctx.clearRect(0, 0, w, h);
      for (let i = 0; i < count; i++) {
        const p = parts[i];
        p.x += p.vx;
        p.y += p.vy;
        if (p.y < -4) p.y = h + 4;
        if (p.x < -4) p.x = w + 4;
        else if (p.x > w + 4) p.x = -4;
        const a = p.base * frac * 0.5;
        ctx.beginPath();
        ctx.fillStyle = `rgba(${r},${g},${b},${a.toFixed(3)})`;
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }
      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    const onResize = () => {
      resize();
      seed();
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, [reduced]);

  return <canvas ref={ref} className="haze" aria-hidden="true" />;
}
