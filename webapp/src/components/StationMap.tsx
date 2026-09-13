import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StationDetail } from "@/components/map/StationDetail";
import { MapCanvas } from "@/components/map/MapCanvas";
import { Skeleton } from "@/components/ui/skeleton";
import type { Panel } from "@/hooks/useForecastData";
import { useOnline } from "@/hooks/useOnline";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import {
  HEAT_GRADIENT,
  MAP_STYLE_ORDER,
  MAP_STYLES,
  type MapLayers,
  type MapStyleId,
} from "@/lib/mapgeo";
import type {
  CityAggregateResponse,
  CityOverview,
  ForecastResponse,
  IndustryRecord,
  IndustryTierFilter,
  PlumeVectorsResponse,
  StationReading,
} from "@/lib/types";
import { classifyIndustryTier } from "@/lib/types";
import { fetchDelhiIndustries } from "@/lib/supabase";
import { useTranslation } from "@/i18n";

// Leaflet's bundle is only fetched when the online renderer actually mounts —
// offline mode never pays for it.
const MapLeaflet = lazy(() => import("@/components/map/MapLeaflet"));

/** How many tileerror events in `auto` mode before we fall back to the canvas. */
const TILE_ERROR_LIMIT = 8;

type RenderMode = "auto" | "tiles" | "offline";

interface StationMapProps {
  stations: Panel<StationReading[]>;
  plume: Panel<PlumeVectorsResponse>;
  forecast: Panel<ForecastResponse>;
  overview: Panel<CityOverview>;
  cursor: number;
  cityAggregate?: CityAggregateResponse | null;
}

const LAYER_DEFS: Array<{ key: keyof MapLayers; label: string }> = [
  { key: "stations", label: "Stations" },
  { key: "heatmap", label: "Heatmap" },
  { key: "fires", label: "Fires" },
  { key: "industries", label: "Industries" },
];

const MODE_DEFS: Array<{ key: RenderMode; label: string }> = [
  { key: "auto", label: "Auto" },
  { key: "tiles", label: "Live" },
  { key: "offline", label: "Offline" },
];

/**
 * The map section. One shell that owns selection, layer, style and render-mode
 * state, and swaps between two renderers that share it all:
 *   - online (or forced "Live") → a real interactive Leaflet map on keyless tiles
 *   - offline (or forced/failed) → the self-contained Canvas schematic
 *
 * The whole section is encased in an outer glassmorphic container with the
 * 3D Physics Lanyard card hanging dynamically from the top ceiling anchor.
 */
export function StationMap({
  stations,
  plume,
  forecast,
  overview,
  cursor,
  cityAggregate,
}: StationMapProps) {
  const { t } = useTranslation();
  const online = useOnline();
  const reduced = useReducedMotion();

  const [selectedUid, setSelectedUid] = useState<string | null>(null);
  const [layers, setLayers] = useState<MapLayers>({
    stations: true,
    heatmap: false,
    fires: true,
    industries: true,
  });
  const [industries, setIndustries] = useState<IndustryRecord[]>([]);
  const [industryTierFilter, setIndustryTierFilter] = useState<IndustryTierFilter>("all");
  const [styleId, setStyleId] = useState<MapStyleId>("dark");
  const [renderMode, setRenderMode] = useState<RenderMode>("auto");
  const [tileFailed, setTileFailed] = useState(false);

  const tileErrCount = useRef(0);

  // Fetch Delhi-only industry facilities (Supabase database-level filtered)
  useEffect(() => {
    let active = true;
    fetchDelhiIndustries().then((records) => {
      if (active && records.length > 0) {
        setIndustries(records);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const { filteredIndustries, tier1Count, tier2Count, tier3Count } = useMemo(() => {
    let t1 = 0;
    let t2 = 0;
    let t3 = 0;
    const filtered: IndustryRecord[] = [];

    for (const ind of industries) {
      const info = classifyIndustryTier(ind);
      if (info.tier === 1) t1++;
      else if (info.tier === 2) t2++;
      else t3++;

      if (industryTierFilter === "all") {
        filtered.push(ind);
      } else if (industryTierFilter === "tier1" && info.tier === 1) {
        filtered.push(ind);
      } else if (industryTierFilter === "tier2" && info.tier === 2) {
        filtered.push(ind);
      } else if (industryTierFilter === "tier3" && info.tier === 3) {
        filtered.push(ind);
      }
    }

    return {
      filteredIndustries: filtered,
      tier1Count: t1,
      tier2Count: t2,
      tier3Count: t3,
    };
  }, [industries, industryTierFilter]);

  // Clean slate whenever style changes
  useEffect(() => {
    tileErrCount.current = 0;
    setTileFailed(false);
  }, [styleId]);

  const onTileError = useCallback(() => {
    tileErrCount.current += 1;
    if (tileErrCount.current >= TILE_ERROR_LIMIT) setTileFailed(true);
  }, []);

  const stationList = stations.data ?? [];
  const selected = useMemo(
    () => stationList.find((s) => s.uid === selectedUid) ?? null,
    [stationList, selectedUid],
  );

  const useTiles =
    renderMode === "tiles" ? true : renderMode === "offline" ? false : online && !tileFailed;

  const chooseMode = useCallback((mode: RenderMode) => {
    if (mode === "tiles") {
      tileErrCount.current = 0;
      setTileFailed(false);
    }
    setRenderMode(mode);
  }, []);

  const toggleLayer = useCallback((key: keyof MapLayers) => {
    setLayers((l) => ({ ...l, [key]: !l[key] }));
  }, []);

  const clearSelection = useCallback(() => setSelectedUid(null), []);

  const feedsLoading = stations.status === "loading" && plume.status === "loading";
  const stationsFailed = stations.status === "error";
  const noFires = layers.fires && plume.data != null && plume.data.hotspots.length === 0;

  const statusLabel = useTiles
    ? "live tiles"
    : renderMode === "offline" || !online
      ? "offline · schematic"
      : "tiles unavailable · schematic";

  return (
    <section className="section section--map station-map-outer" aria-labelledby="map-h">
      <div className="station-map-layout">
        {/* Left Column: Heading, Controls, Viewport */}
        <div className="station-map-main">
          <div className="section__head">
            <div>
              <p className="eyebrow">network</p>
              <h2 className="section__h section__h--sm" id="map-h">
                Station map
              </h2>
              <p className="section__lede section__lede--sm">
                The live OpenAQ network across Delhi-NCR, each station a plume marker sized and coloured
                by its AQI, over the stubble-transport domain. Pick a basemap, toggle the layers, and
                click any station for its exact reading.
              </p>
            </div>
          </div>

          <div className="map__controls" role="group" aria-label="Map controls">
            <div className="map__ctrlGroup">
              <span className="map__ctrlLabel">basemap</span>
              <div className="map__ctrlRow">
                {MAP_STYLE_ORDER.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className="btn btn--solid map__ctrlBtn"
                    aria-pressed={styleId === id}
                    onClick={() => setStyleId(id)}
                  >
                    {MAP_STYLES[id].label}
                  </button>
                ))}
              </div>
            </div>

            <div className="map__ctrlGroup">
              <span className="map__ctrlLabel">layers</span>
              <div className="map__ctrlRow">
                {LAYER_DEFS.map(({ key, label }) => (
                  <button
                    key={key}
                    type="button"
                    className="btn btn--solid map__ctrlBtn"
                    aria-pressed={layers[key]}
                    onClick={() => toggleLayer(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="map__ctrlGroup">
              <span className="map__ctrlLabel">render</span>
              <div className="map__ctrlRow">
                {MODE_DEFS.map(({ key, label }) => (
                  <button
                    key={key}
                    type="button"
                    className="btn btn--solid map__ctrlBtn"
                    aria-pressed={renderMode === key}
                    onClick={() => chooseMode(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Premium Industry Pollution Stage / Tier Filter Toolbar */}
          {layers.industries && (
            <div
              style={{
                marginTop: "0.85rem",
                padding: "0.6rem 0.9rem",
                background: "linear-gradient(135deg, rgba(24, 20, 50, 0.65) 0%, rgba(15, 23, 42, 0.8) 100%)",
                border: "1px solid rgba(168, 85, 247, 0.25)",
                borderRadius: "10px",
                display: "flex",
                flexWrap: "wrap",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "0.6rem",
                backdropFilter: "blur(10px)",
                boxShadow: "0 4px 20px -5px rgba(0, 0, 0, 0.4)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 700,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    color: "#c084fc",
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                  }}
                >
                  🏭 {t("map.industryPollutionTier")}
                </span>
                <span style={{ fontSize: "11px", color: "#475569" }}>•</span>
                <span style={{ fontSize: "11px", color: "#94a3b8", fontWeight: 500 }}>
                  {t("map.activeUnits")}: <strong style={{ color: "#f8fafc" }}>{filteredIndustries.length.toLocaleString()}</strong> {t("map.ofUnits")} {industries.length.toLocaleString()} {t("map.units")}
                </span>
              </div>

              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
                <button
                  type="button"
                  className={`btn btn--solid map__ctrlBtn`}
                  style={{
                    fontSize: "11px",
                    padding: "3px 9px",
                    borderColor: industryTierFilter === "all" ? "#a855f7" : "rgba(148, 163, 184, 0.2)",
                    background: industryTierFilter === "all" ? "rgba(168, 85, 247, 0.25)" : "transparent",
                    color: industryTierFilter === "all" ? "#ffffff" : "#94a3b8",
                  }}
                  onClick={() => setIndustryTierFilter("all")}
                >
                  {t("map.allTiers")} ({industries.length.toLocaleString()})
                </button>
                <button
                  type="button"
                  className={`btn btn--solid map__ctrlBtn`}
                  style={{
                    fontSize: "11px",
                    padding: "3px 9px",
                    color: industryTierFilter === "tier1" ? "#ffffff" : "#fca5a5",
                    borderColor: industryTierFilter === "tier1" ? "#ef4444" : "rgba(239, 68, 68, 0.35)",
                    background: industryTierFilter === "tier1" ? "rgba(239, 68, 68, 0.3)" : "rgba(239, 68, 68, 0.08)",
                  }}
                  onClick={() => setIndustryTierFilter("tier1")}
                >
                  🔴 {t("map.tier1")} ({tier1Count.toLocaleString()})
                </button>
                <button
                  type="button"
                  className={`btn btn--solid map__ctrlBtn`}
                  style={{
                    fontSize: "11px",
                    padding: "3px 9px",
                    color: industryTierFilter === "tier2" ? "#ffffff" : "#fdba74",
                    borderColor: industryTierFilter === "tier2" ? "#f97316" : "rgba(249, 115, 22, 0.35)",
                    background: industryTierFilter === "tier2" ? "rgba(249, 115, 22, 0.3)" : "rgba(249, 115, 22, 0.08)",
                  }}
                  onClick={() => setIndustryTierFilter("tier2")}
                >
                  🟠 {t("map.tier2")} ({tier2Count.toLocaleString()})
                </button>
                <button
                  type="button"
                  className={`btn btn--solid map__ctrlBtn`}
                  style={{
                    fontSize: "11px",
                    padding: "3px 9px",
                    color: industryTierFilter === "tier3" ? "#ffffff" : "#d8b4fe",
                    borderColor: industryTierFilter === "tier3" ? "#a855f7" : "rgba(168, 85, 247, 0.35)",
                    background: industryTierFilter === "tier3" ? "rgba(168, 85, 247, 0.3)" : "rgba(168, 85, 247, 0.08)",
                  }}
                  onClick={() => setIndustryTierFilter("tier3")}
                >
                  🟢 {t("map.tier3")} ({tier3Count.toLocaleString()})
                </button>
              </div>
            </div>
          )}

          <div className="map__viewport plume__mapWrap" style={{ marginTop: '1.2rem' }}>
            {useTiles ? (
              <Suspense fallback={<Skeleton style={{ width: "100%", height: "100%" }} />}>
                <MapLeaflet
                  stations={layers.stations ? stationList : []}
                  plume={plume.data}
                  industries={layers.industries ? filteredIndustries : []}
                  layers={layers}
                  style={MAP_STYLES[styleId]}
                  selectedUid={selectedUid}
                  onSelect={setSelectedUid}
                  onTileError={onTileError}
                />
              </Suspense>
            ) : (
              <MapCanvas
                stations={stationList}
                plume={plume.data}
                industries={layers.industries ? filteredIndustries : []}
                layers={layers}
                style={styleId}
                cursor={cursor}
                selectedUid={selectedUid}
                onSelect={setSelectedUid}
                animate={!reduced}
              />
            )}

            <span className="map__badge" aria-hidden={false}>
              <i className="map__badgeDot" data-live={useTiles} />
              {statusLabel}
            </span>

            <div className="map__ov">
              {feedsLoading ? <p className="map__flag">loading live feeds…</p> : null}
              {stationsFailed ? (
                <p className="map__flag">
                  <b>Live station data unavailable.</b> Basemap and fire transport are shown; no
                  station markers are invented in their place.
                </p>
              ) : null}
              {noFires ? (
                <p className="map__flag">
                  No active fire detections in the transport domain — nothing is inferred where FIRMS
                  reports nothing.
                </p>
              ) : null}

              {layers.heatmap ? (
                <figure className="map__legend">
                  <span
                    className="map__legendBar"
                    style={{
                      background: `linear-gradient(90deg, ${Object.values(HEAT_GRADIENT).join(", ")})`,
                    }}
                  />
                  <figcaption className="map__legendCap">
                    AQI surface · interpolated from {stationList.length} live stations — not measured
                    between them
                  </figcaption>
                </figure>
              ) : null}
            </div>
          </div>
        </div>

        {/* Right Column: Full-Height Hanging 3D Lanyard Pass from Top Ceiling */}
        <div className="station-map-side">
          <StationDetail
            station={selected}
            overview={overview.data}
            plume={plume.data}
            forecast={forecast.data}
            cursor={cursor}
            stationCount={stationList.length}
            cityAggregate={cityAggregate}
            onClear={clearSelection}
          />
        </div>
      </div>
    </section>
  );
}
