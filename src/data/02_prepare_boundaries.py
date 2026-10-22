"""
02_prepare_boundaries.py
Extracts SHRUG village polygons for Karnataka coastal districts (563: Uttara Kannada,
569: Udupi, 575: Dakshina Kannada) and joins them with Census 2011 Village Amenities.

Outputs:
  - data/interim/villages_coastal_utm.parquet (EPSG:32643 - metric CRS)
  - data/interim/villages_coastal_wgs84.parquet (EPSG:4326 - degree CRS)
  - data/interim/census_coastal.parquet (tabular Census data)
"""

import os
import sys
import time

# Ensure UTF-8 console output
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import fiona
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import shape

os.makedirs("data/interim", exist_ok=True)

# ── PARAMETERS ────────────────────────────────────────────────────────────────
COASTAL_DIST_CODES = {
    563: "Uttara Kannada",
    569: "Udupi",
    575: "Dakshina Kannada"
}
SHRUG_SHP = "data/raw/shrug/shrug-shrid-poly-shp/shrid2_open.shp"
VILLAGE_XLSX = "data/raw/DH_2011_DCHB_Village_Release_2900.xlsx"
UTM_CRS = "EPSG:32643"  # UTM Zone 43N (meters) - standard projection for Western India

print("=" * 70)
print("STAGE 1: EXTRACTING SHRUG BOUNDARIES FOR COASTAL KARNATAKA")
print("=" * 70)

t0 = time.time()
target_prefixes = tuple(f"11-29-{code}-" for code in COASTAL_DIST_CODES.keys())
print(f"Target SHRUG prefixes: {target_prefixes}")

features = []
with fiona.open(SHRUG_SHP) as src:
    orig_crs = src.crs
    for feat in src:
        s2 = feat["properties"].get("shrid2", "")
        if s2.startswith(target_prefixes):
            props = dict(feat["properties"])
            geom = shape(feat["geometry"])
            props["geometry"] = geom
            features.append(props)

print(f"Extracted {len(features):,} village polygons from SHRUG in {time.time()-t0:.2f}s")

shrug_gdf = gpd.GeoDataFrame(features, geometry="geometry", crs=orig_crs)
print(f"SHRUG GDF shape: {shrug_gdf.shape}, CRS: {shrug_gdf.crs}")

# Parse shrid2: format is 11-29-DDD-SSSSS-VVVVVV
parts = shrug_gdf["shrid2"].str.split("-", expand=True)
shrug_gdf["shrid2_year"] = parts[0]
shrug_gdf["shrid2_state"] = parts[1]
shrug_gdf["district_code"] = parts[2].astype(int)
shrug_gdf["subdist_code"] = parts[3]
shrug_gdf["shrid2_village"] = parts[4]
shrug_gdf["village_code"] = shrug_gdf["pc11_id"].astype(str).str.zfill(6)
shrug_gdf["district_name"] = shrug_gdf["district_code"].map(COASTAL_DIST_CODES)

print("\nSHRUG Polygons per District:")
print(shrug_gdf["district_name"].value_counts().to_string())

# ── GEOMETRY SANITY CHECKS & REPAIR ──────────────────────────────────────────
print("\n" + "-" * 50)
print("Geometry Sanity Checks:")
print(f"  Total features: {len(shrug_gdf):,}")
invalid_count = (~shrug_gdf.geometry.is_valid).sum()
empty_count = shrug_gdf.geometry.is_empty.sum()
null_count = shrug_gdf.geometry.isna().sum()
print(f"  Invalid geometries: {invalid_count}")
print(f"  Empty geometries:   {empty_count}")
print(f"  Null geometries:    {null_count}")

if invalid_count > 0:
    print("  Applying shapely buffer(0) fix for self-intersections...")
    shrug_gdf["geometry"] = shrug_gdf.geometry.buffer(0)
    still_invalid = (~shrug_gdf.geometry.is_valid).sum()
    print(f"  Invalid geometries remaining: {still_invalid}")

# Reproject to metric CRS (EPSG:32643) for spatial metrics
shrug_utm = shrug_gdf.to_crs(UTM_CRS)
shrug_utm["area_sqkm"] = (shrug_utm.geometry.area / 1e6).round(4)
print(f"Reprojected to metric CRS: {shrug_utm.crs}")
print(f"Village Area stats (sq km):\n{shrug_utm['area_sqkm'].describe().round(3).to_string()}")

# Compute centroids in both UTM and WGS84
shrug_utm["centroid_x_m"] = shrug_utm.geometry.centroid.x
shrug_utm["centroid_y_m"] = shrug_utm.geometry.centroid.y

centroids_wgs84 = gpd.GeoSeries(
    gpd.points_from_xy(shrug_utm["centroid_x_m"], shrug_utm["centroid_y_m"]),
    crs=UTM_CRS
).to_crs("EPSG:4326")

shrug_utm["lon"] = centroids_wgs84.x
shrug_utm["lat"] = centroids_wgs84.y

shrug_wgs84 = shrug_gdf.copy()
shrug_wgs84["lon"] = centroids_wgs84.x
shrug_wgs84["lat"] = centroids_wgs84.y
shrug_wgs84["area_sqkm"] = shrug_utm["area_sqkm"]

print(f"Centroid Longitude Range: {shrug_utm['lon'].min():.4f} to {shrug_utm['lon'].max():.4f}")
print(f"Centroid Latitude Range:  {shrug_utm['lat'].min():.4f} to {shrug_utm['lat'].max():.4f}")

# ── LOAD CENSUS VILLAGE AMENITIES ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("STAGE 2: LOADING AND PARSING CENSUS VILLAGE DIRECTORY")
print("=" * 70)

t0 = time.time()
census_raw = pd.read_excel(
    VILLAGE_XLSX,
    sheet_name="Village_Data_2900",
    engine="openpyxl",
    header=0
)
print(f"Loaded {len(census_raw):,} total villages from Census Excel in {time.time()-t0:.2f}s")

coastal_census = census_raw[census_raw["District Code"].isin(COASTAL_DIST_CODES.keys())].copy()
print(f"Coastal villages in Census: {len(coastal_census):,}")
print(coastal_census["District Name"].value_counts().to_string())

coastal_census["village_code"] = coastal_census["Village Code"].astype(str).str.zfill(6)
coastal_census["district_code"] = coastal_census["District Code"].astype(int)

# Extract core feature columns
KEEP_COLUMNS = {
    "District Code": "census_district_code",
    "District Name": "census_district_name",
    "Sub District Code": "census_subdist_code",
    "Sub District Name": "subdistrict_name",
    "Village Code": "census_village_code_raw",
    "Village Name": "village_name",
    "village_code": "village_code",
    "Total Geographical Area (in Hectares)": "census_area_ha",
    "Total   Households ": "total_households",
    "Total Population of Village": "total_population",
    "Total Male Population of Village": "pop_male",
    "Total Female Population of Village": "pop_female",
    "Total Scheduled Castes Population of Village": "pop_sc",
    "Total Scheduled Tribes Population of Village": "pop_st",
    # Health facility counts
    "Hospital Allopathic (Numbers)": "n_hosp_allopathic_census",
    "Primary Health Centre (Numbers)": "n_phc_census",
    "Community Health Centre (Numbers)": "n_chc_census",
    # Drinking water amenities (1=Available, 2=Not Available)
    "Tap Water-Treated (Status A(1)/NA(2))": "tap_water_treated",
    "Tap Water Untreated (Status A(1)/NA(2))": "tap_water_untreated",
    "Covered Well (Status A(1)/NA(2))": "covered_well",
    "Tube Wells/Borehole (Status A(1)/NA(2))": "tubewell_borehole",
    # Transport & connectivity
    "Public Bus Service (Status A(1)/NA(2))": "bus_service_public",
    "Private Bus Service (Status A(1)/NA(2))": "bus_service_private",
    "Major District Road (Status A(1)/NA(2))": "major_district_road",
    "Black Topped (pucca) Road (Status A(1)/NA(2))": "pucca_road",
    # Distances to hubs
    "District Head Quarter  (Distance in km)": "dist_district_hq_km",
    "Sub District Head Quarter (Distance in km)": "dist_subdist_hq_km",
    "Nearest Statutory Town (Distance in km)": "dist_nearest_town_km",
}

clean_census = coastal_census[[c for c in KEEP_COLUMNS.keys() if c in coastal_census.columns]].copy()
clean_census.rename(columns=KEEP_COLUMNS, inplace=True)

# Coerce numeric columns
numeric_fields = [
    "total_population", "total_households", "pop_male", "pop_female",
    "pop_sc", "pop_st", "census_area_ha",
    "n_hosp_allopathic_census", "n_phc_census", "n_chc_census",
    "dist_district_hq_km", "dist_subdist_hq_km", "dist_nearest_town_km"
]
for f in numeric_fields:
    if f in clean_census.columns:
        clean_census[f] = pd.to_numeric(clean_census[f], errors="coerce").fillna(0)

# Derived demographic ratios
pop = clean_census["total_population"].astype(float)
hh = clean_census["total_households"].astype(float)
clean_census["pop_density_per_ha"] = np.where(clean_census["census_area_ha"] > 0, pop / clean_census["census_area_ha"], 0).round(2)
clean_census["avg_household_size"] = np.where(hh > 0, pop / hh, 0).round(2)
clean_census["sc_share"] = np.where(pop > 0, clean_census["pop_sc"] / pop, 0).round(4)
clean_census["st_share"] = np.where(pop > 0, clean_census["pop_st"] / pop, 0).round(4)
clean_census["vulnerable_pop_share"] = (clean_census["sc_share"] + clean_census["st_share"]).clip(0, 1).round(4)

# Binary status indicators: In Census 1 = Available, 2 = Not Available
# Transform to binary 1=Available, 0=Not Available
status_cols = [
    "tap_water_treated", "tap_water_untreated", "covered_well", "tubewell_borehole",
    "bus_service_public", "bus_service_private", "major_district_road", "pucca_road"
]
for col in status_cols:
    if col in clean_census.columns:
        clean_census[col] = (clean_census[col] == 1).astype(int)

# Road connectivity index (0-3 scale: pucca road + major district road + bus access)
clean_census["road_connectivity_score"] = (
    clean_census["pucca_road"] * 1.5 +
    clean_census["major_district_road"] * 1.0 +
    ((clean_census["bus_service_public"] == 1) | (clean_census["bus_service_private"] == 1)).astype(int) * 0.5
).round(2)

# Drinking water score (0-2 scale: treated tap water + covered well / tubewell)
clean_census["drinking_water_score"] = (
    clean_census["tap_water_treated"] * 1.2 +
    clean_census["tap_water_untreated"] * 0.4 +
    clean_census["covered_well"] * 0.4
).clip(0, 2).round(2)

clean_census.to_parquet("data/interim/census_coastal.parquet", index=False)
print("Saved data/interim/census_coastal.parquet")

# ── JOIN SHRUG AND CENSUS ─────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STAGE 3: JOINING SHRUG SPATIAL BOUNDARIES WITH CENSUS AMENITIES")
print("=" * 70)

overlap = set(shrug_utm["village_code"]).intersection(set(clean_census["village_code"]))
print(f"SHRUG village polygons: {len(shrug_utm):,}")
print(f"Census villages:        {len(clean_census):,}")
print(f"Direct overlapping key: {len(overlap):,} ({len(overlap)/len(clean_census):.2%} of Census, {len(overlap)/len(shrug_utm):.2%} of SHRUG)")

# Merge census attributes onto spatial boundaries
shrug_utm_merged = shrug_utm.merge(clean_census, on="village_code", how="left")
shrug_wgs84_merged = shrug_wgs84.merge(clean_census, on="village_code", how="left")

# Fallback village_name from subdist/code if census missing
shrug_utm_merged["village_name"] = shrug_utm_merged["village_name"].fillna("Village_" + shrug_utm_merged["village_code"])
shrug_wgs84_merged["village_name"] = shrug_wgs84_merged["village_name"].fillna("Village_" + shrug_wgs84_merged["village_code"])

# Save interim files
shrug_utm_merged.to_parquet("data/interim/villages_coastal_utm.parquet", index=False)
shrug_wgs84_merged.to_parquet("data/interim/villages_coastal_wgs84.parquet", index=False)

print("Saved data/interim/villages_coastal_utm.parquet (EPSG:32643)")
print("Saved data/interim/villages_coastal_wgs84.parquet (EPSG:4326)")
print("\nSTAGE 1 COMPLETE: Boundaries and Census features ready.")
