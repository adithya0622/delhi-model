"""
Delhi NCR AQI Forecasting Dashboard — Real-Time Edition
=========================================================
Data: OpenAQ API v3 (Live CPCB/DPCC Monitors)
Map:  Folium with AQI-coloured station markers
"""
import math
import os
from datetime import datetime

import folium
import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import folium_static

# ── Config ────────────────────────────────────────────────────────────────────
BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")
REFRESH  = 300   # 5 min cache for live data

AQI_BANDS = [
    (0,   50,  "Good",         "#009966"),
    (51,  100, "Satisfactory", "#ffde33"),
    (101, 200, "Moderate",     "#ff9933"),
    (201, 300, "Poor",         "#cc0033"),
    (301, 400, "Very Poor",    "#660099"),
    (401, 500, "Severe",       "#7e0023"),
]

# US EPA bands. Different boundaries AND different names from CPCB — EPA breaks at
# 150 where CPCB breaks at 200. NowCast mode computes sub-indices from EPA
# breakpoints, so labelling those numbers with the CPCB table above would call an
# EPA 150 "Moderate" when EPA calls it "Unhealthy for Sensitive Groups".
AQI_BANDS_EPA = [
    (0,   50,  "Good",                           "#009966"),
    (51,  100, "Moderate",                       "#ffde33"),
    (101, 150, "Unhealthy for Sensitive Groups", "#ff9933"),
    (151, 200, "Unhealthy",                      "#cc0033"),
    (201, 300, "Very Unhealthy",                 "#660099"),
    (301, 500, "Hazardous",                      "#7e0023"),
]

def _bands(mode: str = "instant") -> list[tuple]:
    return AQI_BANDS_EPA if mode == "nowcast" else AQI_BANDS

def _cat_color(aqi: int, mode: str = "instant") -> tuple[str, str]:
    table = _bands(mode)
    for lo, hi, label, color in table:
        if lo <= aqi <= hi:
            return label, color
    return table[-1][2], table[-1][3]

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Delhi NCR AQI — Live Dashboard",
    page_icon="🌫️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;900&display=swap');
html, body, [class*="css"] { font-family:'Inter',sans-serif; }
.main { background:#0e1117; }
.card {
  background:linear-gradient(135deg,#1a1f2e,#242938);
  border:1px solid #2d3748; border-radius:14px;
  padding:18px 22px; text-align:center;
}
.big { font-size:2.6rem; font-weight:800; line-height:1.1; }
.sub { font-size:.78rem; color:#a0aec0; text-transform:uppercase;
       letter-spacing:.1em; margin-bottom:6px; }
.badge {
  display:inline-block; padding:4px 16px; border-radius:20px;
  font-weight:700; font-size:.9rem; color:#fff; margin-top:6px;
}
.sh { font-size:.9rem; font-weight:600; color:#a0aec0;
      text-transform:uppercase; letter-spacing:.1em;
      border-bottom:1px solid #2d3748; padding-bottom:6px; margin-bottom:10px; }
.poll-row { display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }
.poll-chip {
  background:#1a1f2e; border:1px solid #2d3748; border-radius:8px;
  padding:8px 14px; flex:1; min-width:80px; text-align:center;
}
.poll-val { font-size:1.4rem; font-weight:700; }
.poll-lbl { font-size:.7rem; color:#718096; }
</style>
""", unsafe_allow_html=True)

# ── Data fetchers ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=REFRESH)
def _fetch_overview(mode: str) -> dict:
    r = httpx.get(f"{BACKEND}/api/v1/realtime/overview", params={"mode": mode}, timeout=45.0)
    r.raise_for_status()
    return r.json()

def get_overview(mode: str) -> dict:
    try:
        return _fetch_overview(mode)
    except Exception:
        return {}

@st.cache_data(ttl=REFRESH)
def _fetch_stations(mode: str) -> list[dict]:
    r = httpx.get(f"{BACKEND}/api/v1/realtime/stations", params={"mode": mode}, timeout=45)
    r.raise_for_status()
    return r.json()

def get_stations(mode: str) -> list[dict]:
    try:
        return _fetch_stations(mode)
    except Exception:
        return []

@st.cache_data(ttl=REFRESH)
def _fetch_station_detail(uid: str, mode: str) -> dict:
    r = httpx.get(f"{BACKEND}/api/v1/realtime/station/{uid}",
                  params={"mode": mode}, timeout=15)
    r.raise_for_status()
    return r.json()

def get_station_detail(uid: str, mode: str = "instant") -> dict:
    try:
        return _fetch_station_detail(uid, mode)
    except Exception:
        return {}

@st.cache_data(ttl=REFRESH)
def _fetch_forecast(lat: float, lon: float, name: str, base_aqi: int = 0) -> dict | None:
    params = {"lat": lat, "lon": lon, "station_name": name}
    if base_aqi > 0:
        params["base_aqi"] = base_aqi
    r = httpx.get(f"{BACKEND}/api/v1/forecast/72hr", params=params, timeout=45)
    r.raise_for_status()
    return r.json()

def get_forecast(lat: float, lon: float, name: str, base_aqi: int = 0) -> dict | None:
    try:
        return _fetch_forecast(lat, lon, name, base_aqi)
    except Exception:
        return None

# ── Inversion status fetcher ──────────────────────────────────────────────────
@st.cache_data(ttl=REFRESH)
def _fetch_inversion() -> list[dict]:
    r = httpx.get(f"{BACKEND}/api/v1/inversion/status", timeout=15)
    r.raise_for_status()
    return r.json()

def get_inversion() -> list[dict]:
    try:
        return _fetch_inversion()
    except Exception:
        return []

# ── Plume vectors fetcher ─────────────────────────────────────────────────────
@st.cache_data(ttl=REFRESH)
def _fetch_plumes() -> dict:
    r = httpx.get(f"{BACKEND}/api/v1/plume/vectors", timeout=20)
    r.raise_for_status()
    return r.json()

def get_plumes() -> dict:
    try:
        return _fetch_plumes()
    except Exception:
        return {"hotspots": [], "plumes": [], "wind_850hpa_u": 0, "wind_850hpa_v": 0}

def make_pollution_map(stations: list[dict], selected_uid=None, plume_data: dict | None = None) -> folium.Map:
    m = folium.Map(
        location=[28.65, 77.22],
        zoom_start=11,
        tiles="CartoDB dark_matter",
        prefer_canvas=True,
    )

    for s in stations:
        aqi   = s.get("aqi", 0)
        color = s.get("color", "#888")
        name  = s.get("name", "Unknown")
        # Prefer the backend's label: it was computed with whichever breakpoint
        # table produced this AQI, so it is correct in both instant and nowcast
        # mode without the frontend needing to know which.
        label = s.get("category") or _cat_color(aqi)[0]
        uid   = s.get("uid")

        # Radius scales with AQI severity
        radius = max(8, min(22, aqi / 18))

        # Highlight selected station
        weight = 4 if str(uid) == str(selected_uid) else 1.5
        opacity = 1.0 if str(uid) == str(selected_uid) else 0.82

        popup_html = f"""
        <div style='font-family:Inter,sans-serif;min-width:180px'>
          <b style='font-size:13px'>{name}</b><br>
          <span style='font-size:22px;font-weight:800;color:{color}'>{aqi}</span>
          <span style='color:#666;font-size:12px'> AQI</span><br>
          <span style='background:{color};color:#fff;padding:2px 10px;
                border-radius:10px;font-size:11px'>{label}</span><br>
          <span style='color:#888;font-size:11px'>Click for details</span>
        </div>"""

        folium.CircleMarker(
            location=[s["lat"], s["lon"]],
            radius=radius,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=opacity,
            weight=weight,
            popup=folium.Popup(popup_html, max_width=220),
            tooltip=f"{name}: AQI {aqi} ({label})",
        ).add_to(m)

    # ── FIRMS hotspot markers + plume trajectory polylines ───────────────────
    if plume_data:
        hotspots = plume_data.get("hotspots", [])
        plumes = plume_data.get("plumes", [])

        for plume in plumes:
            traj = plume.get("trajectory", [])
            if len(traj) < 2:
                continue
            arrival = plume.get("arrival_delhi_t_hours")
            color = "#ff4500" if arrival is not None else "#ff8c00"
            conc = plume.get("pm25_contribution_ug_m3", 0.0) or 0.0
            closest = plume.get("closest_approach_km", 0.0) or 0.0
            arrival_txt = f"{arrival:.0f}h" if arrival is not None else "Misses Delhi"
            folium.PolyLine(
                locations=traj,
                color=color,
                weight=2,
                opacity=0.75,
                dash_array="6 4",
                tooltip=(
                    f"Plume | FRP {plume['origin']['frp_mw']:.0f} MW | "
                    f"arrival {arrival_txt} | closest {closest:.0f} km | "
                    f"+{conc:.1f} µg/m³ in transport layer"
                ),
            ).add_to(m)

        for hs in hotspots:
            frp = hs.get("frp_mw", 0.0) or 0.0
            # Scale the marker with fire intensity so a 400 MW fire is visually
            # distinct from a 5 MW one, but keep it readable when hundreds
            # overlap.
            radius = max(3.0, min(11.0, 3.0 + (frp ** 0.5)))
            folium.CircleMarker(
                location=[hs["lat"], hs["lon"]],
                radius=radius,
                color="#ff4500",
                fill=True,
                fill_color="#ff4500",
                fill_opacity=0.9,
                weight=1,
                tooltip=(
                    f"🔥 {hs.get('source_state', 'Unknown')} | {frp:.0f} MW FRP | "
                    f"detected {str(hs.get('detected_at', ''))[:16].replace('T', ' ')}"
                ),
            ).add_to(m)

        if not hotspots:
            folium.Marker(
                location=[28.65, 77.22],
                icon=folium.DivIcon(
                    html='<div style="color:#4a5568;font-size:11px;white-space:nowrap">'
                         '🔥 No active fire hotspots detected</div>',
                    icon_size=(220, 20),
                ),
            ).add_to(m)

    return m



# ── Sub-index bar chart ───────────────────────────────────────────────────────
def pollutant_chart(pollutants: dict) -> go.Figure:
    names, vals, colors = [], [], []
    for p, v in pollutants.items():
        if v is None:
            continue
        aqi_approx = int(v)  # raw µg/m³ — display as concentration, not sub-index
        _, color = _cat_color(aqi_approx) if p in ("PM2.5", "PM10") else ("#4299e1", "#4299e1")
        names.append(p)
        vals.append(round(v, 1))
        colors.append(color if p in ("PM2.5", "PM10") else "#4299e1")

    fig = go.Figure(go.Bar(
        x=names, y=vals,
        marker_color=colors,
        text=[f"{v}" for v in vals],
        textposition="outside",
        textfont={"color": "#e2e8f0", "size": 12},
    ))
    fig.update_layout(
        height=200, paper_bgcolor="#1a1f2e", plot_bgcolor="#1a1f2e",
        font={"color": "#e2e8f0"}, margin={"t": 20, "b": 30, "l": 40, "r": 20},
        yaxis={"gridcolor": "#2d3748", "title": "µg/m³"},
        xaxis={"gridcolor": "#2d3748"},
        showlegend=False,
    )
    return fig


# ── 72h AQI timeline ──────────────────────────────────────────────────────────
def aqi_timeline(forecast_hours: list[dict]) -> go.Figure:
    df = pd.DataFrame(forecast_hours)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    fig = go.Figure()
    for lo, hi, name, color in AQI_BANDS:
        fig.add_hrect(y0=lo, y1=hi, fillcolor=color, opacity=0.07,
                      line_width=0,
                      annotation_text=name if lo in [0, 201, 401] else "",
                      annotation_position="right",
                      annotation_font={"color": color, "size": 9})

    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["pbl_height_m"],
        name="PBL Height (m)", yaxis="y2",
        line={"color": "#4299e1", "dash": "dot", "width": 1.2}, opacity=0.5))

    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["aqi"] * df["plume_contribution"],
        name="Stubble-burn",
        fill="tozeroy", fillcolor="rgba(255,100,0,0.12)",
        line={"width": 0}, mode="lines"))

    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["aqi"],
        name="AQI Forecast", mode="lines+markers",
        line={"color": "#f6ad55", "width": 2.5},
        marker={"size": 4,
                "color": df["aqi"],
                "colorscale": [[0,"#009966"],[.2,"#ffde33"],[.4,"#ff9933"],
                               [.6,"#cc0033"],[.8,"#660099"],[1,"#7e0023"]],
                "cmin": 0, "cmax": 500},
        hovertemplate="<b>%{x|%a %d %b %H:%M IST}</b><br>AQI: %{y}<extra></extra>",
    ))

    fig.update_layout(
        height=300, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        font={"color": "#e2e8f0"}, margin={"t": 10, "b": 40, "l": 50, "r": 80},
        legend={"orientation": "h", "y": -0.25, "font": {"size": 10}},
        xaxis={"gridcolor": "#2d3748", "title": "Time (IST)"},
        yaxis={"gridcolor": "#2d3748", "range": [0, 520], "title": "AQI"},
        yaxis2={"overlaying": "y", "side": "right", "title": "PBL (m)",
                "showgrid": False, "range": [0, 2400]},
        hovermode="x unified",
    )
    return fig


# ── Chemistry → meteorology feedback timeline ─────────────────────────────────
def feedback_timeline(forecast_hours: list[dict]) -> go.Figure:
    """
    The return leg of the coupling, plotted so it can be audited.

    Left axis: mixing depth before and after the aerosol perturbation. The gap
    between the two lines IS the feedback. Right axis: column AOD driving it.
    """
    df = pd.DataFrame(forecast_hours)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df.get("pbl_height_met_m", df["pbl_height_m"]),
        name="PBL — met model (no aerosol)", mode="lines",
        line={"color": "#63b3ed", "width": 1.6, "dash": "dash"},
        hovertemplate="%{y:.0f} m<extra>met model</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["pbl_height_m"],
        name="PBL — after aerosol feedback", mode="lines",
        line={"color": "#f6ad55", "width": 2.2},
        fill="tonexty", fillcolor="rgba(246,173,85,0.16)",
        hovertemplate="%{y:.0f} m<extra>with feedback</extra>",
    ))
    if "aerosol_optical_depth" in df:
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["aerosol_optical_depth"],
            name="Column AOD", yaxis="y2", mode="lines",
            line={"color": "#b794f4", "width": 1.4},
            hovertemplate="AOD %{y:.2f}<extra></extra>",
        ))

    fig.update_layout(
        height=260, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        font={"color": "#e2e8f0"}, margin={"t": 10, "b": 40, "l": 50, "r": 60},
        legend={"orientation": "h", "y": -0.28, "font": {"size": 10}},
        xaxis={"gridcolor": "#2d3748", "title": "Time (IST)"},
        yaxis={"gridcolor": "#2d3748", "title": "Mixing depth (m)",
               "rangemode": "tozero"},
        yaxis2={"overlaying": "y", "side": "right", "title": "AOD",
                "showgrid": False, "rangemode": "tozero"},
        hovermode="x unified",
    )
    return fig


# ── Inversion strength tracking over the forecast window ──────────────────────
def inversion_timeline(series: list[dict]) -> go.Figure:
    df = pd.DataFrame(series)
    if df.empty:
        return go.Figure()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    fig = go.Figure()
    # Shade the severity bands so a glance shows how long the lid holds.
    for lo, hi, name, color in [(1.5, 3.5, "Weak", "#ffde33"),
                                (3.5, 6.0, "Moderate", "#ff9933"),
                                (6.0, 14.0, "Strong", "#cc0033")]:
        fig.add_hrect(y0=lo, y1=hi, fillcolor=color, opacity=0.08, line_width=0,
                      annotation_text=name, annotation_position="right",
                      annotation_font={"color": color, "size": 9})
    fig.add_hline(y=0, line={"color": "#4a5568", "width": 1})

    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["delta_t_celsius"],
        name="ΔT (925–1000 hPa)", mode="lines",
        line={"color": "#fc8181", "width": 2.2},
        hovertemplate="ΔT %{y:+.1f} °C<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["pbl_height_m"],
        name="PBL height (m)", yaxis="y2", mode="lines",
        line={"color": "#68d391", "width": 1.4, "dash": "dot"},
        hovertemplate="PBL %{y:.0f} m<extra></extra>",
    ))

    fig.update_layout(
        height=250, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        font={"color": "#e2e8f0"}, margin={"t": 10, "b": 40, "l": 50, "r": 70},
        legend={"orientation": "h", "y": -0.28, "font": {"size": 10}},
        xaxis={"gridcolor": "#2d3748", "title": "Time (IST)"},
        yaxis={"gridcolor": "#2d3748", "title": "ΔT (°C)"},
        yaxis2={"overlaying": "y", "side": "right", "title": "PBL (m)",
                "showgrid": False, "rangemode": "tozero"},
        hovermode="x unified",
    )
    return fig


# ── AQI gauge ────────────────────────────────────────────────────────────────
def aqi_gauge(aqi: int, color: str) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=aqi,
        number={"font": {"size": 52, "color": color}},
        gauge={
            "axis": {"range": [0, 500], "tickcolor": "#4a5568",
                     "tickfont": {"color": "#718096", "size": 10}},
            "bar": {"color": color, "thickness": 0.22},
            "bgcolor": "#1a1f2e", "bordercolor": "#2d3748",
            "steps": [
                {"range": [0,   50],  "color": "rgba(0,153,102,0.12)"},
                {"range": [50,  100], "color": "rgba(255,222,51,0.12)"},
                {"range": [100, 200], "color": "rgba(255,153,51,0.12)"},
                {"range": [200, 300], "color": "rgba(204,0,51,0.12)"},
                {"range": [300, 400], "color": "rgba(102,0,153,0.12)"},
                {"range": [400, 500], "color": "rgba(126,0,35,0.12)"},
            ],
            "threshold": {"line": {"color": color, "width": 3},
                          "thickness": 0.75, "value": aqi},
        },
    ))
    fig.update_layout(
        height=200, margin={"t": 10, "b": 0, "l": 20, "r": 20},
        paper_bgcolor="#1a1f2e", font_color="#e2e8f0",
    )
    return fig


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🌫️ Delhi NCR AQI")
    st.caption("Data Source: OpenAQ API v3 (Live CPCB/DPCC Monitors)")
    st.divider()

    if st.button("🔄 Refresh Now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.markdown("**AQI Calculation Mode**")
    mode_map = {
        "Real-time Instant (Default)": "instant",
        "EPA NowCast (24-hr Benchmark)": "nowcast"
    }
    mode_selection = st.radio(
        "Select Mode:",
        options=list(mode_map.keys()),
        index=0,
        label_visibility="collapsed"
    )
    selected_mode = mode_map[mode_selection]
    
    st.divider()
    st.markdown("**Data Sources**")
    st.caption("📡 OpenAQ v3 (CPCB/DPCC live feeds)")
    st.caption("🛰️ NASA FIRMS VIIRS fire hotspots")
    st.caption("🌐 Open-Meteo pressure-level met")
    st.caption("📐 CPCB AQI Methodology 2014")
    st.divider()

    st.markdown("**Status**")
    st.caption("🟢 Connected: OpenAQ Live Stream")
    st.divider()
    st.caption(f"⏱ {datetime.now().strftime('%d %b %Y %H:%M IST')}")


# ── Load data ─────────────────────────────────────────────────────────────────
with st.spinner("Fetching live CPCB data..."):
    overview   = get_overview(selected_mode)
    stations   = get_stations(selected_mode)
    inv_series = get_inversion()
    plume_data = get_plumes()

if not stations:
    st.error("⚠️ Could not reach backend. Is it running?")
    st.code("cd backend && uvicorn app.main:app --reload")
    st.stop()

# ── Title ────────────────────────────────────────────────────────────────────
st.markdown("## 🌫️ Delhi NCR — Live Air Quality Dashboard")
mode_desc = "Live 1-hour sensor proxy (highly reactive)" if selected_mode == "instant" else "12-hour NowCast rolling average (official benchmark)"
# Report only what was actually returned. The previous "/ 113" denominator was
# hardcoded and did not come from any upstream field, so it implied a known total
# the dashboard had no way to know.
st.caption(f"Live stations reporting: {len(stations)} · "
           f"Updated: {overview.get('updated', 'N/A')} · "
           f"**{mode_desc}**")

# ── Row 1: Top-level metrics ──────────────────────────────────────────────────
ov_aqi    = overview.get("aqi", 0)
ov_label, ov_color = _cat_color(ov_aqi, selected_mode)

worst = max(stations, key=lambda x: x["aqi"])
best  = min(stations, key=lambda x: x["aqi"])
avg   = int(sum(s["aqi"] for s in stations) / len(stations))
avg_l, avg_c = _cat_color(avg, selected_mode)

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.markdown(f"""<div class="card">
        <div class="sub">Delhi Overall AQI</div>
        <div class="big" style="color:{ov_color}">{ov_aqi}</div>
        <div class="badge" style="background:{ov_color}">{ov_label}</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class="card">
        <div class="sub">Avg ({len(stations)} stations)</div>
        <div class="big" style="color:{avg_c}">{avg}</div>
        <div class="badge" style="background:{avg_c}">{avg_l}</div>
    </div>""", unsafe_allow_html=True)
with c3:
    wl, wc = _cat_color(worst["aqi"], selected_mode)
    st.markdown(f"""<div class="card">
        <div class="sub">Most Polluted</div>
        <div class="big" style="color:{wc}">{worst["aqi"]}</div>
        <div style="color:#718096;font-size:.75rem;margin-top:3px">{worst["name"].split(",")[0]}</div>
    </div>""", unsafe_allow_html=True)
with c4:
    bl, bc = _cat_color(best["aqi"], selected_mode)
    st.markdown(f"""<div class="card">
        <div class="sub">Cleanest Station</div>
        <div class="big" style="color:{bc}">{best["aqi"]}</div>
        <div style="color:#718096;font-size:.75rem;margin-top:3px">{best["name"].split(",")[0]}</div>
    </div>""", unsafe_allow_html=True)
with c5:
    pm25 = overview.get("pm25")
    st.markdown(f"""<div class="card">
        <div class="sub">PM2.5 (Delhi)</div>
        <div class="big" style="color:#f6ad55">{pm25 or "—"}</div>
        <div style="color:#718096;font-size:.75rem;margin-top:3px">µg/m³</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Inversion status panel ────────────────────────────────────────────────────
st.markdown('<div class="sh">🌡️ ATMOSPHERIC INVERSION & BOUNDARY LAYER</div>', unsafe_allow_html=True)

_inv_now = inv_series[0] if inv_series else {}
_inv_sev = _inv_now.get("severity", "N/A")
_inv_dt  = _inv_now.get("delta_t_celsius", 0)
_inv_pbl = _inv_now.get("pbl_height_m", 0)
_inv_amp = _inv_now.get("aqi_amplification_factor", 1.0)
_inv_present = _inv_now.get("inversion_present", False)

_sev_colors = {"None": "#009966", "Weak": "#ffde33", "Moderate": "#ff9933", "Strong": "#cc0033"}
_sev_col = _sev_colors.get(_inv_sev, "#718096")

i1, i2, i3, i4 = st.columns(4)
with i1:
    st.markdown(f"""<div class="card">
        <div class="sub">Inversion Severity</div>
        <div class="big" style="color:{_sev_col}">{_inv_sev}</div>
        <div class="badge" style="background:{_sev_col}">{'Active' if _inv_present else 'No Inversion'}</div>
    </div>""", unsafe_allow_html=True)
with i2:
    st.markdown(f"""<div class="card">
        <div class="sub">ΔT (925–1000 hPa)</div>
        <div class="big" style="color:#63b3ed">{_inv_dt:+.1f}°C</div>
        <div style="color:#718096;font-size:.75rem;margin-top:3px">Positive = Trapped lid</div>
    </div>""", unsafe_allow_html=True)
with i3:
    st.markdown(f"""<div class="card">
        <div class="sub">PBL Height</div>
        <div class="big" style="color:#68d391">{int(_inv_pbl)} m</div>
        <div style="color:#718096;font-size:.75rem;margin-top:3px">Mixing layer ceiling</div>
    </div>""", unsafe_allow_html=True)
with i4:
    st.markdown(f"""<div class="card">
        <div class="sub">Layer Compression</div>
        <div class="big" style="color:#f6ad55">{_inv_amp:.2f}×</div>
        <div style="color:#718096;font-size:.75rem;margin-top:3px">vs 1200 m well-mixed</div>
    </div>""", unsafe_allow_html=True)

st.caption(
    "Layer compression is a **diagnostic** of how shallow the mixing layer is "
    "(1200 m ÷ PBL). It is not multiplied into the AQI — concentrations come from "
    "a prognostic box model that accumulates mass under the lid, so the same ΔT "
    "gives a different AQI depending on how long the inversion has held."
)

if inv_series:
    st.plotly_chart(inversion_timeline(inv_series), use_container_width=True,
                    config={"displayModeBar": False})

st.markdown("<br>", unsafe_allow_html=True)

# ── Row 2: Map + Station Detail ───────────────────────────────────────────────
map_col, detail_col = st.columns([3, 2])

with map_col:
    st.markdown('<div class="sh">📍 LIVE POLLUTION MAP — DELHI NCR</div>',
                unsafe_allow_html=True)

    # Station selector above map (updates map highlight + detail panel)
    station_names = [f"{s['name']} — AQI {s['aqi']}" for s in stations]
    sel_idx = st.selectbox(
        "Select station for details",
        range(len(stations)),
        format_func=lambda i: station_names[i],
        key="sel_station",
    )
    sel = stations[sel_idx]

    fmap = make_pollution_map(stations, selected_uid=sel.get("uid"), plume_data=plume_data)
    folium_static(fmap, width=700, height=480)

with detail_col:
    st.markdown('<div class="sh">📊 STATION DETAIL</div>', unsafe_allow_html=True)

    # Fetch full detail for selected station
    uid_str = str(sel.get("uid", "delhi"))
    detail = get_station_detail(uid_str, selected_mode)

    # Use overview fallback if detail is empty (demo token limitation)
    display_aqi = detail.get("aqi") or sel["aqi"]
    display_label, display_color = _cat_color(display_aqi, selected_mode)

    # Gauge
    st.plotly_chart(aqi_gauge(display_aqi, display_color),
                    use_container_width=True, config={"displayModeBar": False})

    # Station name + category badge
    st.markdown(f"""
    <div style='text-align:center;margin-top:-10px'>
      <span style='color:#e2e8f0;font-weight:700;font-size:1rem'>{sel['name']}</span><br>
      <span class="badge" style="background:{display_color}">{display_label}</span>
      &nbsp;<span style="color:#718096;font-size:.8rem">
        {detail.get('dominant_pollutant', '') or ''}
      </span>
    </div>""", unsafe_allow_html=True)

    # Pollutant chips
    pollutants = detail.get("pollutants", {})
    if not pollutants or all(v is None for v in pollutants.values()):
        # Fallback: use overview data
        pollutants = {
            "PM2.5": overview.get("pm25"),
            "PM10":  overview.get("pm10"),
            "O3":    overview.get("o3"),
            "NO2":   overview.get("no2"),
        }

    chips_html = '<div class="poll-row">'
    poll_colors = {"PM2.5": "#f6ad55", "PM10": "#fc8181", "O3": "#68d391",
                   "NO2": "#63b3ed", "SO2": "#b794f4", "CO": "#f687b3"}
    for p, v in pollutants.items():
        if v is None:
            continue
        pc = poll_colors.get(p, "#a0aec0")
        chips_html += f"""<div class="poll-chip">
          <div class="poll-val" style="color:{pc}">{round(v,1)}</div>
          <div class="poll-lbl">{p} µg/m³</div>
        </div>"""
    chips_html += "</div>"
    st.markdown(chips_html, unsafe_allow_html=True)

    # Weather strip
    weather = detail.get("weather", {})
    if any(weather.values()):
        st.markdown("<br>", unsafe_allow_html=True)
        wc1, wc2, wc3 = st.columns(3)
        if weather.get("temperature_c") is not None:
            wc1.metric("🌡 Temp", f"{weather['temperature_c']}°C")
        if weather.get("humidity_pct") is not None:
            wc2.metric("💧 Humidity", f"{weather['humidity_pct']}%")
        if weather.get("wind_ms") is not None:
            wc3.metric("💨 Wind", f"{weather['wind_ms']} m/s")

# ── Row 3: Pollutant bar chart (full width) ────────────────────────────────────
st.markdown('<div class="sh">🧪 POLLUTANT CONCENTRATIONS</div>', unsafe_allow_html=True)
full_polls = detail.get("pollutants", {}) or {
    "PM2.5": overview.get("pm25"), "PM10": overview.get("pm10"),
    "O3": overview.get("o3"), "NO2": overview.get("no2"),
}
st.plotly_chart(pollutant_chart(full_polls), use_container_width=True,
                config={"displayModeBar": False})

# ── Row 4: 72h forecast ───────────────────────────────────────────────────────
st.markdown('<div class="sh">📅 72-HOUR AQI FORECAST (Physics Model + Plume Advection)</div>',
            unsafe_allow_html=True)

# Clamp lat/lon to Delhi NCR bbox for physics model
lat = max(28.0, min(29.0, sel.get("lat", 28.6139)))
lon = max(76.5, min(77.8, sel.get("lon", 77.2090)))
sname = sel["name"][:64]

forecast = get_forecast(lat, lon, sname, base_aqi=display_aqi)
if forecast:
    hours = forecast["forecast_hours"]
    peak  = max(hours, key=lambda h: h["aqi"])
    peak_dt = datetime.fromisoformat(peak["timestamp"]).strftime("%a %d %b %H:%M")

    fc1, fc2, fc3 = st.columns(3)
    # Hour-0 now equals display_aqi due to smooth anchoring — show live value directly
    fc1.metric("Live AQI (hour 0)", display_aqi, f"{display_label}")
    fc2.metric("Peak AQI (72h)", peak["aqi"], f"at {peak_dt}")
    fc3.metric("Plume impact now",
               f"{int(hours[0]['plume_contribution']*100)}%",
               "stubble burning")

    st.plotly_chart(aqi_timeline(hours), use_container_width=True,
                    config={"displayModeBar": False})

    # ── Chemistry → meteorology: the return leg of the coupling ───────────────
    st.markdown('<div class="sh">🔁 CHEMISTRY → METEOROLOGY FEEDBACK</div>',
                unsafe_allow_html=True)

    _peak_supp = max(hours, key=lambda h: h.get("pbl_suppression_pct", 0) or 0)
    _peak_aod = max(h.get("aerosol_optical_depth", 0) or 0 for h in hours)
    _peak_sw = min(h.get("aerosol_sw_forcing_w_m2", 0) or 0 for h in hours)
    _peak_dt = min(h.get("aerosol_dt_surface_c", 0) or 0 for h in hours)
    _max_iter = max(h.get("feedback_iterations", 1) or 1 for h in hours)

    g1, g2, g3, g4 = st.columns(4)
    with g1:
        st.markdown(f"""<div class="card">
            <div class="sub">Peak PBL Suppression</div>
            <div class="big" style="color:#f6ad55">{_peak_supp.get('pbl_suppression_pct', 0):.0f}%</div>
            <div style="color:#718096;font-size:.75rem;margin-top:3px">mixing depth removed by haze</div>
        </div>""", unsafe_allow_html=True)
    with g2:
        st.markdown(f"""<div class="card">
            <div class="sub">Peak Column AOD</div>
            <div class="big" style="color:#b794f4">{_peak_aod:.2f}</div>
            <div style="color:#718096;font-size:.75rem;margin-top:3px">optical thickness of the haze</div>
        </div>""", unsafe_allow_html=True)
    with g3:
        st.markdown(f"""<div class="card">
            <div class="sub">Surface Dimming</div>
            <div class="big" style="color:#63b3ed">{_peak_sw:.0f}</div>
            <div style="color:#718096;font-size:.75rem;margin-top:3px">W/m² shortwave removed</div>
        </div>""", unsafe_allow_html=True)
    with g4:
        st.markdown(f"""<div class="card">
            <div class="sub">Surface Cooling</div>
            <div class="big" style="color:#68d391">{_peak_dt:+.2f}°C</div>
            <div style="color:#718096;font-size:.75rem;margin-top:3px">converged in ≤{_max_iter} iterations</div>
        </div>""", unsafe_allow_html=True)

    st.plotly_chart(feedback_timeline(hours), use_container_width=True,
                    config={"displayModeBar": False})
    st.caption(
        "Trapped pollution dims the surface, which cools it, which weakens "
        "convection and lowers the lid — raising concentrations further. The shaded "
        "gap is that suppression. Shortwave dimming is zero at night by "
        "construction; the feedback survives after dark through an 8-hour surface "
        "thermal memory, which is why the following night's inversion is stronger."
    )
else:
    st.warning("Forecast unavailable — physics engine returning no data.")

# ── Row 4b: Stubble-burning source attribution ────────────────────────────────
st.markdown('<div class="sh">🔥 STUBBLE-BURNING PLUME TRANSPORT</div>',
            unsafe_allow_html=True)

_hs_total = plume_data.get("hotspot_count_total", len(plume_data.get("hotspots", [])))
_by_state: dict[str, int] = {}
for _h in plume_data.get("hotspots", []):
    _st_name = _h.get("source_state", "Unknown")
    _by_state[_st_name] = _by_state.get(_st_name, 0) + 1
_profile = plume_data.get("pm25_profile_ug_m3", []) or []
_peak_smoke = max(_profile) if _profile else 0.0
_u = plume_data.get("wind_850hpa_u", 0.0) or 0.0
_v = plume_data.get("wind_850hpa_v", 0.0) or 0.0
# Meteorological convention: the direction the wind blows FROM.
_wdir = (math.degrees(math.atan2(-_u, -_v)) + 360) % 360 if (_u or _v) else 0.0
_wspd = math.hypot(_u, _v)
_compass = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
_wname = _compass[int((_wdir + 11.25) % 360 / 22.5)] if _wspd > 0 else "—"

if _hs_total == 0:
    st.info(
        "No active fire detections in the Punjab–Haryana source region right now. "
        "This is a real answer from NASA FIRMS, not a data gap — no synthetic "
        "hotspots are ever substituted. Outside the late-October to November paddy "
        "residue window, zero is the expected reading."
    )
else:
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        st.markdown(f"""<div class="card">
            <div class="sub">Active Fire Detections</div>
            <div class="big" style="color:#ff4500">{_hs_total}</div>
            <div style="color:#718096;font-size:.75rem;margin-top:3px">VIIRS + MODIS, last 48 h</div>
        </div>""", unsafe_allow_html=True)
    with p2:
        st.markdown(f"""<div class="card">
            <div class="sub">Transport Wind (850 hPa)</div>
            <div class="big" style="color:#63b3ed">{_wname}</div>
            <div style="color:#718096;font-size:.75rem;margin-top:3px">{_wspd:.1f} m/s from {_wdir:.0f}°</div>
        </div>""", unsafe_allow_html=True)
    with p3:
        st.markdown(f"""<div class="card">
            <div class="sub">Peak Smoke Aloft</div>
            <div class="big" style="color:#f6ad55">{_peak_smoke:.0f}</div>
            <div style="color:#718096;font-size:.75rem;margin-top:3px">µg/m³ in transport layer</div>
        </div>""", unsafe_allow_html=True)
    with p4:
        _top = max(_by_state.items(), key=lambda kv: kv[1]) if _by_state else ("—", 0)
        st.markdown(f"""<div class="card">
            <div class="sub">Dominant Source</div>
            <div class="big" style="color:#fc8181;font-size:1.8rem">{_top[0]}</div>
            <div style="color:#718096;font-size:.75rem;margin-top:3px">{_top[1]} of {len(plume_data.get('hotspots', []))} mapped</div>
        </div>""", unsafe_allow_html=True)

    st.caption(
        f"Fires by state (largest contributors shown on the map): "
        + ", ".join(f"**{k}** {v}" for k, v in
                    sorted(_by_state.items(), key=lambda kv: -kv[1]))
        + ". Smoke concentrations are transport-layer values — long-range plumes "
        "arrive above the shallow nocturnal boundary layer, so most of the load "
        "only reaches street level when the mixing layer grows into it the next "
        "morning."
    )

# ── Row 5: All stations table ─────────────────────────────────────────────────
with st.expander(f"📋 All {len(stations)} Stations — Ranked by AQI", expanded=False):
    df = pd.DataFrame([{
        "Station":   s["name"],
        "AQI":       s["aqi"],
        "Category":  s["category"],
        "Latitude":  round(s["lat"], 4),
        "Longitude": round(s["lon"], 4),
        "Updated":   s.get("updated", ""),
    } for s in stations])

    def _style_aqi(val):
        try:
            v = int(val)
            for lo, hi, _, color in _bands(selected_mode):
                if lo <= v <= hi:
                    return f"background:{color}22;color:{color};font-weight:700"
        except Exception:
            pass
        return ""

    st.dataframe(
        df.style.map(_style_aqi, subset=["AQI"]),
        use_container_width=True,
        height=min(600, 38 + 36 * len(df)),
    )

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.markdown("""
<div style='text-align:center;color:#4a5568;font-size:.78rem'>
  Delhi NCR Live AQI Dashboard · Data: OpenAQ API v3 (Live CPCB/DPCC Monitors) ·
  Forecast: Open-Meteo + NASA FIRMS physics model · CPCB AQI Methodology 2014
</div>""", unsafe_allow_html=True)
