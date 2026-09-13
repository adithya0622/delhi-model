# In-Depth Guide: Dynamic Source Apportionment & 72-Hour Predictive Time-Series
## Mathematical Formulations, Chemical-Proxy Physics, Code Implementation, & UI Architecture

---

# 1. Executive Overview & Problem Statement

### The Real-World Challenge in Delhi NCR
In air quality analytics, knowing the total particulate matter ($PM_{2.5}$) is only half the battle. Policymakers, municipal commissioners, and environmental health officers need to know: **"Who is causing the pollution right now?"**

Traditionally, source apportionment relies on:
1. **Offline Filter-Based Chemical Speciation (IIT Kanpur / TERI Studies)**: Takes weeks in a laboratory to analyze Teflon/quartz filters for elemental carbon, organic carbon, and trace metals. These reports produce static annual averages (e.g., *"Vehicles contribute 25% on average"*), but cannot detect a sudden truck strike, lockdown, or holiday traffic drop.
2. **Missing Real-Time Traffic Emission Feeds**: Delhi does not have city-wide connected vehicle telemetry measuring tailpipe emissions in real time.

### The Solution: Deterministic Chemical-Proxy Tracer & Fleet Dynamics
The **NCR-72 Dynamic Source Apportionment Engine** solves this by using live **Nitrogen Dioxide ($NO_2$)** as a real-time chemical tracer for internal combustion engines, coupled with municipal traffic regulations (such as Delhi's daytime heavy commercial truck entry bans) and a **72-hour stacked predictive time-series model**.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                CHEMICAL-PROXY FLOWCHART                                │
└────────────────────────────────────────────────────────────────────────────────────────┘

  Live Station NO2 ───────► Proxy Ratio Engine ───────► Dynamic Transport Share
  (14.7 - 201.4 µg/m³)      R_traffic = [NO2] / 60.0     S_transport = 25% × R_traffic
                                                                  │
                                                                  ▼
  Live Ambient PM2.5 ◄──── Conservation of Mass ◄───── Deficit/Surplus Re-allocation
  (e.g., 221.0 µg/m³)      Σ (Transport + Dust +        Dust, Biomass & Industry absorb
                           Biomass + Industry) = 100%   the remaining percentage evenly
                                  │
                                  ▼
                    Diurnal Fleet Decomposition (Active Hour)
                    • Heavy Commercial Trucks (Surge 22:00 - 06:00)
                    • 2 & 3-Wheelers (Peak during Commute 08-11 & 17-20)
                    • Cars, Taxis & Light Vehicles
                                  │
                                  ▼
              72-Hour Predictive Stacked Area Time-Series
              (6-Layer Fleet View ⇄ 4-Layer Macro Sectors View)
```

---

# 2. Chemical-Proxy Physics & Atmospheric Formulations

---

### A. Why $NO_2$ is the Ideal Tracer for Vehicle Combustion

In urban Delhi, ambient Nitrogen Dioxide ($NO_2$) originates predominantly from high-temperature fossil fuel combustion in internal combustion engines:

$$N_2 + O_2 \xrightarrow{\text{High Temperature } (>1300^\circ\text{C})} 2\,NO$$

$$2\,NO + O_2 \longrightarrow 2\,NO_2 \quad \text{and} \quad NO + O_3 \longrightarrow NO_2 + O_2$$

Because gasoline and diesel vehicles emit high concentrations of nitrogen oxides ($NO_x$) directly at ground level, sudden fluctuations in city-wide $NO_2$ correlate directly with vehicular combustion anomalies.

---

### B. The Traffic Combustion Proxy Ratio ($R_{\text{traffic}}$)

We establish an empirical baseline representing standard daytime traffic in Delhi NCR:

$$[NO_2]_{\text{baseline}} = 60.0\text{ }\mu\text{g/m}^3$$

The real-time **Inferred Traffic Ratio** $R_{\text{traffic}}$ is calculated as:

$$R_{\text{traffic}} = \text{clamp}\left( \frac{[NO_2]_{\text{live}}}{[NO_2]_{\text{baseline}}}, 0.05, 2.0 \right)$$

* When $[NO_2]_{\text{live}} = 60.0\text{ }\mu\text{g/m}^3 \implies R_{\text{traffic}} = 1.0\text{ (100\% Normal Combustion)}$.
* When $[NO_2]_{\text{live}} = 14.7\text{ }\mu\text{g/m}^3 \implies R_{\text{traffic}} = 0.245\text{ (24.5\% / Significant Traffic Suppression)}$.
* When $[NO_2]_{\text{live}} \ge 60.0\text{ }\mu\text{g/m}^3 \implies R_{\text{traffic}} = 1.0\text{ (100\% Full Combustion Cap)}$.

---

### C. Dynamic Vehicular Share & Mass Conservation ($\sum = 100.0\%$)

1. **Standard Delhi Climatological Baseline**:
   - $\text{Vehicular Transport } (S_{\text{transport, base}}) = 25.0\%$
   - $\text{Road \& Soil Dust } (S_{\text{dust, base}}) = 30.0\%$
   - $\text{Biomass / Stubble Burning } (S_{\text{biomass, base}}) = 25.0\%$
   - $\text{Industry \& Power Plants } (S_{\text{industry, base}}) = 20.0\%$
   - Total = $25\% + 30\% + 25\% + 20\% = 100.0\%$

2. **Dynamic Vehicular Share Calculation**:

   $$S_{\text{transport}} = S_{\text{transport, base}} \times R_{\text{traffic}} = 25.0\% \times R_{\text{traffic}}$$

3. **Mass Conservation Re-balancing**:
   If traffic drops (e.g., during a strike or lockdown), the total mass percentage must still sum to exactly $100.0\%$. The percentage deficit $\Delta S$ is distributed evenly among the other three non-vehicular sectors:

   $$\Delta S = S_{\text{transport, base}} - S_{\text{transport}} = 25.0\% - S_{\text{transport}}$$

   $$S_{\text{dust}} = 30.0\% + \frac{\Delta S}{3}$$

   $$S_{\text{biomass}} = 25.0\% + \frac{\Delta S}{3}$$

   $$S_{\text{industry}} = 20.0\% + \frac{\Delta S}{3}$$

   $$\sum \left( S_{\text{transport}} + S_{\text{dust}} + S_{\text{biomass}} + S_{\text{industry}} \right) \equiv 100.0\%$$

4. **Absolute Microgram Contributions ($\mu\text{g/m}^3$)**:
   Each sector's mass contribution is computed by multiplying its dynamic percentage by the live ambient $PM_{2.5}$:

   $$M_{\text{sector}} = [PM_{2.5}]_{\text{ambient}} \times \frac{S_{\text{sector}}}{100}$$

   $$\sum M_{\text{sector}} = [PM_{2.5}]_{\text{ambient}}$$

---

### D. Diurnal Vehicle Fleet Sub-Decomposition

Total vehicular emissions ($M_{\text{transport}}$) are further broken down into three vehicle classes according to Delhi's municipal traffic regulations and commute hours:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        DIURNAL VEHICLE FLEET TIME PROFILES                             │
├───────────────────────────────┬───────────────────────────────┬────────────────────────┤
│ Time Window (IST)             │ Active Fleet Regime           │ Fleet Share Breakdown  │
├───────────────────────────────┼───────────────────────────────┼────────────────────────┤
│ Night Window (22:00 - 06:00)  │ Heavy Truck Entry Surge       │ • Trucks: 61%          │
│                               │ (Commercial diesel trucks     │ • 2 & 3-Wheelers: 25%  │
│                               │  allowed into Delhi)          │ • Cars & Taxis: 14%    │
├───────────────────────────────┼───────────────────────────────┼────────────────────────┤
│ Rush Hours (08-11 & 17-20)    │ Commuter Peak                 │ • Trucks: 10% (Banned) │
│                               │ (High 2-wheelers & cars)      │ • 2 & 3-Wheelers: 60%  │
│                               │                               │ • Cars & Taxis: 30%    │
├───────────────────────────────┼───────────────────────────────┼────────────────────────┤
│ Daytime Normal (Other hours)  │ Standard Daytime Distribution │ • Trucks: 30%          │
│                               │                               │ • 2 & 3-Wheelers: 50%  │
│                               │                               │ • Cars & Taxis: 20%    │
└───────────────────────────────┴───────────────────────────────┴────────────────────────┘
```

---

# 3. 72-Hour Predictive Time-Series Engine

To project source contributions across the next 3 days, the simulation engine couples the hourly $PM_{2.5}$ meteorological prognostic curve with the diurnal fleet profiles for all 72 hours:

For each hour $h \in [0, 71]$:
1. **Clock Hour & Day**: $\text{hour\_of\_day} = (\text{current\_hour} + h) \pmod{24}$.
2. **Hourly Ambient $PM_{2.5}(h)$**: Extracted from the coupled meteorological box model.
3. **Macro-Sector Split**:
   - $M_{\text{dust}}(h) = PM_{2.5}(h) \times 0.30$
   - $M_{\text{biomass}}(h) = PM_{2.5}(h) \times 0.25$
   - $M_{\text{industry}}(h) = PM_{2.5}(h) \times 0.20$
   - $M_{\text{transport}}(h) = PM_{2.5}(h) \times 0.25$
4. **Fleet Decomposition**:
   - $M_{\text{trucks}}(h) = M_{\text{transport}}(h) \times f_{\text{trucks}}(\text{hour\_of\_day})$
   - $M_{\text{2wheelers}}(h) = M_{\text{transport}}(h) \times f_{\text{2wheelers}}(\text{hour\_of\_day})$
   - $M_{\text{cars}}(h) = M_{\text{transport}}(h) \times f_{\text{cars}}(\text{hour\_of\_day})$
5. **Observational Nudge Relaxation**:
   The starting point at $h=0$ exactly reflects live observations; future hours smoothly relax toward the prognostic trajectory via exponential decay ($\tau = 24\text{ hours}$).

---

# 4. Backend Code Implementation (`emission_service.py`)

### A. Pydantic Schemas (`backend/app/schemas/emission.py`)

```python
from pydantic import BaseModel, Field

class VehicleFleetBreakdown(BaseModel):
    heavy_trucks_pct: float = Field(..., description="Heavy commercial trucks percentage")
    two_three_wheelers_pct: float = Field(..., description="2 and 3-wheelers percentage")
    cars_pct: float = Field(..., description="Passenger cars and light commercial percentage")
    heavy_trucks_mcg: float = Field(..., description="Absolute mass in µg/m³")
    two_three_wheelers_mcg: float = Field(..., description="Absolute mass in µg/m³")
    cars_mcg: float = Field(..., description="Absolute mass in µg/m³")

class SourceApportionmentResponse(BaseModel):
    total_pm25: float
    transport_pct: float
    dust_pct: float
    biomass_pct: float
    industry_pct: float
    transport_mcg: float
    dust_mcg: float
    biomass_mcg: float
    industry_mcg: float
    vehicle_breakdown: VehicleFleetBreakdown
    proxy_status: str

class SourceApportionmentHour(BaseModel):
    hour_index: int
    time_label: str
    iso_timestamp: str
    total_pm25: float
    dust_mcg: float
    biomass_mcg: float
    industry_mcg: float
    trucks_mcg: float
    two_wheelers_mcg: float
    cars_mcg: float
    transport_mcg: float

class SourceApportionmentTimeSeriesResponse(BaseModel):
    generated_at: str
    forecast: list[SourceApportionmentHour]
```

---

### B. Service Implementation (`backend/app/services/emission_service.py`)

```python
class EmissionService:
    BASE_TRANSPORT_PCT = 25.0
    BASE_DUST_PCT = 30.0
    BASE_BIOMASS_PCT = 25.0
    BASE_INDUSTRY_PCT = 20.0
    NO2_BASELINE = 60.0

    @classmethod
    def calculate_source_apportionment(
        cls, current_pm25: float, current_no2: float, active_hour: int = 12
    ) -> SourceApportionmentResponse:
        # 1. Compute NO2 Proxy Ratio
        ratio = min(max(current_no2 / cls.NO2_BASELINE, 0.05), 2.0)

        # 2. Dynamic Transport Share
        if ratio >= 1.0:
            transport_pct = cls.BASE_TRANSPORT_PCT
            dust_pct = cls.BASE_DUST_PCT
            biomass_pct = cls.BASE_BIOMASS_PCT
            industry_pct = cls.BASE_INDUSTRY_PCT
        else:
            transport_pct = round(cls.BASE_TRANSPORT_PCT * ratio, 1)
            deficit = cls.BASE_TRANSPORT_PCT - transport_pct
            share_add = deficit / 3.0
            dust_pct = round(cls.BASE_DUST_PCT + share_add, 1)
            biomass_pct = round(cls.BASE_BIOMASS_PCT + share_add, 1)
            industry_pct = round(100.0 - (transport_pct + dust_pct + biomass_pct), 1)

        # 3. Absolute Mass Conversion
        trans_mcg = round(current_pm25 * (transport_pct / 100.0), 2)
        dust_mcg = round(current_pm25 * (dust_pct / 100.0), 2)
        bio_mcg = round(current_pm25 * (biomass_pct / 100.0), 2)
        ind_mcg = round(current_pm25 * (industry_pct / 100.0), 2)

        # 4. Diurnal Fleet Breakdown
        if active_hour >= 22 or active_hour < 6:
            trk_share, two_share, car_share = 61.0, 25.0, 14.0
        elif (8 <= active_hour <= 11) or (17 <= active_hour <= 20):
            trk_share, two_share, car_share = 10.0, 60.0, 30.0
        else:
            trk_share, two_share, car_share = 30.0, 50.0, 20.0

        return SourceApportionmentResponse(
            total_pm25=current_pm25,
            transport_pct=transport_pct,
            dust_pct=dust_pct,
            biomass_pct=biomass_pct,
            industry_pct=industry_pct,
            transport_mcg=trans_mcg,
            dust_mcg=dust_mcg,
            biomass_mcg=bio_mcg,
            industry_mcg=ind_mcg,
            vehicle_breakdown=VehicleFleetBreakdown(
                heavy_trucks_pct=trk_share,
                two_three_wheelers_pct=two_share,
                cars_pct=car_share,
                heavy_trucks_mcg=round(trans_mcg * (trk_share / 100.0), 2),
                two_three_wheelers_mcg=round(trans_mcg * (two_share / 100.0), 2),
                cars_mcg=round(trans_mcg * (car_share / 100.0), 2),
            ),
            proxy_status=cls._get_proxy_status(ratio),
        )
```

---

# 5. Frontend React UI Architecture (`SourceApportionment.tsx`)

### Key Frontend Components:
1. **Interactive Toggle**:
   - `Macro Sectors (4-Layer)`: Road Dust (30%), Biomass/Stubble (25%), Industry (20%), Vehicular Transport (25%).
   - `Fleet Decomposition (6-Layer)`: Road Dust, Biomass, Industry, Heavy Trucks (Night Surge), 2 & 3-Wheelers (Rush Peak), Cars & Taxis.
2. **Recharts Stacked Area Chart**:
   - Smooth monotone curves (`type="monotone"`).
   - Dynamic SVG gradient fills for distinct dark-mode glassmorphism visual hierarchy.
   - Dual-mode custom tooltip showing micrograms ($\mu\text{g/m}^3$) and percentage shares.
3. **Animated Mass Conservation Bar**:
   - Multi-segment progress bar with live flex proportions representing the 4 macro sectors.
   - Visual footer displaying $\Sigma = 100\%$ mass conservation guarantee.

---

# 6. Step-by-Step Numerical Example (Matching Your Screenshot)

Let's trace the exact calculations shown in your uploaded screenshot:

### Given Real-Time Inputs:
* **Live Ambient $\mathbf{PM_{2.5}}$**: $221.0\text{ }\mu\text{g/m}^3$
* **Live $\mathbf{NO_2}$ Chemical Tracer**: $201.4\text{ }\mu\text{g/m}^3$
* **Active Hour**: $21:00\text{ IST}$ (Daytime Fleet Regime)

---

### Step 1: Compute $NO_2$ Combustion Proxy Ratio
$$R_{\text{traffic}} = \frac{201.4}{60.0} = 3.35 \implies \text{clamped to } \mathbf{1.0\text{ (100\% Normal Combustion)}}$$

---

### Step 2: Calculate Macro-Sector Shares & Concentrations
Because $R_{\text{traffic}} = 1.0$, the full standard baseline shares apply:

* **Vehicular Transport ($25.0\%$)**:
  $$M_{\text{transport}} = 221.0 \times 0.25 = \mathbf{55.3\text{ }\mu\text{g/m}^3}$$
* **Road & Soil Dust ($30.0\%$)**:
  $$M_{\text{dust}} = 221.0 \times 0.30 = \mathbf{66.3\text{ }\mu\text{g/m}^3}$$
* **Biomass / Stubble ($25.0\%$)**:
  $$M_{\text{biomass}} = 221.0 \times 0.25 = \mathbf{55.3\text{ }\mu\text{g/m}^3}$$
* **Industry & Power ($20.0\%$)**:
  $$M_{\text{industry}} = 221.0 \times 0.20 = \mathbf{44.2\text{ }\mu\text{g/m}^3}$$

**Sum Check (Conservation of Mass)**:
$$55.3 + 66.3 + 55.3 + 44.2 = \mathbf{221.0\text{ }\mu\text{g/m}^3} \quad (100.0\%)$$

---

### Step 3: Diurnal Fleet Breakdown ($21:00\text{ IST}$)
At $21:00\text{ IST}$, the active regime is **Normal Daytime Fleet** ($30\%$ Trucks, $50\%$ 2/3-Wheelers, $20\%$ Cars):

* **Heavy Commercial Trucks ($30\%$)**:
  $$M_{\text{trucks}} = 55.3 \times 0.30 = \mathbf{16.6\text{ }\mu\text{g/m}^3}$$
* **2 & 3-Wheelers ($50\%$)**:
  $$M_{\text{2wheelers}} = 55.3 \times 0.50 = \mathbf{27.6\text{ }\mu\text{g/m}^3}$$
* **Cars & Light Vehicles ($20\%$)**:
  $$M_{\text{cars}} = 55.3 \times 0.20 = \mathbf{11.1\text{ }\mu\text{g/m}^3}$$

**Fleet Sum Check**:
$$16.6 + 27.6 + 11.1 = \mathbf{55.3\text{ }\mu\text{g/m}^3} \quad (100.0\% \text{ of Transport})$$

---

# 7. Summary for Presentation & Evaluation

1. **Innovation**: Replaces static research papers with a **dynamic chemical proxy algorithm** that updates every 60 seconds.
2. **Physics Grounding**: Implements strict conservation of mass ($\Sigma = 100\%$) and realistic diurnal fleet traffic profiles.
3. **Actionability**: Allows municipal authorities to immediately see whether a spike in pollution is caused by traffic congestion, stubble burning, or meteorological inversion trapping.
