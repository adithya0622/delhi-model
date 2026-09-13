import { fixed, int, signed } from "@/lib/format";
import type { CityAggregateResponse, HourlyForecast } from "@/lib/types";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslation } from "@/i18n";

interface CouplingLoopProps {
  hour: HourlyForecast | null;
  loading: boolean;
  cityAggregate?: CityAggregateResponse | null;
  cursor?: number;
}

/**
 * The return leg made visible: PM2.5 → column AOD → shortwave withheld →
 * surface cooling → mixing depth suppressed → back to PM2.5. Each hour is a
 * fixed point, and the Picard iteration count shows how hard it was to close.
 * Wrapped in a whole Realism Shiny Border container.
 */
export function CouplingLoop({ hour, loading, cityAggregate, cursor = 0 }: CouplingLoopProps) {
  const { t } = useTranslation();
  const isLiveNow = cursor === 0;
  const aggPm25 = cityAggregate?.sub_indices?.["PM2.5"]?.conc;
  const hourPm25 = hour?.sub_indices.find((s) => s.pollutant === "PM2.5")?.concentration ?? null;
  const pm25 = isLiveNow && aggPm25 != null ? aggPm25 : hourPm25;

  const skel = loading && !hour && !cityAggregate;

  // AOD dynamically coupled to the active particulate concentration
  const aod = hour
    ? isLiveNow && aggPm25 != null && hourPm25 && hourPm25 > 0
      ? hour.aerosol_optical_depth * (aggPm25 / hourPm25)
      : hour.aerosol_optical_depth
    : pm25
    ? pm25 * 0.0034
    : null;

  const iters = skel ? (
    <Skeleton style={{ width: "3rem", height: "3rem" }} />
  ) : (
    <span className="loop__iterN">{hour ? int(hour.feedback_iterations) : "1"}</span>
  );

  const v = (node: React.ReactNode) =>
    skel ? <Skeleton style={{ width: "3rem", height: "1.5rem" }} /> : node;

  return (
    <section className="section section--loop" aria-labelledby="loop-h">
      <div className="section__head">
        <div>
          <p className="eyebrow">{t("atmosphere.returnLeg")}</p>
          <h2 className="section__h" id="loop-h">
            {t("atmosphere.chemistryPushback")}
          </h2>
          <p className="section__lede">
            {t("atmosphere.couplingLede")}
          </p>
        </div>
        <div className="loop__iter">
          {iters}
          <span className="loop__iterK">
            {t("atmosphere.picardIterations")}
          </span>
        </div>
      </div>

      {/* Whole Realism Shiny Border Container for the 2-Way Loop */}
      <article className="realism-box" style={{ width: "100%", margin: "1.5rem 0" }}>
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
          <ol className="loop" style={{ margin: 0, border: "none", background: "transparent" }}>
            <li className="loop__node" data-node="pm" style={{ background: "rgba(255, 255, 255, 0.02)", border: "none", borderRight: "1px solid rgba(255, 255, 255, 0.06)" }}>
              <span className="loop__i">PM2.5</span>
              <span className="loop__v">
                {v(<span>{pm25 != null ? fixed(pm25, 1) : "—"}</span>)}
                <i>µg/m³</i>
              </span>
              <span className="loop__d">{t("atmosphere.surfaceLoad")}</span>
            </li>
            <li className="loop__node" data-node="aod" style={{ background: "rgba(255, 255, 255, 0.02)", border: "none", borderRight: "1px solid rgba(255, 255, 255, 0.06)" }}>
              <span className="loop__i">AOD</span>
              <span className="loop__v">{v(<span>{aod != null ? fixed(aod, 2) : "—"}</span>)}</span>
              <span className="loop__d">{t("atmosphere.extinctionDepth")}</span>
            </li>
            <li className="loop__node" data-node="sw" style={{ background: "rgba(255, 255, 255, 0.02)", border: "none", borderRight: "1px solid rgba(255, 255, 255, 0.06)" }}>
              <span className="loop__i">{t("atmosphere.shortwave")}</span>
              <span className="loop__v">
                {v(<span>{hour ? signed(hour.aerosol_sw_forcing_w_m2, 0) : "0"}</span>)}
                <i>W/m²</i>
              </span>
              <span className="loop__d">{t("atmosphere.withheldFromGround")}</span>
            </li>
            <li className="loop__node" data-node="dt" style={{ background: "rgba(255, 255, 255, 0.02)", border: "none", borderRight: "1px solid rgba(255, 255, 255, 0.06)" }}>
              <span className="loop__i">{t("atmosphere.surface")}</span>
              <span className="loop__v">
                {v(<span>{hour ? signed(hour.aerosol_dt_surface_c, 1) : "-0.1"}</span>)}
                <i>°C</i>
              </span>
              <span className="loop__d">{t("atmosphere.cooling")}</span>
            </li>
            <li className="loop__node loop__node--close" data-node="pbl" style={{ background: "rgba(255, 255, 255, 0.02)", border: "none" }}>
              <span className="loop__i">{t("atmosphere.mixingDepth")}</span>
              <span className="loop__v">
                {v(<span>{hour ? fixed(hour.pbl_suppression_pct, 1) : "0.0"}</span>)}
                <i>%</i>
              </span>
              <span className="loop__d">{t("atmosphere.suppressedBack")}</span>
            </li>
            <li className="loop__node loop__node--close" data-node="wind" style={{ background: "rgba(255, 255, 255, 0.02)", border: "none" }}>
              <span className="loop__i">{t("atmosphere.surfaceWind")}</span>
              <span className="loop__v">
                {v(<span>{hour ? fixed(hour.wind_effective_ms, 1) : "—"}</span>)}
                <i>m/s</i>
              </span>
              <span className="loop__d">{t("atmosphere.windFeedback")}</span>
            </li>
          </ol>
        </div>
      </article>

      <p className="loop__note">
        {t("atmosphere.couplingFootnote")}
      </p>
      <p className="loop__note">
        {t("atmosphere.windLegNote")}
      </p>
    </section>
  );
}
export default CouplingLoop;
