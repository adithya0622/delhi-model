import { useEffect } from "react";
import {
  AlertTriangle,
  Flame,
  Factory,
  TrendingUp,
  Activity,
  MapPin,
  Clock,
  Wind,
  ShieldAlert,
  Heart,
  X,
  Navigation,
} from "lucide-react";
import type { AlertItem } from "@/lib/alertsEngine";
import type { AlertLanguage } from "@/lib/alertTranslations";
import { ALERT_TRANSLATIONS } from "@/lib/alertTranslations";

interface AlertDetailModalProps {
  alert: AlertItem | null;
  language: AlertLanguage;
  onClose: () => void;
  onNavigate: (page: string, params?: any) => void;
}

export function AlertDetailModal({
  alert,
  language,
  onClose,
  onNavigate,
}: AlertDetailModalProps) {
  const t = ALERT_TRANSLATIONS[language] || ALERT_TRANSLATIONS.en;

  // Escape key closes modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  if (!alert) return null;

  const severityColors = {
    CRITICAL: {
      badgeBg: "rgba(239, 68, 68, 0.2)",
      badgeBorder: "#ef4444",
      badgeText: "#fca5a5",
      glow: "rgba(239, 68, 68, 0.35)",
    },
    HIGH: {
      badgeBg: "rgba(249, 115, 22, 0.2)",
      badgeBorder: "#f97316",
      badgeText: "#fdba74",
      glow: "rgba(249, 115, 22, 0.35)",
    },
    MODERATE: {
      badgeBg: "rgba(234, 179, 8, 0.2)",
      badgeBorder: "#eab308",
      badgeText: "#fde047",
      glow: "rgba(234, 179, 8, 0.35)",
    },
    LOW: {
      badgeBg: "rgba(34, 197, 94, 0.2)",
      badgeBorder: "#22c55e",
      badgeText: "#86efac",
      glow: "rgba(34, 197, 94, 0.35)",
    },
    INFO: {
      badgeBg: "rgba(168, 85, 247, 0.2)",
      badgeBorder: "#a855f7",
      badgeText: "#d8b4fe",
      glow: "rgba(168, 85, 247, 0.35)",
    },
  };

  const currentTheme = severityColors[alert.severity] || severityColors.MODERATE;

  const getCategoryIcon = (cat: string) => {
    switch (cat) {
      case "AIR_QUALITY":
        return <AlertTriangle size={18} />;
      case "RAPID_RISE":
        return <TrendingUp size={18} />;
      case "INDUSTRIAL":
        return <Factory size={18} />;
      case "FIRE_SMOKE":
        return <Flame size={18} />;
      case "FORECAST":
        return <Activity size={18} />;
      case "EXPOSURE":
        return <Heart size={18} />;
      default:
        return <AlertTriangle size={18} />;
    }
  };

  const handleAction = () => {
    onClose();
    if (alert.actionTarget.type === "map") {
      onNavigate("overview");
      setTimeout(() => {
        const mapEl = document.getElementById("station-map-view");
        if (mapEl) mapEl.scrollIntoView({ behavior: "smooth" });
      }, 100);
    } else if (alert.actionTarget.type === "exposure") {
      onNavigate("exposure-tracker");
    } else if (alert.actionTarget.type === "forecast") {
      onNavigate("forecast-datas");
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 100,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1rem",
        backgroundColor: "rgba(4, 7, 13, 0.82)",
        backdropFilter: "blur(14px)",
        WebkitBackdropFilter: "blur(14px)",
        animation: "fadeIn 0.2s ease",
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: "100%",
          maxWidth: "680px",
          maxHeight: "90vh",
          overflowY: "auto",
          background: "linear-gradient(135deg, rgba(20, 26, 44, 0.95) 0%, rgba(11, 15, 26, 0.98) 100%)",
          border: `1px solid ${currentTheme.badgeBorder}66`,
          borderRadius: "16px",
          boxShadow: `0 24px 64px -12px rgba(0, 0, 0, 0.8), 0 0 32px ${currentTheme.glow}`,
          padding: "clamp(1.2rem, 3vw, 2rem)",
          position: "relative",
          color: "var(--bone)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header Row */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: "1rem",
            marginBottom: "1.2rem",
            borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
            paddingBottom: "1rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.35rem",
                padding: "3px 9px",
                borderRadius: "5px",
                background: currentTheme.badgeBg,
                border: `1px solid ${currentTheme.badgeBorder}`,
                color: currentTheme.badgeText,
                fontFamily: "var(--mono)",
                fontSize: "11px",
                fontWeight: 700,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
              }}
            >
              {getCategoryIcon(alert.category)}
              <span>{alert.severity} ADVISORY</span>
            </span>

            <span
              style={{
                padding: "3px 8px",
                borderRadius: "5px",
                background: "rgba(255, 255, 255, 0.06)",
                border: "1px solid rgba(255, 255, 255, 0.12)",
                fontFamily: "var(--mono)",
                fontSize: "10.5px",
                color: "rgba(255, 255, 255, 0.7)",
                textTransform: "uppercase",
                letterSpacing: "0.04em",
              }}
            >
              {alert.category.replace("_", " ")}
            </span>
          </div>

          <button
            type="button"
            onClick={onClose}
            style={{
              background: "rgba(255, 255, 255, 0.08)",
              border: "1px solid rgba(255, 255, 255, 0.15)",
              borderRadius: "6px",
              color: "#FFFFFF",
              cursor: "pointer",
              padding: "5px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transition: "all 0.2s ease",
            }}
            aria-label="Close details"
          >
            <X size={16} />
          </button>
        </div>

        {/* Alert Title & Location Banner */}
        <h2
          style={{
            fontSize: "clamp(18px, 2.2vw, 22px)",
            fontWeight: 700,
            color: "#FFFFFF",
            lineHeight: 1.3,
            marginBottom: "0.4rem",
          }}
        >
          {alert.title}
        </h2>

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: "0.8rem",
            fontSize: "12px",
            color: "#94a3b8",
            fontFamily: "var(--mono)",
            marginBottom: "1.4rem",
          }}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem", color: "#38bdf8" }}>
            <MapPin size={13} /> {alert.location}
          </span>
          <span>•</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
            <Clock size={13} /> {new Date(alert.lastUpdated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} IST
          </span>
          <span>•</span>
          <span style={{ color: "#a855f7" }}>
            Impact: <strong style={{ color: "#FFFFFF" }}>{alert.impactLevel}</strong>
          </span>
        </div>

        {/* Primary Human Explanation Box */}
        <div
          style={{
            padding: "1rem 1.2rem",
            background: "rgba(255, 255, 255, 0.04)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
            borderRadius: "10px",
            marginBottom: "1.4rem",
            fontSize: "13.5px",
            lineHeight: 1.6,
            color: "#e2e8f0",
          }}
        >
          <strong style={{ color: currentTheme.badgeText, display: "block", marginBottom: "4px" }}>
            Summary of Situation:
          </strong>
          {alert.description}
        </div>

        {/* Environmental Telemetry Grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
            gap: "0.6rem",
            marginBottom: "1.4rem",
          }}
        >
          {alert.metrics.aqi && (
            <div
              style={{
                padding: "0.75rem",
                background: "rgba(15, 23, 42, 0.6)",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: "8px",
              }}
            >
              <div style={{ fontSize: "10px", color: "#94a3b8", fontFamily: "var(--mono)", textTransform: "uppercase" }}>
                Observed AQI
              </div>
              <div style={{ fontSize: "20px", fontWeight: 700, color: currentTheme.badgeText, fontFamily: "var(--mono)" }}>
                {alert.metrics.aqi}
              </div>
            </div>
          )}

          {alert.metrics.pm25 && (
            <div
              style={{
                padding: "0.75rem",
                background: "rgba(15, 23, 42, 0.6)",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: "8px",
              }}
            >
              <div style={{ fontSize: "10px", color: "#94a3b8", fontFamily: "var(--mono)", textTransform: "uppercase" }}>
                PM2.5 Density
              </div>
              <div style={{ fontSize: "18px", fontWeight: 700, color: "#FFFFFF", fontFamily: "var(--mono)" }}>
                {alert.metrics.pm25} <span style={{ fontSize: "11px", fontWeight: 400, color: "#94a3b8" }}>µg/m³</span>
              </div>
            </div>
          )}

          {alert.metrics.deltaPct && (
            <div
              style={{
                padding: "0.75rem",
                background: "rgba(15, 23, 42, 0.6)",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: "8px",
              }}
            >
              <div style={{ fontSize: "10px", color: "#94a3b8", fontFamily: "var(--mono)", textTransform: "uppercase" }}>
                Rate of Surge
              </div>
              <div style={{ fontSize: "18px", fontWeight: 700, color: "#f87171", fontFamily: "var(--mono)" }}>
                +{alert.metrics.deltaPct}%
              </div>
            </div>
          )}

          {alert.metrics.windSpeed && (
            <div
              style={{
                padding: "0.75rem",
                background: "rgba(15, 23, 42, 0.6)",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: "8px",
              }}
            >
              <div style={{ fontSize: "10px", color: "#94a3b8", fontFamily: "var(--mono)", textTransform: "uppercase" }}>
                Wind &amp; Vector
              </div>
              <div style={{ fontSize: "14px", fontWeight: 600, color: "#FFFFFF", display: "flex", alignItems: "center", gap: "4px", marginTop: "4px" }}>
                <Wind size={13} style={{ color: "#38bdf8" }} />
                {alert.metrics.windSpeed} m/s {alert.metrics.windDirection}
              </div>
            </div>
          )}
        </div>

        {/* Actionable Health Guidance Box */}
        <div
          style={{
            padding: "1rem 1.2rem",
            background: "linear-gradient(135deg, rgba(30, 27, 75, 0.4) 0%, rgba(15, 23, 42, 0.6) 100%)",
            border: "1px solid rgba(168, 85, 247, 0.3)",
            borderRadius: "10px",
            marginBottom: "1.4rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", marginBottom: "0.5rem" }}>
            <ShieldAlert size={16} style={{ color: "#c084fc" }} />
            <strong style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "#c084fc", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              {t.recommendedAction}
            </strong>
          </div>
          <p style={{ fontSize: "13px", lineHeight: 1.5, color: "#f1f5f9", marginBottom: "0.6rem" }}>
            {alert.recommendedAction}
          </p>
          <div style={{ fontSize: "12px", color: "#cbd5e1", borderTop: "1px solid rgba(255, 255, 255, 0.08)", paddingTop: "0.5rem" }}>
            <strong style={{ color: "#fca5a5" }}>Sensitive Groups Advisory:</strong> {alert.sensitiveGroupAction}
          </div>
        </div>

        {/* Data Provenance & Science Context */}
        <div
          style={{
            fontSize: "11px",
            color: "#64748b",
            fontFamily: "var(--mono)",
            marginBottom: "1.5rem",
            padding: "0.6rem 0.8rem",
            background: "rgba(0, 0, 0, 0.25)",
            borderRadius: "6px",
            border: "1px solid rgba(255, 255, 255, 0.05)",
          }}
        >
          <strong>Scientific Provenance:</strong> {alert.sourceContext.label} • {alert.sourceContext.details}
        </div>

        {/* Action Buttons */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", justifyContent: "flex-end" }}>
          <button
            type="button"
            onClick={handleAction}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.4rem",
              padding: "0.6rem 1.1rem",
              borderRadius: "8px",
              background: "linear-gradient(135deg, #7e22ce 0%, #9333ea 100%)",
              border: "1px solid rgba(255, 255, 255, 0.2)",
              color: "#FFFFFF",
              fontSize: "12.5px",
              fontWeight: 600,
              fontFamily: "var(--mono)",
              cursor: "pointer",
              boxShadow: "0 4px 14px rgba(147, 51, 234, 0.4)",
              transition: "all 0.2s ease",
            }}
          >
            <Navigation size={14} />
            <span>
              {alert.actionTarget.type === "map"
                ? t.viewOnMap
                : alert.actionTarget.type === "exposure"
                ? t.checkExposure
                : t.checkForecast}
            </span>
          </button>

          <button
            type="button"
            onClick={onClose}
            style={{
              padding: "0.6rem 1rem",
              borderRadius: "8px",
              background: "rgba(255, 255, 255, 0.08)",
              border: "1px solid rgba(255, 255, 255, 0.15)",
              color: "#94a3b8",
              fontSize: "12.5px",
              fontFamily: "var(--mono)",
              cursor: "pointer",
              transition: "all 0.2s ease",
            }}
          >
            {t.close}
          </button>
        </div>
      </div>
    </div>
  );
}
