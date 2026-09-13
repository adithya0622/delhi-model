/**
 * CPCB National AQI (2014) colour + category logic.
 *
 * The AQI ramp is the ONLY saturated colour family in the interface, so colour
 * always means "air quality" and nothing else. We derive colours on the client
 * from the tuned dark-ground ramp (mirrored from styles.css --aqi-1..6) rather
 * than trusting the backend `color` field, which carries the raw CPCB hues that
 * wash out on this background.
 */

import type { AqiCategory } from "./types";
import { AQI_CATEGORIES } from "./types";

/** Ramp matching reference image colors. */
export const AQI_HEX: Record<AqiCategory, string> = {
  Good: "#8ceb8c",
  Satisfactory: "#ffff00",
  Moderate: "#ff9900",
  "Unhealthy for Sensitive Groups": "#ff9900",
  Poor: "#ff6666",
  Unhealthy: "#ff6666",
  "Very Poor": "#af52de",
  "Very Unhealthy": "#af52de",
  Severe: "#800000",
  Hazardous: "#800000",
};

/** The corresponding CSS custom property, for cases where the live var is wanted. */
export const AQI_VAR: Record<AqiCategory, string> = {
  Good: "var(--aqi-1)",
  Satisfactory: "var(--aqi-2)",
  Moderate: "var(--aqi-3)",
  "Unhealthy for Sensitive Groups": "var(--aqi-3)",
  Poor: "var(--aqi-4)",
  Unhealthy: "var(--aqi-4)",
  "Very Poor": "var(--aqi-5)",
  "Very Unhealthy": "var(--aqi-5)",
  Severe: "var(--aqi-6)",
  Hazardous: "var(--aqi-6)",
};

/** CPCB 2014 upper bounds, aligned index-for-index with AQI_CATEGORIES. */
const CPCB_UPPER: readonly number[] = [50, 100, 200, 300, 400, 500];

/** Map a raw AQI value to its CPCB category. Values > 500 clamp to Severe. */
export function aqiToCategory(aqi: number): AqiCategory {
  for (let i = 0; i < CPCB_UPPER.length; i++) {
    if (aqi <= CPCB_UPPER[i]) return AQI_CATEGORIES[i];
  }
  return "Severe";
}

/** Hex for a category. */
export function categoryColor(cat: AqiCategory): string {
  return AQI_HEX[cat] ?? "var(--mist)";
}

/** Hex for a raw AQI value, via its category. */
export function aqiColor(aqi: number): string {
  return categoryColor(aqiToCategory(aqi));
}

/** Ascending severity rank (Good = 0 … Severe = 5); -1 if unrecognised. */
export function categoryRank(cat: AqiCategory): number {
  return AQI_CATEGORIES.indexOf(cat);
}

const BREAKPOINTS: Record<string, [number, number, number, number][]> = {
  "PM2.5": [
    [0.0, 30.0, 0, 50],
    [30.0, 60.0, 51, 100],
    [60.0, 90.0, 101, 200],
    [90.0, 120.0, 201, 300],
    [120.0, 250.0, 301, 400],
    [250.0, 500.0, 401, 500],
  ],
  PM10: [
    [0, 50, 0, 50],
    [50, 100, 51, 100],
    [100, 250, 101, 200],
    [250, 350, 201, 300],
    [350, 430, 301, 400],
    [430, 600, 401, 500],
  ],
  NO2: [
    [0, 40, 0, 50],
    [40, 80, 51, 100],
    [80, 180, 101, 200],
    [180, 280, 201, 300],
    [280, 400, 301, 400],
    [400, 1000, 401, 500],
  ],
  O3: [
    [0, 50, 0, 50],
    [50, 100, 51, 100],
    [100, 168, 101, 200],
    [168, 208, 201, 300],
    [208, 748, 301, 400],
    [748, 1000, 401, 500],
  ],
  SO2: [
    [0, 40, 0, 50],
    [40, 80, 51, 100],
    [80, 380, 101, 200],
    [380, 800, 201, 300],
    [800, 1600, 301, 400],
    [1600, 2000, 401, 500],
  ],
  CO: [
    [0.0, 1.0, 0, 50],
    [1.0, 2.0, 51, 100],
    [2.0, 10.0, 101, 200],
    [10.0, 17.0, 201, 300],
    [17.0, 34.0, 301, 400],
    [34.0, 50.0, 401, 500],
  ],
};

const EPA_BREAKPOINTS: Record<string, [number, number, number, number][]> = {
  "PM2.5": [
    [0.0, 9.0, 0, 50],
    [9.1, 35.4, 51, 100],
    [35.5, 55.4, 101, 150],
    [55.5, 125.4, 151, 200],
    [125.5, 225.4, 201, 300],
    [225.5, 500.4, 301, 500],
  ],
  PM10: [
    [0, 54, 0, 50],
    [55, 154, 51, 100],
    [155, 254, 101, 150],
    [255, 354, 151, 200],
    [355, 424, 201, 300],
    [425, 604, 301, 500],
  ],
  NO2: [
    [0, 53, 0, 50],
    [54, 100, 51, 100],
    [101, 360, 101, 150],
    [361, 649, 151, 200],
    [650, 1249, 201, 300],
    [1250, 2049, 301, 500],
  ],
  O3: [
    [0, 106, 0, 50],
    [107, 137, 51, 100],
    [138, 167, 101, 150],
    [168, 206, 151, 200],
    [207, 392, 201, 300],
    [393, 1000, 301, 500],
  ],
  SO2: [
    [0, 35, 0, 50],
    [36, 75, 51, 100],
    [76, 185, 101, 150],
    [186, 304, 151, 200],
    [305, 604, 201, 300],
    [605, 1004, 301, 500],
  ],
  CO: [
    [0.0, 4.4, 0, 50],
    [4.5, 9.4, 51, 100],
    [9.5, 12.4, 101, 150],
    [12.5, 15.4, 151, 200],
    [15.5, 30.4, 201, 300],
    [30.5, 50.4, 301, 500],
  ],
};

/** Calculate the official AQI sub-index for a concentration (defaults to EPA standard). */
export function pollutantSubIndex(species: string, concentration: number, standard: "epa" | "cpcb" = "epa"): number {
  const norm = species.replace(/\./g, "").toUpperCase();
  const key = norm === "PM25" ? "PM2.5" : norm;
  const table = standard === "cpcb" ? BREAKPOINTS[key] : (EPA_BREAKPOINTS[key] ?? BREAKPOINTS[key]);
  if (!table || concentration <= 0) return 0;

  for (const [clo, chi, ilo, ihi] of table) {
    if (concentration <= chi) {
      const idx = ((ihi - ilo) / (chi - clo)) * (concentration - clo) + ilo;
      return Math.min(500, Math.max(0, Math.round(idx)));
    }
  }
  return 500;
}

