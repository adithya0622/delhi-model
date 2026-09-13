import type { Layer, LayerOptions } from "leaflet";

/**
 * Ambient types for leaflet.heat (0.2) — it ships no @types package. We declare
 * only the slice we use: `L.heatLayer(points, opts)` returns a Layer we add to
 * and remove from the map. Points are `[lat, lng, intensity]`, intensity 0..1.
 */
declare module "leaflet" {
  interface HeatMapOptions extends LayerOptions {
    minOpacity?: number;
    maxZoom?: number;
    max?: number;
    radius?: number;
    blur?: number;
    gradient?: Record<number, string>;
  }

  interface HeatLayer extends Layer {
    setLatLngs(latlngs: Array<[number, number, number]>): this;
    addLatLng(latlng: [number, number, number]): this;
    setOptions(options: HeatMapOptions): this;
    redraw(): this;
  }

  function heatLayer(
    latlngs: Array<[number, number, number]>,
    options?: HeatMapOptions,
  ): HeatLayer;
}

// The side-effect import (`import "leaflet.heat"`) needs the module to exist.
declare module "leaflet.heat";
