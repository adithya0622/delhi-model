import React, { createContext, useContext, useEffect, useState, useMemo, useCallback } from "react";
import { en } from "./locales/en";
import { hi } from "./locales/hi";
import { ta } from "./locales/ta";

export type Language = "en" | "hi" | "ta";

export interface LanguageOption {
  code: Language;
  label: string;
  nativeLabel: string;
}

export const LANGUAGE_OPTIONS: LanguageOption[] = [
  { code: "en", label: "English", nativeLabel: "English" },
  { code: "hi", label: "Hindi", nativeLabel: "हिन्दी" },
  { code: "ta", label: "Tamil", nativeLabel: "தமிழ்" },
];

const translations: Record<Language, typeof en> = {
  en,
  hi: hi as unknown as typeof en,
  ta: ta as unknown as typeof en,
};

const STORAGE_KEY = "ncr72_language_v1";

interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (keyPath: string, params?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextType | undefined>(undefined);

function getNestedValue(obj: any, path: string): string | undefined {
  const parts = path.split(".");
  let current = obj;
  for (const part of parts) {
    if (current === undefined || current === null) return undefined;
    current = current[part];
  }
  return typeof current === "string" ? current : undefined;
}

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [language, setLanguageState] = useState<Language>(() => {
    if (typeof window !== "undefined") {
      try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved === "en" || saved === "hi" || saved === "ta") {
          return saved;
        }
      } catch {
        // Ignore storage errors
      }
    }
    return "en";
  });

  const setLanguage = useCallback((newLang: Language) => {
    setLanguageState(newLang);
    if (typeof window !== "undefined") {
      try {
        localStorage.setItem(STORAGE_KEY, newLang);
        document.documentElement.lang = newLang;
        document.documentElement.setAttribute("data-lang", newLang);
      } catch {
        // Ignore storage quota
      }
    }
  }, []);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = language;
      document.documentElement.setAttribute("data-lang", language);
    }
  }, [language]);

  const t = useCallback(
    (keyPath: string, params?: Record<string, string | number>): string => {
      const activeDict = translations[language] || translations.en;
      let text = getNestedValue(activeDict, keyPath);

      // Fallback to English if missing in target locale
      if (text === undefined && language !== "en") {
        text = getNestedValue(translations.en, keyPath);
      }

      // If still missing, return the leaf key or keyPath safely
      if (text === undefined) {
        return keyPath.split(".").pop() || keyPath;
      }

      // Param interpolation: e.g. "AQI is {aqi}"
      if (params) {
        Object.entries(params).forEach(([k, v]) => {
          text = text?.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
        });
      }

      return text || "";
    },
    [language],
  );

  const value = useMemo(
    () => ({
      language,
      setLanguage,
      t,
    }),
    [language, setLanguage, t],
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
};

export function useTranslation(): LanguageContextType {
  const context = useContext(LanguageContext);
  if (!context) {
    // Fallback if rendered outside provider
    return {
      language: "en",
      setLanguage: () => {},
      t: (keyPath: string) => {
        const text = getNestedValue(en, keyPath);
        return text || keyPath.split(".").pop() || keyPath;
      },
    };
  }
  return context;
}
