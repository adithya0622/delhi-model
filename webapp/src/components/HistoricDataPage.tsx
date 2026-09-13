import { ArrowLeft, History } from "lucide-react";
import { HistoricalData } from "@/components/HistoricalData";
import { Footer } from "@/components/Footer";
import type { Panel } from "@/hooks/useForecastData";
import { useTranslation } from "@/i18n";
import type {
  CityAggregateResponse,
  ConsensusResponse,
  ForecastResponse,
  HourlyForecast,
} from "@/lib/types";

interface HistoricDataPageProps {
  forecast: Panel<ForecastResponse>;
  hour: HourlyForecast | null;
  cursor: number;
  consensus?: ConsensusResponse | null;
  cityAggregate?: CityAggregateResponse | null;
  onBack: () => void;
}

export function HistoricDataPage({
  forecast,
  hour,
  cursor: _cursor,
  consensus,
  cityAggregate,
  onBack,
}: HistoricDataPageProps) {
  const { t } = useTranslation();
  const currentAqi =
    cityAggregate?.overall_aqi ??
    (consensus?.metrics ? Math.round(consensus.metrics.aqi) : (hour ? hour.aqi : 0));

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
              <History size={13} style={{ color: "var(--live)" }} />
              Retrospective Archive
            </span>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <main style={{ maxWidth: "1400px", margin: "0 auto" }}>
        <HistoricalData
          currentAqi={currentAqi}
          forecast={forecast}
          cityAggregate={cityAggregate}
        />
      </main>

      <Footer />
    </div>
  );
}
