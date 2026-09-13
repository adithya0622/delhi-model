import { useState } from "react";
import {
  Sliders,
  X,
  Check,
  AlertTriangle,
  Flame,
  Factory,
  TrendingUp,
  Activity,
  Heart,
  Save,
} from "lucide-react";
import type { AlertCategory, AlertSettings } from "@/lib/alertsEngine";
import { DEFAULT_ALERT_SETTINGS } from "@/lib/alertsEngine";
import type { AlertLanguage } from "@/lib/alertTranslations";
import { ALERT_TRANSLATIONS } from "@/lib/alertTranslations";

interface AlertSettingsModalProps {
  settings: AlertSettings;
  language: AlertLanguage;
  onSave: (newSettings: AlertSettings) => void;
  onClose: () => void;
}

export function AlertSettingsModal({
  settings: initialSettings,
  language,
  onSave,
  onClose,
}: AlertSettingsModalProps) {
  const t = ALERT_TRANSLATIONS[language] || ALERT_TRANSLATIONS.en;
  const [localSettings, setLocalSettings] = useState<AlertSettings>({ ...initialSettings });

  const toggleCategory = (cat: AlertCategory) => {
    setLocalSettings((prev) => ({
      ...prev,
      enabledCategories: {
        ...prev.enabledCategories,
        [cat]: !prev.enabledCategories[cat],
      },
    }));
  };

  const handleSave = () => {
    onSave(localSettings);
    onClose();
  };

  const handleReset = () => {
    setLocalSettings({ ...DEFAULT_ALERT_SETTINGS });
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
          maxWidth: "580px",
          maxHeight: "90vh",
          overflowY: "auto",
          background: "linear-gradient(135deg, rgba(20, 26, 44, 0.96) 0%, rgba(11, 15, 26, 0.98) 100%)",
          border: "1px solid rgba(168, 85, 247, 0.35)",
          borderRadius: "16px",
          boxShadow: "0 24px 64px -12px rgba(0, 0, 0, 0.8), 0 0 32px rgba(168, 85, 247, 0.2)",
          padding: "clamp(1.2rem, 3vw, 1.8rem)",
          color: "var(--bone)",
          position: "relative",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: "1.2rem",
            borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
            paddingBottom: "0.85rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <Sliders size={18} style={{ color: "#c084fc" }} />
            <h2 style={{ fontSize: "16px", fontWeight: 700, color: "#FFFFFF", fontFamily: "var(--mono)" }}>
              {t.alertSettings}
            </h2>
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
            }}
          >
            <X size={15} />
          </button>
        </div>

        {/* Section 1: AQI Threshold Trigger */}
        <div style={{ marginBottom: "1.4rem" }}>
          <label style={{ display: "block", fontSize: "12px", fontFamily: "var(--mono)", color: "#94a3b8", textTransform: "uppercase", marginBottom: "0.6rem" }}>
            Notify when regional AQI reaches:
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.5rem" }}>
            {(["Poor", "Very Poor", "Severe"] as const).map((level) => {
              const selected = localSettings.minAqiThreshold === level;
              return (
                <button
                  key={level}
                  type="button"
                  onClick={() => setLocalSettings((prev) => ({ ...prev, minAqiThreshold: level }))}
                  style={{
                    padding: "0.55rem",
                    borderRadius: "6px",
                    background: selected ? "rgba(168, 85, 247, 0.25)" : "rgba(255, 255, 255, 0.04)",
                    border: `1px solid ${selected ? "#a855f7" : "rgba(255, 255, 255, 0.1)"}`,
                    color: selected ? "#FFFFFF" : "#94a3b8",
                    fontFamily: "var(--mono)",
                    fontSize: "11.5px",
                    fontWeight: selected ? 600 : 400,
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  {level} {level === "Poor" ? "(201+)" : level === "Very Poor" ? "(301+)" : "(401+)"}
                </button>
              );
            })}
          </div>
        </div>

        {/* Section 2: Category Toggles */}
        <div style={{ marginBottom: "1.6rem" }}>
          <label style={{ display: "block", fontSize: "12px", fontFamily: "var(--mono)", color: "#94a3b8", textTransform: "uppercase", marginBottom: "0.6rem" }}>
            Active Advisory Categories:
          </label>

          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {[
              { id: "AIR_QUALITY", label: "Regional Air Quality Alerts", icon: AlertTriangle, desc: "CPCB standard threshold crossings" },
              { id: "RAPID_RISE", label: "Rapid Pollution Surge Tracker", icon: TrendingUp, desc: "+20% or higher PM2.5 rise within 1 hour" },
              { id: "INDUSTRIAL", label: "Nearby Industrial Zone Influence", icon: Factory, desc: "Spatial proximity to Tier 1 manufacturing pockets" },
              { id: "FIRE_SMOKE", label: "Satellite Fire & Stubble Smoke", icon: Flame, desc: "NASA FIRMS detections & 850 hPa wind vector coupling" },
              { id: "FORECAST", label: "Prognostic Inversion & Spike Warnings", icon: Activity, desc: "Nocturnal cooling and 72-hour forecast deteriorations" },
              { id: "EXPOSURE", label: "Personal Exposure Limit Advisories", icon: Heart, desc: "High cumulative inhalation dose estimates" },
            ].map((cat) => {
              const isEnabled = localSettings.enabledCategories[cat.id as AlertCategory];
              const Icon = cat.icon;
              return (
                <div
                  key={cat.id}
                  onClick={() => toggleCategory(cat.id as AlertCategory)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0.65rem 0.85rem",
                    background: isEnabled ? "rgba(255, 255, 255, 0.05)" : "rgba(0, 0, 0, 0.2)",
                    border: `1px solid ${isEnabled ? "rgba(168, 85, 247, 0.3)" : "rgba(255, 255, 255, 0.06)"}`,
                    borderRadius: "8px",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "0.7rem" }}>
                    <Icon size={16} style={{ color: isEnabled ? "#c084fc" : "#64748b" }} />
                    <div>
                      <div style={{ fontSize: "12.5px", fontWeight: 600, color: isEnabled ? "#FFFFFF" : "#94a3b8" }}>
                        {cat.label}
                      </div>
                      <div style={{ fontSize: "10.5px", color: "#64748b" }}>
                        {cat.desc}
                      </div>
                    </div>
                  </div>

                  <div
                    style={{
                      width: "18px",
                      height: "18px",
                      borderRadius: "4px",
                      background: isEnabled ? "#9333ea" : "transparent",
                      border: `1px solid ${isEnabled ? "#a855f7" : "rgba(255, 255, 255, 0.3)"}`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "#FFFFFF",
                    }}
                  >
                    {isEnabled && <Check size={12} strokeWidth={3} />}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Footer Actions */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem" }}>
          <button
            type="button"
            onClick={handleReset}
            style={{
              padding: "0.55rem 0.9rem",
              borderRadius: "6px",
              background: "transparent",
              border: "1px solid rgba(255, 255, 255, 0.15)",
              color: "#94a3b8",
              fontFamily: "var(--mono)",
              fontSize: "11.5px",
              cursor: "pointer",
            }}
          >
            Reset Defaults
          </button>

          <div style={{ display: "flex", gap: "0.6rem" }}>
            <button
              type="button"
              onClick={handleSave}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.4rem",
                padding: "0.55rem 1.1rem",
                borderRadius: "6px",
                background: "linear-gradient(135deg, #7e22ce 0%, #9333ea 100%)",
                border: "1px solid rgba(255, 255, 255, 0.2)",
                color: "#FFFFFF",
                fontFamily: "var(--mono)",
                fontSize: "12px",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              <Save size={13} />
              <span>{t.saveSettings}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
