import { ArrowLeft, HeartPulse } from "lucide-react";
import { ExposureTracker } from "@/components/ExposureTracker";
import type { Panel } from "@/hooks/useForecastData";
import { useTranslation } from "@/i18n";
import type {
  CityAggregateResponse,
  ConsensusResponse,
  ForecastResponse,
  HourlyForecast,
} from "@/lib/types";

interface ExposureTrackerPageProps {
  forecast: Panel<ForecastResponse>;
  hour: HourlyForecast | null;
  cursor: number;
  consensus?: ConsensusResponse | null;
  cityAggregate?: CityAggregateResponse | null;
  onBack: () => void;
}

export function ExposureTrackerPage({
  forecast,
  hour,
  cursor: _cursor,
  consensus,
  cityAggregate,
  onBack,
}: ExposureTrackerPageProps) {
  const { t } = useTranslation();
  const pm25 =
    cityAggregate?.sub_indices?.["PM2.5"]?.conc ??
    (consensus?.metrics?.pm25 ?? (hour?.sub_indices.find((s) => s.pollutant === "PM2.5")?.concentration ?? 95));

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
              <HeartPulse size={13} style={{ color: "var(--live)" }} />
              Health Dosimetry &amp; Activity Planner
            </span>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <main style={{ maxWidth: "1400px", margin: "0 auto" }}>
        <section id="exposure-tracker">
          <ExposureTracker currentPm25={pm25} forecast={forecast} />
        </section>
      </main>
    </div>
  );
}
export default ExposureTrackerPage;
