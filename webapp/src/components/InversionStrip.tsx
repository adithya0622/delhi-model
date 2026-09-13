import type { Panel } from "@/hooks/useForecastData";
import { signed } from "@/lib/format";
import type { InversionStatus } from "@/lib/types";
import { PanelMessage } from "@/components/ui/panel-message";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslation } from "@/i18n";

interface InversionStripProps {
  inversion: Panel<InversionStatus[]>;
  cursor: number;
}

export function InversionStrip({ inversion, cursor }: InversionStripProps) {
  const { t } = useTranslation();
  const series = inversion.data ?? [];
  const idx = Math.max(0, Math.min(series.length - 1, cursor));
  const cur = series[idx] ?? null;
  const lidHours = series.filter((s) => s.inversion_present).length;

  // Calculate dynamic heights based on delta_t profile
  const dtValues = series.map((s) => s.delta_t_celsius);
  const minDt = dtValues.length ? Math.min(...dtValues) : -8;
  const maxDt = dtValues.length ? Math.max(...dtValues) : 4;
  const range = maxDt - minDt || 1;

  const getBarStyle = (s: InversionStatus) => {
    // Dynamic height representing thermal profile (18% - 100%)
    const heightPercent = Math.max(18, Math.min(100, Math.round(((s.delta_t_celsius - minDt) / range) * 76 + 20)));
    
    let bg = "var(--hairline-2)";
    if (s.severity === "Strong") {
      bg = "var(--aqi-5)";
    } else if (s.severity === "Moderate") {
      bg = "var(--aqi-4)";
    } else if (s.severity === "Weak") {
      bg = "var(--aqi-3)";
    } else if (s.delta_t_celsius >= -1.0) {
      bg = "#10b981"; // Stable / near-neutral
    } else {
      // Normal lapse rate: dynamic cool cyan/blue gradient based on height
      const intensity = Math.round(30 + ((s.delta_t_celsius - minDt) / range) * 45);
      bg = `rgba(56, 189, 248, ${intensity / 100})`;
    }

    return {
      height: `${heightPercent}%`,
      background: bg,
    };
  };

  return (
    <section className="section section--inv" aria-labelledby="inv-h">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "0.5rem" }}>
        <div>
          <p className="eyebrow">lid</p>
          <h2 className="section__h section__h--sm" id="inv-h">
            {t("atmosphere.inversionStrength")}
          </h2>
        </div>
        <div style={{ marginTop: "0.25rem" }}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.4rem",
              padding: "0.25rem 0.65rem",
              borderRadius: "4px",
              fontSize: "11px",
              fontFamily: "var(--mono)",
              background: lidHours > 0 ? "rgba(239, 68, 68, 0.15)" : "rgba(56, 189, 248, 0.12)",
              color: lidHours > 0 ? "var(--aqi-5)" : "#38bdf8",
              border: `1px solid ${lidHours > 0 ? "rgba(239, 68, 68, 0.3)" : "rgba(56, 189, 248, 0.25)"}`,
            }}
          >
            <span
              style={{
                width: "6px",
                height: "6px",
                borderRadius: "50%",
                background: lidHours > 0 ? "var(--aqi-5)" : "#38bdf8",
              }}
            />
            {lidHours > 0 ? t("atmosphere.inversionActive") : t("atmosphere.inversionNormal")}
          </span>
        </div>
      </div>

      <p className="section__lede section__lede--sm">
        {t("atmosphere.inversionLede")}
      </p>

      {inversion.status === "error" ? (
        <PanelMessage tone="warn" style={{ marginTop: "2rem" }}>
          <b>Meteorology feed unavailable.</b> The inversion series could not be retrieved from the
          upstream met provider.
        </PanelMessage>
      ) : inversion.status === "loading" ? (
        <>
          <div className="inv__strip" aria-hidden="true">
            {Array.from({ length: 72 }, (_, i) => (
              <Skeleton key={i} className="inv__cell" style={{ height: "40%" }} />
            ))}
          </div>
          <div className="inv__axis">
            <span>{t("atmosphere.now")}</span>
            <span>+24</span>
            <span>+48</span>
            <span>+72 h</span>
          </div>
        </>
      ) : (
        <>
          <div className="inv__strip" aria-hidden="true">
            {series.map((s, i) => {
              const bar = getBarStyle(s);
              return (
                <div
                  key={i}
                  className={`inv__cell${i === idx ? " is-cursor" : ""}`}
                  data-sev={s.severity}
                  style={bar}
                  title={`Hour +${i}: ΔT ${signed(s.delta_t_celsius, 1)}°C (${s.severity === "None" ? "Normal lapse rate" : `${s.severity} inversion`})`}
                />
              );
            })}
          </div>
          <div className="inv__axis">
            <span>{t("atmosphere.now")}</span>
            <span>+24</span>
            <span>+48</span>
            <span>+72 h</span>
          </div>
        </>
      )}

      <dl className="inv__stats">
        <div>
          <dt>{t("atmosphere.deltaTCursor")}</dt>
          <dd>{cur ? `${signed(cur.delta_t_celsius, 1)} °C` : "—"}</dd>
        </div>
        <div>
          <dt>{t("atmosphere.severity")}</dt>
          <dd>{cur ? (cur.severity === "None" ? t("atmosphere.noneNormalLapse") : cur.severity) : "—"}</dd>
        </div>
        <div>
          <dt>{t("atmosphere.lapseRate")}</dt>
          <dd>{cur ? `${signed(cur.lapse_rate_k_per_km, 1)} K/km` : "—"}</dd>
        </div>
        <div>
          <dt>{t("atmosphere.hoursWithLid")}</dt>
          <dd>{series.length ? `${lidHours} ${t("map.ofUnits")} ${series.length}` : "—"}</dd>
        </div>
      </dl>
    </section>
  );
}
