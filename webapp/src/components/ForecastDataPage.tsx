import { ArrowLeft, Sparkles } from "lucide-react";
import { PollutantForecasts } from "@/components/PollutantForecasts";
import { Footer } from "@/components/Footer";
import type { Panel } from "@/hooks/useForecastData";
import { useTranslation } from "@/i18n";
import type {
  CityAggregateResponse,
  ConsensusResponse,
  ForecastResponse,
  HourlyForecast,
} from "@/lib/types";

interface ForecastDataPageProps {
  forecast: Panel<ForecastResponse>;
  hour: HourlyForecast | null;
  cursor: number;
  consensus?: ConsensusResponse | null;
  cityAggregate?: CityAggregateResponse | null;
  onBack: () => void;
}

export function ForecastDataPage({
  forecast,
  hour,
  cursor,
  consensus,
  cityAggregate,
  onBack,
}: ForecastDataPageProps) {
  const { t } = useTranslation();
  return (
    <div
      style={{
        minHeight: "100vh",
        backgroundColor: "var(--abyss)",
        color: "var(--bone)",
        paddingTop: "3.8rem",
      }}
    >
      {/* Sleek Top Navigation Bar */}
      <div
        style={{
          maxWidth: "1400px",
          margin: "0 auto",
          padding: "0.85rem var(--pad)",
          borderBottom: "1px solid var(--hairline)",
        }}
      >
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "0.8rem",
          }}
        >
          <button
            type="button"
            className="btn btn--solid"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.6rem",
              padding: "0.45rem 0.95rem",
              background: "var(--slab)",
              border: "1px solid var(--hairline-2)",
              borderRadius: "4px",
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
                borderRadius: "3px",
                fontFamily: "var(--mono)",
                fontSize: "11px",
                color: "var(--bone)",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              <Sparkles size={13} style={{ color: "var(--live)" }} />
              Forecast Particle Projections
            </span>
          </div>
        </div>
      </div>

      {/* Main Page Sections */}
      <main style={{ maxWidth: "1400px", margin: "0 auto" }}>
        <PollutantForecasts
          forecast={forecast}
          hour={hour}
          cursor={cursor}
          consensus={consensus}
          cityAggregate={cityAggregate}
        />
      </main>

      <Footer />
    </div>
  );
}
export default ForecastDataPage;
