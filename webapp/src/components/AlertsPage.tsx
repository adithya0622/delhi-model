import { useMemo, useState } from "react";
import {
  Bell,
  ArrowLeft,
  Sliders,
  CheckCheck,
  AlertTriangle,
  Flame,
  Factory,
  TrendingUp,
  Activity,
  Heart,
  MapPin,
  Clock,
  ShieldCheck,
  ChevronRight,
  ShieldAlert,
} from "lucide-react";
import type { Panel } from "@/hooks/useForecastData";
import type {
  CityAggregateResponse,
  ConsensusResponse,
  ForecastResponse,
  HourlyForecast,
  IndustryRecord,
  PlumeVectorsResponse,
  StationReading,
} from "@/lib/types";
import {
  evaluateAlerts,
  loadAlertSettings,
  saveAlertSettings,
  markAlertAsRead,
  markAllAlertsAsRead,
  type AlertItem,
  type AlertSeverity,
  type AlertSettings,
} from "@/lib/alertsEngine";
import type { AlertLanguage } from "@/lib/alertTranslations";
import { ALERT_TRANSLATIONS } from "@/lib/alertTranslations";
import { AlertDetailModal } from "@/components/alerts/AlertDetailModal";
import { AlertSettingsModal } from "@/components/alerts/AlertSettingsModal";
import { useTranslation } from "@/i18n";

interface AlertsPageProps {
  cityAggregate?: CityAggregateResponse | null;
  stations?: Panel<StationReading[]> | StationReading[];
  forecast?: Panel<ForecastResponse> | ForecastResponse;
  hour?: HourlyForecast | null;
  plume?: Panel<PlumeVectorsResponse> | PlumeVectorsResponse;
  consensus?: ConsensusResponse | null;
  industries?: IndustryRecord[];
  onBack: () => void;
  onNavigate?: (page: any) => void;
}

export function AlertsPage({
  cityAggregate,
  stations: stationsProp,
  forecast: forecastProp,
  hour,
  plume: plumeProp,
  consensus,
  industries = [],
  onBack,
  onNavigate,
}: AlertsPageProps) {
  const { language, setLanguage } = useTranslation();
  const [settings, setSettings] = useState<AlertSettings>(() => loadAlertSettings());
  const [showSettings, setShowSettings] = useState(false);
  const [selectedAlert, setSelectedAlert] = useState<AlertItem | null>(null);
  const [severityFilter, setSeverityFilter] = useState<"ALL" | AlertSeverity>("ALL");

  const t = ALERT_TRANSLATIONS[language] || ALERT_TRANSLATIONS.en;

  // Unpack Panel wrappers safely
  const stationList = Array.isArray(stationsProp)
    ? stationsProp
    : stationsProp && "data" in stationsProp && Array.isArray(stationsProp.data)
    ? stationsProp.data
    : [];

  const forecastData =
    forecastProp && "data" in forecastProp
      ? (forecastProp.data as ForecastResponse | null)
      : (forecastProp as ForecastResponse | null);

  const plumeData =
    plumeProp && "data" in plumeProp
      ? (plumeProp.data as PlumeVectorsResponse | null)
      : (plumeProp as PlumeVectorsResponse | null);

  // Evaluate alerts reactively from real data
  const { activeAlerts, earlierAlerts, criticalCount } = useMemo(() => {
    return evaluateAlerts({
      cityAggregate,
      stations: stationList,
      forecast: forecastData,
      currentHour: hour,
      plume: plumeData,
      consensus,
      industries,
      userSettings: settings,
      language: (language as "en" | "hi" | "ta"),
    });
  }, [cityAggregate, stationList, forecastData, hour, plumeData, consensus, industries, settings, language]);

  const filteredActiveAlerts = useMemo(() => {
    if (severityFilter === "ALL") return activeAlerts;
    return activeAlerts.filter((a) => a.severity === severityFilter);
  }, [activeAlerts, severityFilter]);

  const handleMarkAllRead = () => {
    markAllAlertsAsRead(activeAlerts.map((a) => a.id));
    setSettings((prev) => ({ ...prev }));
  };

  const handleOpenDetail = (alert: AlertItem) => {
    markAlertAsRead(alert.id);
    setSelectedAlert(alert);
  };

  const handleSaveSettings = (newSettings: AlertSettings) => {
    setSettings(newSettings);
    saveAlertSettings(newSettings);
  };

  // Severity danger-level styling configuration
  const severityConfig: Record<
    AlertSeverity,
    {
      border: string;
      borderLeft: string;
      bg: string;
      text: string;
      glow: string;
      dangerScore: string;
      dangerLabel: string;
      dangerColor: string;
      filledBars: number;
    }
  > = {
    CRITICAL: {
      border: "rgba(239, 68, 68, 0.7)",
      borderLeft: "6px solid #ef4444",
      bg: "linear-gradient(135deg, rgba(48, 12, 18, 0.88) 0%, rgba(15, 23, 42, 0.95) 100%)",
      text: "#fca5a5",
      glow: "0 8px 32px rgba(239, 68, 68, 0.28), inset 0 0 20px rgba(239, 68, 68, 0.08)",
      dangerScore: "9.5/10",
      dangerLabel: "CRITICAL DANGER",
      dangerColor: "#ef4444",
      filledBars: 5,
    },
    HIGH: {
      border: "rgba(249, 115, 22, 0.65)",
      borderLeft: "6px solid #f97316",
      bg: "linear-gradient(135deg, rgba(38, 22, 12, 0.88) 0%, rgba(15, 23, 42, 0.95) 100%)",
      text: "#fdba74",
      glow: "0 8px 26px rgba(249, 115, 22, 0.22), inset 0 0 16px rgba(249, 115, 22, 0.06)",
      dangerScore: "7.5/10",
      dangerLabel: "HIGH DANGER",
      dangerColor: "#f97316",
      filledBars: 4,
    },
    MODERATE: {
      border: "rgba(234, 179, 8, 0.55)",
      borderLeft: "6px solid #eab308",
      bg: "linear-gradient(135deg, rgba(32, 28, 12, 0.88) 0%, rgba(15, 23, 42, 0.95) 100%)",
      text: "#fde047",
      glow: "0 6px 22px rgba(234, 179, 8, 0.16), inset 0 0 14px rgba(234, 179, 8, 0.04)",
      dangerScore: "5.0/10",
      dangerLabel: "MODERATE RISK",
      dangerColor: "#eab308",
      filledBars: 3,
    },
    LOW: {
      border: "rgba(34, 197, 94, 0.45)",
      borderLeft: "6px solid #22c55e",
      bg: "linear-gradient(135deg, rgba(12, 32, 22, 0.88) 0%, rgba(15, 23, 42, 0.95) 100%)",
      text: "#86efac",
      glow: "0 6px 18px rgba(34, 197, 94, 0.14), inset 0 0 12px rgba(34, 197, 94, 0.03)",
      dangerScore: "2.5/10",
      dangerLabel: "LOW RISK",
      dangerColor: "#22c55e",
      filledBars: 1,
    },
    INFO: {
      border: "rgba(56, 189, 248, 0.45)",
      borderLeft: "6px solid #38bdf8",
      bg: "linear-gradient(135deg, rgba(12, 26, 42, 0.88) 0%, rgba(15, 23, 42, 0.95) 100%)",
      text: "#7dd3fc",
      glow: "0 6px 18px rgba(56, 189, 248, 0.14), inset 0 0 12px rgba(56, 189, 248, 0.03)",
      dangerScore: "1.0/10",
      dangerLabel: "ADVISORY",
      dangerColor: "#38bdf8",
      filledBars: 1,
    },
  };

  const getCategoryIcon = (cat: string) => {
    switch (cat) {
      case "AIR_QUALITY":
        return <AlertTriangle size={15} />;
      case "RAPID_RISE":
        return <TrendingUp size={15} />;
      case "INDUSTRIAL":
        return <Factory size={15} />;
      case "FIRE_SMOKE":
        return <Flame size={15} />;
      case "FORECAST":
        return <Activity size={15} />;
      case "EXPOSURE":
        return <Heart size={15} />;
      default:
        return <AlertTriangle size={15} />;
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        backgroundColor: "var(--abyss)",
        color: "var(--bone)",
        paddingTop: "4.8rem",
        paddingBottom: "4rem",
      }}
    >
      <div
        style={{
          maxWidth: "1320px",
          margin: "0 auto",
          padding: "0 clamp(1rem, 3vw, 2.5rem)",
        }}
      >
        {/* Top Action Nav Row */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "1rem",
            marginBottom: "1.8rem",
          }}
        >
          <button
            type="button"
            className="btn btn--solid"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.55rem",
              padding: "0.5rem 1rem",
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
            <ArrowLeft size={14} />
            <span>{t.backToOverview}</span>
          </button>

          {/* Right Top Controls: Language Switcher, Settings, Mark Read */}
          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
            {/* Language Selector */}
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "3px",
                padding: "3px",
                background: "rgba(15, 23, 42, 0.7)",
                border: "1px solid rgba(255, 255, 255, 0.12)",
                borderRadius: "6px",
              }}
            >
              {(["en", "hi", "ta"] as AlertLanguage[]).map((lang) => (
                <button
                  key={lang}
                  type="button"
                  onClick={() => setLanguage(lang)}
                  style={{
                    padding: "3px 8px",
                    borderRadius: "4px",
                    background: language === lang ? "rgba(168, 85, 247, 0.35)" : "transparent",
                    border: language === lang ? "1px solid #a855f7" : "1px solid transparent",
                    color: language === lang ? "#FFFFFF" : "#94a3b8",
                    fontFamily: "var(--mono)",
                    fontSize: "10.5px",
                    fontWeight: 600,
                    cursor: "pointer",
                    textTransform: "uppercase",
                  }}
                >
                  {lang === "en" ? "EN" : lang === "hi" ? "हिन्दी" : "தமிழ்"}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={handleMarkAllRead}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.4rem",
                padding: "0.45rem 0.85rem",
                background: "rgba(255, 255, 255, 0.05)",
                border: "1px solid rgba(255, 255, 255, 0.12)",
                borderRadius: "6px",
                color: "#cbd5e1",
                fontFamily: "var(--mono)",
                fontSize: "11.5px",
                cursor: "pointer",
                transition: "all 0.2s ease",
              }}
            >
              <CheckCheck size={13} style={{ color: "#38bdf8" }} />
              <span>{t.markAllRead}</span>
            </button>

            <button
              type="button"
              onClick={() => setShowSettings(true)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.4rem",
                padding: "0.45rem 0.85rem",
                background: "rgba(168, 85, 247, 0.15)",
                border: "1px solid rgba(168, 85, 247, 0.35)",
                borderRadius: "6px",
                color: "#c084fc",
                fontFamily: "var(--mono)",
                fontSize: "11.5px",
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 0.2s ease",
              }}
            >
              <Sliders size={13} />
              <span>{t.alertSettings}</span>
            </button>
          </div>
        </div>

        {/* Header Hero Banner with Dynamic Danger Level Glow */}
        <div
          style={{
            marginBottom: "2rem",
            padding: "clamp(1.2rem, 3vw, 1.8rem)",
            background:
              criticalCount > 0
                ? "linear-gradient(135deg, rgba(60, 15, 25, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%)"
                : "linear-gradient(135deg, rgba(30, 27, 75, 0.5) 0%, rgba(15, 23, 42, 0.8) 100%)",
            border: `1px solid ${criticalCount > 0 ? "rgba(239, 68, 68, 0.5)" : "rgba(168, 85, 247, 0.3)"}`,
            borderRadius: "14px",
            boxShadow:
              criticalCount > 0
                ? "0 12px 36px -8px rgba(239, 68, 68, 0.35)"
                : "0 12px 36px -8px rgba(0, 0, 0, 0.5)",
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "1.2rem",
          }}
        >
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.4rem" }}>
              <div
                style={{
                  width: "28px",
                  height: "28px",
                  borderRadius: "6px",
                  background: criticalCount > 0 ? "rgba(239, 68, 68, 0.25)" : "rgba(168, 85, 247, 0.25)",
                  border: `1px solid ${criticalCount > 0 ? "#ef4444" : "#a855f7"}`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#FFFFFF",
                }}
              >
                {criticalCount > 0 ? <ShieldAlert size={16} /> : <Bell size={15} />}
              </div>
              <h1
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: "clamp(18px, 2.5vw, 24px)",
                  fontWeight: 700,
                  color: "#FFFFFF",
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  margin: 0,
                }}
              >
                {t.alertsTitle}
              </h1>
            </div>
            <p style={{ margin: 0, fontSize: "13px", color: "#94a3b8", maxWidth: "680px", lineHeight: 1.5 }}>
              {t.alertsSubtitle}
            </p>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "6px 12px",
              background: "rgba(0, 0, 0, 0.35)",
              borderRadius: "8px",
              border: "1px solid rgba(255, 255, 255, 0.1)",
              fontFamily: "var(--mono)",
              fontSize: "11px",
              color: "#38bdf8",
            }}
          >
            <span
              style={{
                width: "7px",
                height: "7px",
                borderRadius: "50%",
                background: "#22c55e",
                boxShadow: "0 0 8px #22c55e",
              }}
            />
            <span>43 CAAQMS Real-Time Sensors Active</span>
          </div>
        </div>

        {/* 4 Compact Summary Metrics */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "1rem",
            marginBottom: "2.4rem",
          }}
        >
          {/* 1. Active Alerts */}
          <div
            style={{
              padding: "1.1rem 1.2rem",
              background: "rgba(15, 23, 42, 0.75)",
              border: "1px solid rgba(255, 255, 255, 0.1)",
              borderRadius: "10px",
              backdropFilter: "blur(8px)",
            }}
          >
            <div style={{ fontSize: "11px", fontFamily: "var(--mono)", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "0.3rem" }}>
              {t.summaryActive}
            </div>
            <div style={{ fontSize: "28px", fontWeight: 700, fontFamily: "var(--mono)", color: "#FFFFFF" }}>
              {activeAlerts.length}
            </div>
          </div>

          {/* 2. New Today */}
          <div
            style={{
              padding: "1.1rem 1.2rem",
              background: "rgba(15, 23, 42, 0.75)",
              border: "1px solid rgba(255, 255, 255, 0.1)",
              borderRadius: "10px",
              backdropFilter: "blur(8px)",
            }}
          >
            <div style={{ fontSize: "11px", fontFamily: "var(--mono)", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "0.3rem" }}>
              {t.summaryToday}
            </div>
            <div style={{ fontSize: "28px", fontWeight: 700, fontFamily: "var(--mono)", color: "#c084fc" }}>
              {activeAlerts.length + earlierAlerts.length}
            </div>
          </div>

          {/* 3. Critical Alerts */}
          <div
            style={{
              padding: "1.1rem 1.2rem",
              background: criticalCount > 0 ? "rgba(48, 12, 18, 0.75)" : "rgba(15, 23, 42, 0.75)",
              border: `1px solid ${criticalCount > 0 ? "rgba(239, 68, 68, 0.55)" : "rgba(255, 255, 255, 0.1)"}`,
              borderRadius: "10px",
              backdropFilter: "blur(8px)",
              boxShadow: criticalCount > 0 ? "0 0 20px rgba(239, 68, 68, 0.2)" : "none",
            }}
          >
            <div style={{ fontSize: "11px", fontFamily: "var(--mono)", color: criticalCount > 0 ? "#fca5a5" : "#94a3b8", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "0.3rem" }}>
              {t.summaryCritical}
            </div>
            <div style={{ fontSize: "28px", fontWeight: 700, fontFamily: "var(--mono)", color: criticalCount > 0 ? "#ef4444" : "#FFFFFF" }}>
              {criticalCount}
            </div>
          </div>

          {/* 4. Last Updated */}
          <div
            style={{
              padding: "1.1rem 1.2rem",
              background: "rgba(15, 23, 42, 0.75)",
              border: "1px solid rgba(255, 255, 255, 0.1)",
              borderRadius: "10px",
              backdropFilter: "blur(8px)",
            }}
          >
            <div style={{ fontSize: "11px", fontFamily: "var(--mono)", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "0.3rem" }}>
              {t.summaryUpdated}
            </div>
            <div style={{ fontSize: "18px", fontWeight: 600, fontFamily: "var(--mono)", color: "#38bdf8", marginTop: "4px" }}>
              Live Telemetry (1m)
            </div>
          </div>
        </div>

        {/* Section Header: Active Alerts */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "0.8rem",
            marginBottom: "1.2rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <h2 style={{ fontSize: "18px", fontWeight: 700, color: "#FFFFFF", fontFamily: "var(--mono)", letterSpacing: "0.04em", margin: 0 }}>
              {t.activeAlerts} ({filteredActiveAlerts.length})
            </h2>
          </div>

          {/* Filter Pills */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
            {(["ALL", "CRITICAL", "HIGH", "MODERATE"] as const).map((sev) => {
              const active = severityFilter === sev;
              return (
                <button
                  key={sev}
                  type="button"
                  onClick={() => setSeverityFilter(sev)}
                  style={{
                    padding: "4px 10px",
                    borderRadius: "6px",
                    background: active ? "rgba(168, 85, 247, 0.3)" : "rgba(255, 255, 255, 0.05)",
                    border: `1px solid ${active ? "#a855f7" : "rgba(255, 255, 255, 0.1)"}`,
                    color: active ? "#FFFFFF" : "#94a3b8",
                    fontFamily: "var(--mono)",
                    fontSize: "11px",
                    fontWeight: active ? 600 : 400,
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  {sev === "ALL"
                    ? t.filterAll
                    : sev === "CRITICAL"
                    ? t.filterCritical
                    : sev === "HIGH"
                    ? t.filterHigh
                    : t.filterModerate}
                </button>
              );
            })}
          </div>
        </div>

        {/* Active Alerts List with Custom Danger-Level Border & Glow Architecture */}
        {filteredActiveAlerts.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: "1.2rem", marginBottom: "3rem" }}>
            {filteredActiveAlerts.map((alert) => {
              const config = severityConfig[alert.severity] || severityConfig.MODERATE;
              return (
                <div
                  key={alert.id}
                  style={{
                    background: config.bg,
                    border: `1px solid ${config.border}`,
                    borderLeft: config.borderLeft,
                    borderRadius: "14px",
                    padding: "clamp(1.2rem, 2.5vw, 1.8rem)",
                    backdropFilter: "blur(14px)",
                    boxShadow: config.glow,
                    transition: "transform 0.2s ease, box-shadow 0.2s ease",
                    position: "relative",
                    overflow: "hidden",
                  }}
                >
                  {/* Top Metadata & Danger Level Header Row */}
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: "0.8rem",
                      marginBottom: "0.9rem",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
                      {/* Danger Level Pill Badge */}
                      <span
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "0.35rem",
                          padding: "3px 9px",
                          borderRadius: "5px",
                          background: `${config.dangerColor}22`,
                          border: `1px solid ${config.dangerColor}80`,
                          color: config.text,
                          fontFamily: "var(--mono)",
                          fontSize: "11px",
                          fontWeight: 800,
                          letterSpacing: "0.06em",
                          textTransform: "uppercase",
                        }}
                      >
                        {getCategoryIcon(alert.category)}
                        <span>{alert.severity}</span>
                      </span>

                      {/* Danger Severity Gauge (5-bar meter) */}
                      <div
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "3px",
                          padding: "3px 8px",
                          background: "rgba(0, 0, 0, 0.4)",
                          border: `1px solid ${config.dangerColor}40`,
                          borderRadius: "5px",
                          fontSize: "10.5px",
                          fontFamily: "var(--mono)",
                        }}
                      >
                        <span style={{ color: "#94a3b8", marginRight: "4px" }}>{t.dangerLabel}:</span>
                        <div style={{ display: "flex", gap: "2px" }}>
                          {[1, 2, 3, 4, 5].map((barIdx) => (
                            <span
                              key={barIdx}
                              style={{
                                width: "5px",
                                height: "10px",
                                borderRadius: "1px",
                                background:
                                  barIdx <= config.filledBars
                                    ? config.dangerColor
                                    : "rgba(255, 255, 255, 0.1)",
                              }}
                            />
                          ))}
                        </div>
                        <span style={{ color: config.dangerColor, fontWeight: 700, marginLeft: "4px" }}>
                          {config.dangerScore}
                        </span>
                      </div>

                      <span
                        style={{
                          fontSize: "11px",
                          fontFamily: "var(--mono)",
                          color: "#94a3b8",
                          textTransform: "uppercase",
                        }}
                      >
                        {alert.category.replace("_", " ")}
                      </span>

                      <span style={{ color: "#475569" }}>•</span>

                      <span
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "0.25rem",
                          fontSize: "11.5px",
                          color: "#38bdf8",
                          fontFamily: "var(--mono)",
                        }}
                      >
                        <MapPin size={12} />
                        {alert.location}
                      </span>
                    </div>

                    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "11.5px", color: "#94a3b8", fontFamily: "var(--mono)" }}>
                      <Clock size={12} />
                      <span>{new Date(alert.lastUpdated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} IST</span>
                    </div>
                  </div>

                  {/* Title & Detailed Explanation */}
                  <h3
                    style={{
                      fontSize: "clamp(17px, 2vw, 20px)",
                      fontWeight: 800,
                      color: "#FFFFFF",
                      marginBottom: "0.5rem",
                      letterSpacing: "-0.01em",
                    }}
                  >
                    {alert.title}
                  </h3>

                  <p
                    style={{
                      fontSize: "14px",
                      lineHeight: 1.6,
                      color: "#e2e8f0",
                      marginBottom: "1.1rem",
                    }}
                  >
                    {alert.summary}
                  </p>

                  {/* Recommended Action Box with Accentuated Danger Border */}
                  <div
                    style={{
                      padding: "0.85rem 1.1rem",
                      background: "rgba(0, 0, 0, 0.4)",
                      border: `1px solid ${config.dangerColor}50`,
                      borderRadius: "8px",
                      marginBottom: "1.2rem",
                      fontSize: "13px",
                      lineHeight: 1.5,
                      color: "#f8fafc",
                    }}
                  >
                    <strong style={{ color: config.dangerColor }}>{t.protocolLabel} </strong>
                    {alert.recommendedAction}
                  </div>

                  {/* Bottom Footer Telemetry & Details Action */}
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: "0.8rem",
                      borderTop: `1px solid rgba(255, 255, 255, 0.08)`,
                      paddingTop: "0.9rem",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "1rem", fontSize: "12px", fontFamily: "var(--mono)", color: "#94a3b8" }}>
                      {alert.metrics.aqi && (
                        <span>
                          AQI: <strong style={{ color: "#FFFFFF" }}>{alert.metrics.aqi}</strong>
                        </span>
                      )}
                      {alert.metrics.pm25 && (
                        <span>
                          PM2.5: <strong style={{ color: "#f87171" }}>{alert.metrics.pm25} µg/m³</strong>
                        </span>
                      )}
                      <span>
                        Impact: <strong style={{ color: config.text }}>{alert.impactLevel}</strong>
                      </span>
                    </div>

                    <div style={{ display: "flex", gap: "0.6rem" }}>
                      <button
                        type="button"
                        onClick={() => handleOpenDetail(alert)}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "0.4rem",
                          padding: "0.45rem 1rem",
                          borderRadius: "6px",
                          background: `${config.dangerColor}25`,
                          border: `1px solid ${config.dangerColor}70`,
                          color: "#FFFFFF",
                          fontFamily: "var(--mono)",
                          fontSize: "11.5px",
                          fontWeight: 700,
                          cursor: "pointer",
                          transition: "all 0.2s ease",
                        }}
                      >
                        <span>{t.viewDetails}</span>
                        <ChevronRight size={13} />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          /* Empty State: You're All Clear */
          <div
            style={{
              padding: "3.5rem 1.5rem",
              background: "rgba(15, 23, 42, 0.5)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: "14px",
              textAlign: "center",
              marginBottom: "3rem",
            }}
          >
            <div
              style={{
                width: "48px",
                height: "48px",
                borderRadius: "50%",
                background: "rgba(34, 197, 94, 0.15)",
                border: "1px solid #22c55e",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#22c55e",
                margin: "0 auto 1rem",
              }}
            >
              <ShieldCheck size={24} />
            </div>
            <h3 style={{ fontSize: "18px", fontWeight: 700, color: "#FFFFFF", marginBottom: "0.4rem" }}>
              {t.noActiveAlertsTitle}
            </h3>
            <p style={{ fontSize: "13px", color: "#94a3b8", maxWidth: "480px", margin: "0 auto" }}>
              {t.noActiveAlertsDesc}
            </p>
          </div>
        )}

        {/* Section: Earlier & Resolved Alerts */}
        <div style={{ marginBottom: "2rem" }}>
          <h2 style={{ fontSize: "16px", fontWeight: 700, color: "#94a3b8", fontFamily: "var(--mono)", letterSpacing: "0.04em", marginBottom: "1rem" }}>
            {t.earlierAlerts}
          </h2>

          <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
            {earlierAlerts.map((hist) => (
              <div
                key={hist.id}
                onClick={() => handleOpenDetail(hist)}
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "0.8rem",
                  padding: "0.85rem 1.1rem",
                  background: "rgba(15, 23, 42, 0.45)",
                  border: "1px solid rgba(255, 255, 255, 0.06)",
                  borderRadius: "8px",
                  cursor: "pointer",
                  transition: "all 0.2s ease",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", flexWrap: "wrap" }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "#64748b" }}>
                    {new Date(hist.lastUpdated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} IST
                  </span>
                  <span style={{ fontWeight: 600, fontSize: "13px", color: "#cbd5e1" }}>{hist.title}</span>
                </div>
                <ChevronRight size={14} style={{ color: "#64748b" }} />
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Settings Modal */}
      {showSettings && (
        <AlertSettingsModal
          settings={settings}
          language={language as AlertLanguage}
          onClose={() => setShowSettings(false)}
          onSave={handleSaveSettings}
        />
      )}

      {/* Detail Modal */}
      {selectedAlert && (
        <AlertDetailModal
          alert={selectedAlert}
          language={language as AlertLanguage}
          onClose={() => setSelectedAlert(null)}
          onNavigate={(page) => {
            setSelectedAlert(null);
            if (onNavigate) onNavigate(page);
          }}
        />
      )}
    </div>
  );
}
