import { BOOT_STEP_ORDER, type BootState } from "@/hooks/useForecastData";

/** Human labels for the boot steps, in the prototype's wording. */
const STEP_TEXT: Record<(typeof BOOT_STEP_ORDER)[number], string> = {
  api: "reach api",
  met: "meteorology + coupled column",
  inv: "inversion diagnostics",
  fire: "fire detections",
  obs: "station network",
};

interface BootProps {
  boot: BootState;
  ready: boolean;
}

/**
 * The boot overlay. The forecast integrates 72 coupled hours behind two upstream
 * calls, so this covers a real wait. Visibility is driven by the document's
 * `data-state` (CSS fades it out once ready); this component only paints staging.
 */
export function Boot({ boot, ready }: BootProps) {
  const done = BOOT_STEP_ORDER.filter((k) => boot.steps[k] === "ok").length;
  const progress = ready ? 1 : done / BOOT_STEP_ORDER.length;

  return (
    <div className="boot" id="boot" aria-hidden={ready}>
      <div className="boot__inner">
        <p className="boot__mark">
          NCR<span>·</span>72
        </p>
        <p className="boot__msg">{boot.message}</p>
        <div className="boot__bar">
          <i style={{ width: `${Math.round(progress * 100)}%` }} />
        </div>
        <ol className="boot__steps">
          {BOOT_STEP_ORDER.map((k) => (
            <li key={k} data-step={k} data-ok={boot.steps[k] === "ok" ? "1" : boot.steps[k] === "fail" ? "0" : undefined}>
              {STEP_TEXT[k]}
            </li>
          ))}
        </ol>
        {boot.error ? <p className="boot__err">{boot.error}</p> : null}
      </div>
    </div>
  );
}
