"""
06_build_master_table.py
Consolidates all interim feature sets into one master table (one row per village).

Schema:
  Identifiers:
    - area_id (shrid2)
    - village_code (Census 2011 6-digit code)
    - village_name
    - district_code
    - district_name
    - subdistrict_name
    - lon, lat (centroid coordinates)
    - area_sqkm
  Demographics (Census):
    - population
    - households
    - pop_density_sqkm
    - avg_household_size
    - sc_share
    - st_share
    - vulnerable_pop_share
  Medical & Health (HMIS & Census):
    - dist_nearest_hc_km
    - dist_nearest_phc_km
    - dist_nearest_hospital_km
    - n_hc_10km
    - n_phc_chc_10km
    - has_phc_or_chc
  Shelters (NCRMP-II & Plans):
    - dist_nearest_shelter_km
    - n_shelters_10km
    - shelter_capacity_nearby
    - shelter_capacity_per_capita
    - shelter_road_access
  Monitoring & Early Warning (KSNDMC):
    - dist_nearest_gauge_km
    - n_gauges_20km
    - nearest_gauge_name
  Roads & Infrastructure (Census):
    - road_connectivity_score (0-3 scale: pucca + district road + bus)
    - drinking_water_score (0-2 scale: treated tap + covered well)
    - pucca_road
    - bus_service_available
  Physical Geography & Hazard Exposure:
    - elevation_mean (m)
    - dist_coast_km
    - cvi_physical
    - cvi_social
    - cvi_integrated
    - vulnerability_tier (Very Low, Low, Medium, High, Very High)
  Validation Target:
    - tauktae_affected (0 or 1)
  Constructed Target:
    - preparedness_score (0-100 composite index)
    - preparedness_tier (Low, Medium, High)

Outputs:
  - data/processed/master_village_preparedness.parquet
  - data/processed/master_village_preparedness.csv
"""

import os
import sys
import time

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import geopandas as gpd
import numpy as np
import pandas as pd

os.makedirs("data/processed", exist_ok=True)

print("=" * 70)
print("STAGE 5: BUILDING MASTER CONSOLIDATED DATASET (ONE ROW PER VILLAGE)")
print("=" * 70)

# ── 1. LOAD ALL INTERIM LAYERS ────────────────────────────────────────────────
t0 = time.time()
print("Loading interim tables...")

villages_utm = gpd.read_parquet("data/interim/villages_coastal_utm.parquet")
hc_feat = pd.read_parquet("data/interim/features_health_centres.parquet")
gauge_feat = pd.read_parquet("data/interim/features_rain_gauges.parquet")
sv_feat = pd.read_parquet("data/interim/features_shelters_vulnerability.parquet")

print(f"  Boundaries + Census:    {len(villages_utm):,} rows")
print(f"  Health features:        {len(hc_feat):,} rows")
print(f"  Rain gauge features:    {len(gauge_feat):,} rows")
print(f"  Shelter/Vuln features:  {len(sv_feat):,} rows")

# ── 2. MERGE INTO MASTER TABLE ────────────────────────────────────────────────
print("\nJoining all feature layers on area_id (shrid2)...")

master = villages_utm.copy()

# Join Health Centre features
hc_cols_to_merge = [c for c in hc_feat.columns if c not in ["village_code"]]
master = master.merge(hc_feat[hc_cols_to_merge], on="shrid2", how="left")

# Join Rain Gauge features
gauge_cols_to_merge = [c for c in gauge_feat.columns if c not in ["village_code"]]
master = master.merge(gauge_feat[gauge_cols_to_merge], on="shrid2", how="left")

# Join Shelter & Vulnerability features
sv_cols_to_merge = [c for c in sv_feat.columns if c not in ["village_code"]]
master = master.merge(sv_feat[sv_cols_to_merge], on="shrid2", how="left")

print(f"Merged master table shape: {master.shape}")

# ── 3. HARMONIZE AND STANDARDIZE COLUMN NAMES ────────────────────────────────
master.rename(columns={
    "shrid2": "area_id",
    "total_population": "population",
    "total_households": "households",
    "area_sqkm": "village_area_sqkm",
    "pucca_road": "has_pucca_road",
    "major_district_road": "has_major_district_road",
}, inplace=True)

# Harmonize missing demographic and infrastructure values for unmatched polygons
fill_defaults = {
    "subdistrict_name": "Rural/Forest Pocket",
    "population": 0,
    "households": 0,
    "avg_household_size": 0.0,
    "sc_share": 0.0,
    "st_share": 0.0,
    "vulnerable_pop_share": 0.0,
    "road_connectivity_score": 0.0,
    "drinking_water_score": 0.0,
    "has_pucca_road": 0,
    "has_major_district_road": 0,
}
for col, default_val in fill_defaults.items():
    if col in master.columns:
        master[col] = master[col].fillna(default_val)

# Derive pop density per sqkm
pop = pd.to_numeric(master["population"], errors="coerce").fillna(0)
area = pd.to_numeric(master["village_area_sqkm"], errors="coerce").replace(0, np.nan)
master["pop_density_sqkm"] = (pop / area).fillna(0).round(1)

# Bus connectivity binary
master["bus_connectivity"] = (
    (master.get("bus_service_public", 0) == 1) |
    (master.get("bus_service_private", 0) == 1)
).astype(int)

# Local health centre presence
master["has_phc_or_chc"] = (
    (master.get("n_phc_census", 0) > 0) |
    (master.get("n_chc_census", 0) > 0) |
    (master.get("n_hosp_allopathic_census", 0) > 0)
).astype(int)

# ── 4. CONSTRUCT THE PREPAREDNESS INDEX (0 - 100) ─────────────────────────────
print("\nConstructing composite Preparedness Index (0-100 scale)...")

def min_max_norm(series, invert=False):
    """Normalize a series to [0, 1]. If invert=True, lower values get higher score."""
    s = pd.to_numeric(series, errors="coerce").fillna(series.median())
    s_min, s_max = s.min(), s.max()
    if s_max == s_min:
        return pd.Series(0.5, index=s.index)
    norm = (s - s_min) / (s_max - s_min)
    return 1.0 - norm if invert else norm

# Dimension 1: Health & Medical Access (Weight: 25%)
# - Proximity to nearest health centre (inverted)
# - Proximity to nearest hospital (inverted)
# - Count of health facilities within 10 km
# - Local health centre presence
s_near_hc = min_max_norm(master["dist_nearest_hc_km"], invert=True)
s_near_hosp = min_max_norm(master["dist_nearest_hospital_km"], invert=True)
s_hc_density = min_max_norm(master["n_hc_10km"])
s_local_hc = master["has_phc_or_chc"].astype(float)

score_medical = (0.35 * s_near_hc + 0.25 * s_near_hosp + 0.25 * s_hc_density + 0.15 * s_local_hc) * 100

# Dimension 2: Evacuation & Shelter Capacity (Weight: 25%)
# - Proximity to nearest shelter (inverted)
# - Number of shelters within 10 km
# - Shelter capacity nearby
# - Shelter capacity per capita
s_near_shelter = min_max_norm(master["dist_nearest_shelter_km"], invert=True)
s_shelter_num = min_max_norm(master["n_shelters_10km"])
s_shelter_cap = min_max_norm(master["shelter_capacity_nearby"])
s_shelter_per_cap = min_max_norm(np.log1p(master["shelter_capacity_per_capita"]))

score_shelters = (0.35 * s_near_shelter + 0.25 * s_shelter_num + 0.25 * s_shelter_cap + 0.15 * s_shelter_per_cap) * 100

# Dimension 3: Road Connectivity & Basic Utilities (Weight: 20%)
# - Road connectivity score (pucca + major district road + bus)
# - Drinking water score (treated tap water + covered wells)
s_road = min_max_norm(master["road_connectivity_score"])
s_water = min_max_norm(master["drinking_water_score"])

score_infrastructure = (0.60 * s_road + 0.40 * s_water) * 100

# Dimension 4: Early Warning & Weather Monitoring (Weight: 15%)
# - Proximity to nearest telemetric rain gauge (inverted)
# - Gauge density within 20 km
s_near_gauge = min_max_norm(master["dist_nearest_gauge_km"], invert=True)
s_gauge_density = min_max_norm(master["n_gauges_20km"])

score_early_warning = (0.60 * s_near_gauge + 0.40 * s_gauge_density) * 100

# Dimension 5: Socio-Economic Resilience (Weight: 15%)
# - Lower vulnerable population share (SC/ST share)
# - Average household size (moderate size is better than extreme crowding)
s_vuln_share = min_max_norm(master["vulnerable_pop_share"], invert=True)
s_hh_size = min_max_norm(np.abs(master["avg_household_size"] - 4.5), invert=True)

score_socioeconomic = (0.70 * s_vuln_share + 0.30 * s_hh_size) * 100

# Overall Composite Preparedness Score (0 - 100)
master["score_medical"] = score_medical.round(2)
master["score_shelters"] = score_shelters.round(2)
master["score_infrastructure"] = score_infrastructure.round(2)
master["score_early_warning"] = score_early_warning.round(2)
master["score_socioeconomic"] = score_socioeconomic.round(2)

master["preparedness_score"] = (
    0.25 * score_medical +
    0.25 * score_shelters +
    0.20 * score_infrastructure +
    0.15 * score_early_warning +
    0.15 * score_socioeconomic
).round(2)

# Preparedness Tier (Low, Medium, High)
# Based on tertile / standard disaster thresholds
master["preparedness_tier"] = pd.cut(
    master["preparedness_score"],
    bins=[-np.inf, 40.0, 60.0, np.inf],
    labels=["Low", "Medium", "High"]
)

print(f"Preparedness Score Summary:\n{master['preparedness_score'].describe().round(2).to_string()}")
print("\nPreparedness Tier Distribution:")
print(master["preparedness_tier"].value_counts().to_string())

# ── 5. SANITY CHECKS & VALIDATION ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("SANITY CHECKS & VALIDATION ON MASTER DATASET")
print("=" * 70)

# Check missing values
null_counts = master.isnull().sum()
cols_with_nulls = null_counts[null_counts > 0]
print(f"Columns with null values: {len(cols_with_nulls)}")
if len(cols_with_nulls) > 0:
    print(cols_with_nulls.to_string())

# Check coordinates
print(f"Coordinate Bounds:")
print(f"  Longitude range: {master['lon'].min():.4f} to {master['lon'].max():.4f}")
print(f"  Latitude range:  {master['lat'].min():.4f} to {master['lat'].max():.4f}")

# Check key columns correlation with Tauktae validation target
tauktae_corr = master[[
    "preparedness_score", "dist_coast_km", "elevation_mean",
    "score_shelters", "score_medical", "cvi_integrated", "tauktae_affected"
]].corr()["tauktae_affected"].round(3)

print("\nCorrelation with Tauktae Affected validation indicator:")
print(tauktae_corr.to_string())

print("\nMean Preparedness Score by Tauktae Affected Status:")
print(master.groupby("tauktae_affected")["preparedness_score"].mean().round(2).to_string())

print("\nMean Distance to Coast by Tauktae Affected Status:")
print(master.groupby("tauktae_affected")["dist_coast_km"].mean().round(2).to_string())

# ── 6. FINAL SELECTION & EXPORT ───────────────────────────────────────────────
ordered_cols = [
    "area_id",
    "village_code",
    "village_name",
    "district_code",
    "district_name",
    "subdistrict_name",
    "lon",
    "lat",
    "village_area_sqkm",
    # Demographics
    "population",
    "households",
    "pop_density_sqkm",
    "avg_household_size",
    "sc_share",
    "st_share",
    "vulnerable_pop_share",
    # Geography & Hazard
    "elevation_mean",
    "dist_coast_km",
    "cvi_physical",
    "cvi_social",
    "cvi_integrated",
    "vulnerability_tier",
    # Shelters
    "dist_nearest_shelter_km",
    "n_shelters_10km",
    "shelter_capacity_nearby",
    "shelter_capacity_per_capita",
    "shelter_road_access",
    # Health & Medical
    "dist_nearest_hc_km",
    "dist_nearest_phc_km",
    "dist_nearest_hospital_km",
    "n_hc_10km",
    "n_phc_chc_10km",
    "has_phc_or_chc",
    # Weather Early Warning
    "dist_nearest_gauge_km",
    "n_gauges_20km",
    "nearest_gauge_name",
    # Infrastructure & Roads
    "road_connectivity_score",
    "drinking_water_score",
    "has_pucca_road",
    "has_major_district_road",
    "bus_connectivity",
    # Dimension Scores
    "score_medical",
    "score_shelters",
    "score_infrastructure",
    "score_early_warning",
    "score_socioeconomic",
    # Targets
    "preparedness_score",
    "preparedness_tier",
    "tauktae_affected"
]

export_df = master[[c for c in ordered_cols if c in master.columns]].copy()

# Save CSV & Parquet
export_df.to_parquet("data/processed/master_village_preparedness.parquet", index=False)
export_df.to_csv("data/processed/master_village_preparedness.csv", index=False)

print("\n" + "=" * 70)
print("SUCCESSFULLY EXPORTED CONSOLIDATED MASTER DATASET:")
print(f"  Parquet: data/processed/master_village_preparedness.parquet ({len(export_df):,} rows x {len(export_df.columns)} columns)")
print(f"  CSV:     data/processed/master_village_preparedness.csv")
print("=" * 70)
