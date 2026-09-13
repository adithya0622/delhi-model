import type { Panel } from "@/hooks/useForecastData";
import { aqiColor } from "@/lib/aqi";
import { clock, int } from "@/lib/format";
import type { CityOverview, StationReading } from "@/lib/types";
import { PanelMessage } from "@/components/ui/panel-message";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslation } from "@/i18n";
import { getTranslatedStationName, type StationLang } from "@/lib/stationTranslations";

interface StationsProps {
  stations: Panel<StationReading[]>;
  overview: Panel<CityOverview>;
}

export function Stations({ stations, overview }: StationsProps) {
  const { t, language } = useTranslation();
  const rows = (stations.data ?? []).slice().sort((a, b) => b.aqi - a.aqi); // worst first
  const ov = overview.data;

  const getCategoryLabel = (cat?: string) => {
    if (!cat) return "";
    switch (cat.toLowerCase()) {
      case "good": return t("hero.categories.good");
      case "satisfactory": return t("hero.categories.satisfactory");
      case "moderate": return t("hero.categories.moderate");
      case "poor": return t("hero.categories.poor");
      case "very poor": return t("hero.categories.veryPoor");
      case "severe": return t("hero.categories.severe");
      case "hazardous": return t("hero.categories.hazardous");
      default: return cat;
    }
  };

  const cityName = language === "ta" ? "தில்லி" : language === "hi" ? "दिल्ली" : "Delhi";
  const cityLine = ov
    ? `${cityName} ${int(ov.aqi)} · ${getCategoryLabel(ov.category)}${ov.updated ? ` · ${t("stations.updated")} ${clock(ov.updated)}` : ""}`
    : "";

  return (
    <section className="section section--stations" aria-labelledby="st-h">
      <div className="section__head">
        <div>
          <p className="eyebrow">{t("stations.groundTruth")}</p>
          <h2 className="section__h section__h--sm" id="st-h">
            {t("stations.title")}
          </h2>
          <p className="section__lede section__lede--sm">
            {t("stations.subtitle")}
          </p>
        </div>
        <p className="stations__city">{cityLine}</p>
      </div>

      {stations.status === "loading" ? (
        <div className="stations">
          {Array.from({ length: 8 }, (_, i) => (
            <div className="st" key={i}>
              <Skeleton style={{ width: "2.4rem", height: "1.3rem" }} />
              <div className="st__body" style={{ flex: 1 }}>
                <Skeleton style={{ width: "80%", height: "0.8rem" }} />
                <Skeleton style={{ width: "40%", height: "0.6rem", marginTop: "0.4rem" }} />
              </div>
            </div>
          ))}
        </div>
      ) : stations.status === "error" ? (
        <PanelMessage tone="warn">
          <b>{t("stations.openAqUnavailable")}</b>
        </PanelMessage>
      ) : rows.length === 0 ? (
        <PanelMessage>
          <b>{t("stations.noStations")}</b>
        </PanelMessage>
      ) : (
        <div className="stations">
          {rows.map((s) => (
            <div className="st" key={s.uid} title={s.dominant_pollutant ? `${t("hero.dominant")} ${s.dominant_pollutant}` : undefined}>
              <span className="st__aqi" style={{ ["--c" as string]: aqiColor(s.aqi) }}>
                {int(s.aqi)}
              </span>
              <span className="st__body">
                <span className="st__name">{getTranslatedStationName(s.name, (language as StationLang) || "en")}</span>
                <span className="st__cat">{getCategoryLabel(s.category)}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
