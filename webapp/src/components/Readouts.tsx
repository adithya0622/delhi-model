import { fixed, int, signed, compass } from "@/lib/format";
import type { HourlyForecast } from "@/lib/types";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslation } from "@/i18n";

interface ReadoutsProps {
  hour: HourlyForecast | null;
  loading: boolean;
}

/**
 * The readouts driven by the cursor, wrapped in a whole Realism Shiny Border container.
 */
export function Readouts({ hour, loading }: ReadoutsProps) {
  const { t } = useTranslation();
  const skel = loading && !hour;
  const val = (node: React.ReactNode) =>
    skel ? <Skeleton style={{ width: "3.4rem", height: "1.4rem" }} /> : node;

  /** Lid strength phrased from the hour's ΔT, so it agrees with the number shown. */
  const lidState = (dt: number): string => {
    if (dt <= 0.2) return t("atmosphere.noLidVentilated");
    if (dt < 2) return t("atmosphere.weakLid");
    if (dt < 4) return t("atmosphere.moderateLid");
    return t("atmosphere.strongLid");
  };

  return (
    <article className="realism-box" style={{ width: "100%", marginTop: "1.8rem" }}>
      <div className="realism-topglow" />
      <div
        className="realism-blob"
        style={{
          background: "radial-gradient(circle 120px at 0% 100%, #38bdf8, rgba(56, 189, 248, 0.4), transparent)",
          boxShadow: "-4px 9px 40px rgba(56, 189, 248, 0.4)",
        }}
      />
      <div
        className="realism-inner"
        style={{
          padding: "0",
          background: "radial-gradient(circle 700px at 80% -50%, #1e242c, #0b0d10)",
          borderRadius: "18px",
          overflow: "hidden",
        }}
      >
        <div className="realism-inner-glow" />
        <div className="readouts" style={{ margin: 0, border: "none", background: "transparent" }}>
          <div className="ro" style={{ background: "rgba(255, 255, 255, 0.02)", borderRight: "1px solid rgba(255, 255, 255, 0.06)" }}>
            <p className="ro__k">{t("atmosphere.mixingDepth")}</p>
            <p className="ro__v">
              {val(<span>{hour ? int(hour.pbl_height_m) : "—"}</span>)}
              <i>m</i>
            </p>
            <p className="ro__n">met model {hour ? int(hour.pbl_height_met_m) : "—"} m</p>
          </div>

          <div className="ro" style={{ background: "rgba(255, 255, 255, 0.02)", borderRight: "1px solid rgba(255, 255, 255, 0.06)" }}>
            <p className="ro__k">{t("atmosphere.depthRemoved")}</p>
            <p className="ro__v ro__v--warn">
              {val(<span>{hour ? fixed(hour.pbl_suppression_pct, 1) : "—"}</span>)}
              <i>%</i>
            </p>
            <p className="ro__n">{t("atmosphere.byAerosolShading")}</p>
          </div>

          <div className="ro" style={{ background: "rgba(255, 255, 255, 0.02)", borderRight: "1px solid rgba(255, 255, 255, 0.06)" }}>
            <p className="ro__k">{t("atmosphere.columnAod")}</p>
            <p className="ro__v">{val(<span>{hour ? fixed(hour.aerosol_optical_depth, 2) : "—"}</span>)}</p>
            <p className="ro__n">{t("atmosphere.aodSub")}</p>
          </div>

          <div className="ro" style={{ background: "rgba(255, 255, 255, 0.02)", borderRight: "1px solid rgba(255, 255, 255, 0.06)" }}>
            <p className="ro__k">{t("atmosphere.surfaceForcing")}</p>
            <p className="ro__v">
              {val(<span>{hour ? signed(hour.aerosol_sw_forcing_w_m2, 0) : "—"}</span>)}
              <i>W/m²</i>
            </p>
            <p className="ro__n">{t("atmosphere.withheldFromGround")}</p>
          </div>

          <div className="ro" style={{ background: "rgba(255, 255, 255, 0.02)", borderRight: "1px solid rgba(255, 255, 255, 0.06)" }}>
            <p className="ro__k">{t("consensus.wind")}</p>
            <p className="ro__v">
              {val(<span>{hour ? fixed(hour.wind_speed_ms, 1) : "—"}</span>)}
              <i>m/s</i>
            </p>
            <p className="ro__n">{hour ? compass(hour.wind_direction_deg) : "—"} at 850 hPa</p>
          </div>

          <div className="ro" style={{ background: "rgba(255, 255, 255, 0.02)" }}>
            <p className="ro__k">ΔT 925–1000 hPa</p>
            <p className="ro__v">
              {val(<span>{hour ? signed(hour.inversion_delta_t, 1) : "—"}</span>)}
              <i>°C</i>
            </p>
            <p className="ro__n">{hour ? lidState(hour.inversion_delta_t) : "—"}</p>
          </div>
        </div>
      </div>
    </article>
  );
}
