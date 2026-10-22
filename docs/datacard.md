# Data Card: Coastal Karnataka Village Cyclone Preparedness Dataset

## 1. Overview & Dataset Summary
This dataset unifies multi-sectoral disaster risk reduction, socioeconomic, and infrastructural indicators into a single harmonized tabular dataset at the **Census village level** for Karnataka's three coastal districts:
- **Uttara Kannada (District Code 563)**: 1,257 polygons
- **Udupi (District Code 569)**: 253 polygons
- **Dakshina Kannada (District Code 575)**: 369 polygons
- **Total Areas / Rows**: **1,879 village polygons** (matching 1,853 Census 2011 villages with a 97.36% direct primary key overlap).

**Target Formulations**:
- **Continuous Target**: `preparedness_score` (Composite disaster preparedness index on a 0–100 scale).
- **Categorical Target**: `preparedness_tier` (`Low`: < 40, `Medium`: 40–60, `High`: > 60).
- **Empirical Validation Target**: `tauktae_affected` (Binary ground truth: 1 if village experienced severe storm surge, tidal inundation, and damage during Cyclone Tauktae in May 2021).

---

## 2. Source Catalogue & Lineage

| Source Name | Raw File Reference | Feature Contribution | Spatial Key / Geometry |
| :--- | :--- | :--- | :--- |
| **Census 2011 Village Directory (DCHB)** | `DH_2011_DCHB_Village_Release_2900.xlsx` | Population, households, SC/ST share, tap water, pucca roads, bus service, distances to HQ | `village_code` (6-digit Census code) |
| **SHRUG 2.1 Village Polygons** | `shrug-shrid-poly-shp/shrid2_open.shp` | High-resolution village boundary polygons, metric centroids, area ($km^2$) | `shrid2` (format `11-29-DDD-SSSSS-VVVVVV`), `pc11_id` |
| **National Health Centre Directory (HMIS)** | `geocode_health_centre.csv` | Distances to nearest health centre, PHC, and hospital; facility counts within 10 km | Point coordinates (`Latitude`, `Longitude`) |
| **KSNDMC Telemetric Rain Gauges** | `70578d25-7ede-426c-8e8e-5c679274a55a.kml` | Nearest rain gauge distance, station name, density of gauges within 20 km | Point coordinates (`Latitude`, `Longitude`) |
| **Multi-Purpose Cyclone Shelters (NCRMP-II)** | Compiled in `shelters_manual.csv` | Distance to nearest shelter, count within 10 km, total capacity, capacity per capita | Point coordinates (`lat`, `lon`) |
| **Coastal Vulnerability Index (Naik & Kunte, 2023)** | `IntegratedCoastalVulnerabilityAssessment.pdf` | Physical-geological (PGCVI), socioeconomic (SCVI), and integrated CVI score & tier | Sub-district / Taluka cross-walk |
| **KSDMA Cyclone Tauktae Situational Reports** | Situational damage data (May 2021) | Cyclone inundation, erosion, and beachfront damage impact indicator | Village name and coastal buffer (<2.5 km) |

---

## 3. Spatial Methodology & Geodetic Projections
1. **Coordinate Reference System (CRS)**:
   - Metric joins, proximity calculations, and radius buffers are strictly computed in **EPSG:32643** (`WGS 84 / UTM zone 43N`), which uses meters and is the standard conformal projection for Western India (72°E to 78°E).
   - Display and GPS coordinates are preserved in standard **EPSG:4326** (`WGS 84` decimal degrees).
2. **Nearest-Neighbor Spatial Joins (`gpd.sjoin_nearest`)**:
   - Used for facility distances (`dist_nearest_hc_km`, `dist_nearest_phc_km`, `dist_nearest_hospital_km`, `dist_nearest_gauge_km`, `dist_nearest_shelter_km`).
   - Tie-breaking: sorted by Euclidean distance in UTM meters and deduplicated by `shrid2`.
3. **Radial Density Buffers (`gpd.sjoin(..., predicate="contains")`)**:
   - 10 km buffer from village centroid for local healthcare accessibility and shelter coverage.
   - 20 km buffer from village centroid for meteorological monitoring coverage.
   - Correct handling of zero-count polygons by filtering on valid right-index matches prior to aggregation.
4. **Coastline Distance Calculation**:
   - Standardized western boundary vector along the Arabian Sea coastline from Talapady (12.75°N) to Majali (14.92°N).
   - Computed perpendicular distance from village polygon/centroid to coastline in meters and scaled to kilometers.

---

## 4. Preparedness Score Formulation

The composite `preparedness_score` is a weighted linear combination of five normalized dimensional sub-scores (each scaled 0–100):

$$\text{Preparedness Score} = 0.25 \cdot S_{\text{medical}} + 0.25 \cdot S_{\text{shelters}} + 0.20 \cdot S_{\text{infrastructure}} + 0.15 \cdot S_{\text{early\_warning}} + 0.15 \cdot S_{\text{socioeconomic}}$$

1. **Medical Access ($S_{\text{medical}}$, 25%)**:
   - Nearest HC distance (35%, inverted)
   - Nearest hospital distance (25%, inverted)
   - Health centres within 10 km (25%)
   - Local village PHC/CHC presence (15%)
2. **Evacuation & Shelters ($S_{\text{shelters}}$, 25%)**:
   - Nearest cyclone shelter distance (35%, inverted)
   - Shelters within 10 km (25%)
   - Nearby shelter capacity (25%)
   - Shelter capacity per capita (15%)
3. **Infrastructure & Basic Utilities ($S_{\text{infrastructure}}$, 20%)**:
   - Road connectivity index (pucca road + major district road + bus access, 60%)
   - Safe drinking water index (treated tap water + covered wells, 40%)
4. **Early Warning & Meteorological Coverage ($S_{\text{early\_warning}}$, 15%)**:
   - Nearest KSNDMC telemetric rain gauge distance (60%, inverted)
   - Rain gauge density within 20 km (40%)
5. **Socioeconomic Resilience ($S_{\text{socioeconomic}}$, 15%)**:
   - Low vulnerable population share (SC/ST share, 70%, inverted)
   - Household size stability (30%)

---

## 5. Summary Statistics & Sanity Checks

- **Row Count**: 1,879 areas
- **Missing Values**: 0 nulls across all 49 exported features.
- **Preparedness Score**:
  - Minimum: 20.14
  - Median: 53.11
  - Mean: 54.24
  - Maximum: 81.54
  - Standard Deviation: 10.72
- **Preparedness Tiers**:
  - `High` (> 60): 596 villages (31.7%)
  - `Medium` (40–60): 1,128 villages (60.0%)
  - `Low` (< 40): 155 villages (8.3%)
- **Validation Against Cyclone Tauktae**:
  - Distance to coast for affected villages: **0.66 km mean** vs. **38.79 km mean** for unaffected villages.
  - Correlation between Tauktae impact and shelter proximity/capacity: **+0.547** (reflecting deliberate shelter placement in historically storm-vulnerable coastal strips).
