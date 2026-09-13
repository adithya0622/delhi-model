import { ArrowLeft, CloudRain } from "lucide-react";
import { Atmosphere } from "@/components/Atmosphere";
import { CouplingLoop } from "@/components/CouplingLoop";
import { InversionStrip } from "@/components/InversionStrip";
import type { Cursor } from "@/hooks/useCursor";
import type { Panel } from "@/hooks/useForecastData";
import { useTranslation } from "@/i18n";
import type {
  CityAggregateResponse,
  ConsensusResponse,
  ForecastResponse,
  HourlyForecast,
  InversionStatus,
} from "@/lib/types";

interface AtmosphericDynamicsPageProps {
  forecast: Panel<ForecastResponse>;
  hour: HourlyForecast | null;
  cursor: Cursor;
  inversion?: Panel<InversionStatus[]>;
  consensus?: ConsensusResponse | null;
  cityAggregate?: CityAggregateResponse | null;
  onBack: () => void;
}

export function AtmosphericDynamicsPage({
  forecast,
  hour,
  cursor,
  inversion,
  consensus: _consensus,
  cityAggregate,
  onBack,
}: AtmosphericDynamicsPageProps) {
  const { t } = useTranslation();
  return (
    <div
      style={{
        minHeight: "100vh",
        backgroundColor: "var(--abyss)",
        color: "var(--bone)",
        paddingTop: "4.5rem",
      }}
    >
      {/* Top Navigation Bar */}
      <div
        style={{
          maxWidth: "1400px",
          margin: "0 auto",
          padding: "1rem var(--pad) 0.5rem",
        }}
      >
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "1rem",
          }}
        >
          <button
            type="button"
            className="btn btn--solid"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.6rem",
              padding: "0.5rem 0.95rem",
              background: "var(--slab)",
              border: "1px solid var(--hairline-2)",
              borderRadius: "6px",
              color: "var(--bone)",
              fontFamily: "var(--mono)",
              fontSize: "12px",
              cursor: "pointer",
              transition: "all 0.2s ease",
            }}
            onClick={onBack}
          >
            <ArrowLeft size={15} />
            <span>{t("common.backToOverview")}</span>
          </button>

          <div style={{ display: "flex", alignItems: "center", gap: "0.8rem" }}>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.4rem",
                padding: "4px 10px",
                background: "color-mix(in srgb, var(--live) 15%, transparent)",
                border: "1px solid color-mix(in srgb, var(--live) 40%, transparent)",
                borderRadius: "4px",
                fontFamily: "var(--mono)",
                fontSize: "11px",
                color: "var(--bone)",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              <CloudRain size={13} style={{ color: "var(--live)" }} />
              Atmospheric Physics &amp; Coupling
            </span>
          </div>
        </div>
      </div>

      {/* Main Content Modules */}
      <main style={{ maxWidth: "1400px", margin: "0 auto" }}>
        {/* Module 1: The Layer Air Trapped In */}
        <section id="atmosphere-column">
          <Atmosphere forecast={forecast} hour={hour} cursor={cursor} />
        </section>

        {/* Module 2: Chemistry Pushing Back on the Weather */}
        <section id="coupling-loop" style={{ borderTop: "1px solid var(--hairline)" }}>
          <CouplingLoop
            hour={hour}
            loading={forecast.status === "loading"}
            cityAggregate={cityAggregate}
            cursor={cursor.cursor}
          />
        </section>

        {/* Module 3: Thermal Inversion Watch & Lid */}
        <section id="inversion-watch" style={{ borderTop: "1px solid var(--hairline)" }}>
          {inversion && <InversionStrip inversion={inversion} cursor={cursor.cursor} />}
        </section>
      </main>
    </div>
  );
}
export default AtmosphericDynamicsPage;
