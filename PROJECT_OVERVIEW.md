# NCR-72: Real-Time Air Quality Intelligence & 72-Hour Physics-Informed ML Forecasting Engine

---

## Executive Summary
**NCR-72** is an advanced atmospheric intelligence and predictive forecasting platform engineered specifically for the National Capital Region (Delhi NCR). By unifying live ground-truth monitoring from **IQAir AirVisual**, multi-species chemical telemetry from **WeatherAPI**, and a **72-hour chemical regime Machine Learning model**, NCR-72 transforms raw, fragmented environmental data into actionable, hour-by-hour prognostic intelligence.

---

## 1. The Problems We Solve
1. **Delayed & Fragmented Data**: Traditional apps only report lagging historical readings without forward-looking predictability or chemical context.
2. **Standard & Scale Confusion**: Different sensors report conflicting numbers (e.g., physical mass concentration in µg/m³ vs. dimensionless EPA / CPCB AQI indices).
3. **Complex Atmospheric Trapping**: Delhi NCR experiences severe diurnal temperature inversions and boundary-layer collapse, trapping particulate matter (PM2.5, PM10) at night and driving toxic Ground-Level Ozone (O3) spikes in the afternoon.
4. **Lack of Source Accountability**: Citizens and authorities rarely know *where* the pollution originates (vehicular exhaust vs. dust vs. biomass vs. factories).

---

## 2. Core Architecture & Technical Innovations

\ ┌──────────────────────┐   ┌───────────────────────────┐   ┌──────────────────────────────┐
 │   Live Ingestion     │   │  Physics & Chemistry ML   │   │     Actionable Output        │
 │ • IQAir AirVisual    │──▶│ • HistGradientBoosting    │──▶│ • 72-Hour Dynamic Curve      │
 │ • WeatherAPI (6 Gas) │   │ • PBL Height & Inversion  │   │ • Source Apportionment       │
 │ • 50 Delhi Stations  │   │ • NOx-VOC Ozone Chemistry │   │ • Multilingual AI Assistant  │
 └──────────────────────┘   └───────────────────────────┘   └──────────────────────────────┘
\
### A. Multi-Provider Harmonization (Single Source of Truth)
- Ingests real-time criteria pollutants across **50 official Delhi NCR stations** (ITO, Anand Vihar, RK Puram, Punjabi Bagh, etc.).
- Anchors headline AQI to official **IQAir AirVisual live observations** on the US EPA 2024 standard, while maintaining calibrated physical concentrations for all 6 criteria pollutants (PM2.5, PM10, NO2, O3, SO2, CO).

### B. Chemical Regime & Boundary-Layer ML Forecasting (72h Horizon)
- Uses a trained **\HistGradientBoostingRegressor\** that couples atmospheric physics (Planetary Boundary Layer height, thermal inversion ΔT, wind vectors) with photochemical kinetics (NO2/O3 ratios, oxidation capacity).
- Produces a smooth, continuous **72-hour dynamic forecast curve** reflecting realistic diurnal rhythms (nighttime accumulation vs. daytime solar dispersion).

### C. Dynamic Source Apportionment & Fleet Breakdown
- Uses ambient NO2 chemical tracers to isolate vehicular exhaust from background dust, biomass burning, and industrial emissions.
- Models diurnal fleet dynamics: **Nighttime Heavy Truck Influx (61%)**, **Peak Rush-Hour Commuters (60%)**, and **Off-Peak Traffic**.

### D. Health Risk Optimization & Multilingual Neural AI
- **Personalized Exposure Window**: Recommends optimal jogging/cycling times across the 72-hour forecast to minimize cumulative particulate inhalation.
- **Multilingual Healthcare Assistant**: Powered by Groq AI and Google Neural Speech Synthesis, offering real-time medical guidance in **English, Hindi (हिंदी), and Tamil (தமிழ்)**.

---

## 3. Target Audience & Practical Impact

| Stakeholder | Key Value Delivered |
| :--- | :--- |
| **Citizens & Families** | Immediate awareness of actual air quality, safe outdoor exercise windows, mask & purifier advisories, and child/elderly health alerts. |
| **Municipal Authorities & Regulators** | Proactive 72-hour early warnings to trigger **Graded Response Action Plan (GRAP)** protocols, restrict diesel truck entries, and control industrial emissions *before* hazardous peaks occur. |
| **Researchers & Urban Planners** | Open access to synchronized atmospheric physics, chemical regimes, and spatial station plume dynamics across Delhi NCR. |

---

## 4. Platform Specifications & Access
- **Frontend Web Application**: Built with React, TypeScript, Tailwind CSS, Lucide Icons, and Recharts.
- **Backend API Engine**: Built with FastAPI, Python 3.12, Uvicorn, Scikit-Learn, and HTTPX.
- **Live Local URL**: [http://127.0.0.1:5173](http://127.0.0.1:5173)
- **Primary API Endpoints**:
  - \GET /api/v1/forecast/72hr-ml\: 72-hour Machine Learning forecast series.
  - \GET /api/v1/forecast/consensus\: 5-source multi-model consensus.
  - \GET /api/v1/current-aggregate\: Harmonized 50-station network aggregate.
  - \POST /api/v1/health/chat\: AI health advisory engine.
