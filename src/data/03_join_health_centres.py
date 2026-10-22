"""
03_join_health_centres.py
Spatial join: geocoded health centres -> village polygons (EPSG:32643 UTM).

For each village, calculates:
  - dist_nearest_hc_km      : Distance to nearest health facility (km)
  - dist_nearest_phc_km     : Distance to nearest Primary Health Centre / CHC (km)
  - dist_nearest_hospital_km: Distance to nearest District / Sub-district Hospital (km)
  - n_hc_10km               : Count of health centres within 10 km
  - n_phc_chc_10km          : Count of PHC/CHCs within 10 km

Source: data/raw/geocode_health_centre.csv
"""

import os
import sys
import time

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import geopandas as gpd
import numpy as np
import pandas as pd

os.makedirs("data/interim", exist_ok=True)

COASTAL_DISTRICTS = ["Dakshina Kannada", "Udupi", "Uttara Kannada"]
UTM_CRS = "EPSG:32643"

print("=" * 70)
print("STAGE 2: SPATIAL JOIN - HEALTH CENTRES TO VILLAGE BOUNDARIES")
print("=" * 70)

# ── 1. LOAD HEALTH CENTRES ────────────────────────────────────────────────────
t0 = time.time()
hc_raw = pd.read_csv("data/raw/geocode_health_centre.csv")
print(f"Loaded {len(hc_raw):,} raw health facility records in {time.time()-t0:.2f}s")

# Filter to active physical facilities in the 3 coastal districts
hc = hc_raw[
    (hc_raw["State Name"] == "Karnataka") &
    (hc_raw["District Name"].isin(COASTAL_DISTRICTS)) &
    (hc_raw["ActiveFlag_C"] == "Y") &
    (hc_raw["NOTIONAL_PHYSICAL"] == "Physical")
].copy()
print(f"Filtered coastal Karnataka facilities: {len(hc):,}")
print(hc["District Name"].value_counts().to_string())

# Sanity check coordinates
hc = hc.dropna(subset=["Latitude", "Longitude"])
hc = hc[
    (hc["Latitude"].between(11.5, 16.5)) &
    (hc["Longitude"].between(73.5, 76.5))
].copy()
print(f"Valid geocoded facilities within coastal extent: {len(hc):,}")

# Facility classifications
hc_gdf = gpd.GeoDataFrame(
    hc,
    geometry=gpd.points_from_xy(hc["Longitude"], hc["Latitude"]),
    crs="EPSG:4326"
).to_crs(UTM_CRS)

# Categorize facility types
phc_chc_types = {"phc", "chc", "sub_centre", "sc", "primary health centre", "community health centre"}
hospital_types = {"dis_h", "sub_dis_h", "dh", "sdh", "hospital", "general hospital"}

hc_gdf["is_phc_chc"] = hc_gdf["Facility Type"].str.lower().str.strip().isin(phc_chc_types)
hc_gdf["is_hospital"] = hc_gdf["Facility Type"].str.lower().str.strip().isin(hospital_types)

print(f"Facility Breakdown:")
print(f"  PHC / CHC / Sub-Centres: {hc_gdf['is_phc_chc'].sum():,}")
print(f"  District / Sub-District Hospitals: {hc_gdf['is_hospital'].sum():,}")
print(f"  Other facilities: {(~hc_gdf['is_phc_chc'] & ~hc_gdf['is_hospital']).sum():,}")

# ── 2. LOAD VILLAGE POLYGONS ──────────────────────────────────────────────────
villages = gpd.read_parquet("data/interim/villages_coastal_utm.parquet")
print(f"\nLoaded {len(villages):,} coastal village polygons in {villages.crs}")

# ── 3. NEAREST FACILITY DISTANCES ─────────────────────────────────────────────
print("\nComputing nearest facility distances (sjoin_nearest)...")

# 3a. Nearest Any Health Facility
t0 = time.time()
near_any = gpd.sjoin_nearest(
    villages[["shrid2", "geometry"]],
    hc_gdf[["geometry"]],
    how="left",
    distance_col="dist_nearest_hc_m"
).sort_values("dist_nearest_hc_m").drop_duplicates("shrid2")

villages["dist_nearest_hc_km"] = (near_any["dist_nearest_hc_m"] / 1000.0).round(2)
print(f"  Nearest Any Health Facility: mean {villages['dist_nearest_hc_km'].mean():.2f} km, max {villages['dist_nearest_hc_km'].max():.2f} km ({time.time()-t0:.2f}s)")

# 3b. Nearest PHC / CHC
t0 = time.time()
hc_phc = hc_gdf[hc_gdf["is_phc_chc"]].copy()
near_phc = gpd.sjoin_nearest(
    villages[["shrid2", "geometry"]],
    hc_phc[["geometry"]],
    how="left",
    distance_col="dist_nearest_phc_m"
).sort_values("dist_nearest_phc_m").drop_duplicates("shrid2")

villages["dist_nearest_phc_km"] = (near_phc["dist_nearest_phc_m"] / 1000.0).round(2)
print(f"  Nearest PHC / CHC:           mean {villages['dist_nearest_phc_km'].mean():.2f} km, max {villages['dist_nearest_phc_km'].max():.2f} km ({time.time()-t0:.2f}s)")

# 3c. Nearest Hospital (District / Sub-District Hospital)
t0 = time.time()
hc_hosp = hc_gdf[hc_gdf["is_hospital"]].copy()
if len(hc_hosp) > 0:
    near_hosp = gpd.sjoin_nearest(
        villages[["shrid2", "geometry"]],
        hc_hosp[["geometry"]],
        how="left",
        distance_col="dist_nearest_hosp_m"
    ).sort_values("dist_nearest_hosp_m").drop_duplicates("shrid2")
    villages["dist_nearest_hospital_km"] = (near_hosp["dist_nearest_hosp_m"] / 1000.0).round(2)
else:
    # If no separate hospital tag, fallback to CHC/nearest major centre
    villages["dist_nearest_hospital_km"] = villages["dist_nearest_phc_km"]
print(f"  Nearest Hospital:            mean {villages['dist_nearest_hospital_km'].mean():.2f} km, max {villages['dist_nearest_hospital_km'].max():.2f} km ({time.time()-t0:.2f}s)")

# ── 4. BUFFER COUNTS (FACILITIES WITHIN 10 KM) ────────────────────────────────
print("\nComputing health facility density within 10 km radius...")
t0 = time.time()
village_buf = villages[["shrid2", "geometry"]].copy()
village_buf["geometry"] = village_buf.geometry.centroid.buffer(10_000)

joined = gpd.sjoin(
    village_buf,
    hc_gdf[["geometry", "is_phc_chc"]],
    how="left",
    predicate="contains"
)

# Proper counting avoiding left-join NaN artifact
valid_matches = joined.dropna(subset=["index_right"])
count_all = valid_matches.groupby("shrid2").size().rename("n_hc_10km")
count_phc = valid_matches[valid_matches["is_phc_chc"]].groupby("shrid2").size().rename("n_phc_chc_10km")

villages["n_hc_10km"] = villages["shrid2"].map(count_all).fillna(0).astype(int)
villages["n_phc_chc_10km"] = villages["shrid2"].map(count_phc).fillna(0).astype(int)

print(f"  Count within 10 km computed in {time.time()-t0:.2f}s")
print(f"  Facilities within 10 km: mean {villages['n_hc_10km'].mean():.1f}, min {villages['n_hc_10km'].min()}, max {villages['n_hc_10km'].max()}")
print(f"  PHC/CHCs within 10 km:   mean {villages['n_phc_chc_10km'].mean():.1f}, min {villages['n_phc_chc_10km'].min()}, max {villages['n_phc_chc_10km'].max()}")

# ── 5. SAVE INTERIM HEALTH FEATURES ───────────────────────────────────────────
cols_to_save = [
    "shrid2", "village_code",
    "dist_nearest_hc_km", "dist_nearest_phc_km", "dist_nearest_hospital_km",
    "n_hc_10km", "n_phc_chc_10km"
]
features_hc = villages[cols_to_save].copy()
features_hc.to_parquet("data/interim/features_health_centres.parquet", index=False)
print("\nSaved data/interim/features_health_centres.parquet")
print(features_hc.describe().round(2).to_string())
print("\nSTAGE 2 COMPLETE: Health centre spatial join finished.")
