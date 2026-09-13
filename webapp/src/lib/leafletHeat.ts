/**
 * leaflet.heat shim.
 *
 * leaflet.heat@0.2.0 predates ES modules: its IIFE augments a *global* Leaflet
 * (`L.heatLayer = …`) and exports nothing. Under Vite there is no implicit global
 * `L`, and `import * as L from "leaflet"` yields a sealed module namespace the
 * plugin cannot write to — so `L.heatLayer` came back undefined at call time.
 *
 * This module publishes Leaflet on `globalThis.L` FIRST, then pulls the plugin in
 * for its side effect. Split into its own file on purpose: a module's imports are
 * evaluated before its body, so the assignment and the plugin import must live in
 * separate modules for the ordering (assign → then augment) to hold. Anything that
 * needs the heat layer imports `heatLayer` from here rather than off `leaflet`.
 */
import L from "leaflet";

(globalThis as unknown as { L: typeof L }).L = L;

// Side-effect import: augments the global L we just published.
import "leaflet.heat";

type HeatLatLng = [number, number, number] | [number, number];
interface HeatOptions {
  minOpacity?: number;
  maxZoom?: number;
  max?: number;
  radius?: number;
  blur?: number;
  gradient?: Record<number, string>;
}

// The plugin adds these to L at runtime; they are absent from @types/leaflet.
const Lheat = L as unknown as {
  heatLayer: (latlngs: HeatLatLng[], options?: HeatOptions) => L.Layer;
};

export const heatLayer = Lheat.heatLayer;
export type { HeatLatLng, HeatOptions };
