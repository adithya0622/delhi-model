import { useEffect, useRef, useState } from "react";
import { Globe, ChevronDown, Check } from "lucide-react";
import { useTranslation, LANGUAGE_OPTIONS, type Language } from "@/i18n";

interface LanguageSelectorProps {
  compact?: boolean;
}

export function LanguageSelector({ compact = false }: LanguageSelectorProps) {
  const { language, setLanguage } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  const currentOption = LANGUAGE_OPTIONS.find((opt) => opt.code === language) || LANGUAGE_OPTIONS[0];

  const handleSelect = (code: Language) => {
    setLanguage(code);
    setIsOpen(false);
  };

  return (
    <div ref={menuRef} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "0.35rem",
          padding: compact ? "0.28rem 0.6rem" : "0.32rem 0.75rem",
          background: isOpen ? "rgba(168, 85, 247, 0.25)" : "rgba(255, 255, 255, 0.08)",
          border: `1px solid ${isOpen ? "#a855f7" : "rgba(255, 255, 255, 0.22)"}`,
          borderRadius: "6px",
          color: "#FFFFFF",
          fontFamily: "var(--mono)",
          fontSize: "11.5px",
          fontWeight: 600,
          cursor: "pointer",
          transition: "all 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
          boxShadow: isOpen ? "0 0 12px rgba(168, 85, 247, 0.4)" : "none",
          outline: "none",
        }}
        aria-label="Select Language"
        aria-expanded={isOpen}
      >
        <Globe size={13} style={{ color: "#38bdf8" }} />
        <span>{currentOption.nativeLabel}</span>
        <ChevronDown
          size={11}
          style={{
            transform: isOpen ? "rotate(180deg)" : "rotate(0deg)",
            transition: "transform 0.2s ease",
            color: "rgba(255, 255, 255, 0.6)",
          }}
        />
      </button>

      {isOpen && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            zIndex: 100,
            minWidth: "140px",
            background: "linear-gradient(135deg, rgba(20, 26, 44, 0.96) 0%, rgba(11, 15, 26, 0.98) 100%)",
            border: "1px solid rgba(168, 85, 247, 0.35)",
            borderRadius: "8px",
            boxShadow: "0 16px 40px rgba(0, 0, 0, 0.8), 0 0 20px rgba(168, 85, 247, 0.2)",
            padding: "4px",
            backdropFilter: "blur(20px)",
            WebkitBackdropFilter: "blur(20px)",
            animation: "fadeIn 0.15s ease",
          }}
        >
          {LANGUAGE_OPTIONS.map((opt) => {
            const isSelected = opt.code === language;
            return (
              <button
                key={opt.code}
                type="button"
                onClick={() => handleSelect(opt.code)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  width: "100%",
                  padding: "0.45rem 0.7rem",
                  borderRadius: "5px",
                  background: isSelected ? "rgba(168, 85, 247, 0.22)" : "transparent",
                  border: "none",
                  color: isSelected ? "#FFFFFF" : "#cbd5e1",
                  fontFamily: opt.code === "hi" ? "var(--font-sans), 'Noto Sans Devanagari', sans-serif" : opt.code === "ta" ? "var(--font-sans), 'Noto Sans Tamil', sans-serif" : "var(--mono)",
                  fontSize: "12px",
                  fontWeight: isSelected ? 600 : 400,
                  cursor: "pointer",
                  textAlign: "left",
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={(e) => {
                  if (!isSelected) {
                    e.currentTarget.style.background = "rgba(255, 255, 255, 0.08)";
                    e.currentTarget.style.color = "#FFFFFF";
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isSelected) {
                    e.currentTarget.style.background = "transparent";
                    e.currentTarget.style.color = "#cbd5e1";
                  }
                }}
              >
                <span>{opt.nativeLabel}</span>
                {isSelected && <Check size={13} style={{ color: "#c084fc" }} />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
