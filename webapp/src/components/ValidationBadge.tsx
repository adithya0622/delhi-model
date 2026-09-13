import { useEffect, useState } from "react";

import { getValidationBacktest } from "@/lib/api";
import type { BacktestReport } from "@/lib/types";

/**
 * ValidationBadge — displays the leak-free hindcast accuracy (MAE vs CAMS
 * reanalysis, skill vs persistence) as a compact, honest readout.
 *
 * Renders nothing while the first background computation is pending, so the
 * console never shows a fake number. Every value shown is produced by
 * `backtest_service.run_hindcast_backtest()` and labelled with its protocol.
 */
export function ValidationBadge() {
  const [report, setReport] = useState<BacktestReport | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getValidationBacktest(ctrl.signal)
      .then(setReport)
      .catch(() => setReport(null));
    return () => ctrl.abort();
  }, []);

  if (!report) return null;

  // First computation still running server-side: stay silent rather than
  // inventing a number — same policy as the plume map with zero FIRMS hits.
  if (!report.available || !report.pooled?.mae_ug_m3) return null;

  const pooled = report.pooled;
  const skill = report.skill_vs_persistence?.mae_skill_score;
  const windows = report.protocol?.windows ?? 0;

  return (
    <div
      className="validation-badge"
      title={`${report.protocol?.truth ?? "CAMS reanalysis"} — ${windows} hindcast windows of ${report.protocol?.window_hours ?? 72} h. Excludes ML, plume and nudging (see protocol).`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.5em",
        fontSize: "0.72rem",
        letterSpacing: "0.04em",
        opacity: 0.85,
        whiteSpace: "nowrap",
      }}
    >
      <span style={{ opacity: 0.6 }}>HINDCAST VALIDATION</span>
      <span>
        MAE {pooled.mae_ug_m3} µg/m³
        {pooled.bootstrap_mae_ci95 ? ` (95% CI ${pooled.bootstrap_mae_ci95.lo}–${pooled.bootstrap_mae_ci95.hi})` : ""}
      </span>
      {pooled.pearson_r != null && <span>r {pooled.pearson_r}</span>}
      {skill != null && (
        <span style={{ color: skill > 0 ? "var(--good, #4caf50)" : "var(--warn, #ff9800)" }}>
          skill vs persistence {skill > 0 ? "+" : ""}
          {skill}
        </span>
      )}
      <span style={{ opacity: 0.5 }}>vs CAMS · {windows}×{report.protocol?.window_hours ?? 72} h windows</span>
    </div>
  );
}

export default ValidationBadge;
