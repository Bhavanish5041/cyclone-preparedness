"""
04_join_rain_gauges.py
Parse KSNDMC telemetric rain gauge KML, extract coordinates,
filter to coastal Karnataka region, and spatial-join to village polygons.

Calculates:
  - dist_nearest_gauge_km : Distance to nearest telemetric rain gauge (km)
  - n_gauges_20km          : Density of rain gauges within 20 km radius
  - nearest_gauge_name    : Name of the nearest KSNDMC monitoring station

Source: data/raw/70578d25-7ede-426c-8e8e-5c679274a55a.kml
"""

import os
import sys
import time

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import geopandas as gpd
import xml.etree.ElementTree as etree
import numpy as np
import pandas as pd

os.makedirs("data/interim", exist_ok=True)

UTM_CRS = "EPSG:32643"
KML_PATH = "data/raw/70578d25-7ede-426c-8e8e-5c679274a55a.kml"

print("=" * 70)
print("STAGE 3: PARSING KSNDMC RAIN GAUGES & SPATIAL JOIN TO VILLAGES")
print("=" * 70)

# ── 1. PARSE KSNDMC KML ───────────────────────────────────────────────────────
t0 = time.time()
tree = etree.parse(KML_PATH)
root = tree.getroot()
ns = {"kml": "http://www.opengis.net/kml/2.2"}

records = []
for placemark in root.findall(".//kml:Placemark", ns):
    name_el = placemark.find(".//kml:SimpleData[@name='TM_RainGauge_LocationName']", ns)
    name = name_el.text if name_el is not None else None

    sid_el = placemark.find(".//kml:SimpleData[@name='KGISTM_RainGauge_LocationID']", ns)
    sid = sid_el.text if sid_el is not None else None

    kgiscode_el = placemark.find(".//kml:SimpleData[@name='KGISCode']", ns)
    kgiscode = kgiscode_el.text if kgiscode_el is not None else ""

    coord_el = placemark.find(".//kml:coordinates", ns)
    if coord_el is None or not coord_el.text:
        continue
    parts = coord_el.text.strip().split(",")
    if len(parts) < 2:
        continue
    try:
        lon, lat = float(parts[0]), float(parts[1])
    except ValueError:
        continue

    records.append({
        "station_id": sid,
        "station_name": name,
        "kgiscode": kgiscode,
        "lon": lon,
        "lat": lat,
    })

gauges_df = pd.DataFrame(records)
print(f"Parsed {len(gauges_df):,} rain gauges from KML in {time.time()-t0:.2f}s")

# Filter to coastal Karnataka extent (approx 11.5°N - 16.0°N, 73.8°E - 76.5°E)
gauges_coastal = gauges_df[
    (gauges_df["lat"].between(11.5, 16.0)) &
    (gauges_df["lon"].between(73.8, 76.5))
].copy()
print(f"KSNDMC gauges within coastal extent: {len(gauges_coastal):,}")

# Convert to GeoDataFrame in UTM CRS
gauges_gdf = gpd.GeoDataFrame(
    gauges_coastal,
    geometry=gpd.points_from_xy(gauges_coastal["lon"], gauges_coastal["lat"]),
    crs="EPSG:4326"
).to_crs(UTM_CRS)

# ── 2. LOAD VILLAGE POLYGONS ──────────────────────────────────────────────────
villages = gpd.read_parquet("data/interim/villages_coastal_utm.parquet")
print(f"\nLoaded {len(villages):,} coastal village polygons in {villages.crs}")

# ── 3. DISTANCE TO NEAREST RAIN GAUGE ─────────────────────────────────────────
t0 = time.time()
nearest = gpd.sjoin_nearest(
    villages[["shrid2", "geometry"]],
    gauges_gdf[["station_id", "station_name", "geometry"]],
    how="left",
    distance_col="dist_nearest_gauge_m"
).sort_values("dist_nearest_gauge_m").drop_duplicates("shrid2")

villages["dist_nearest_gauge_km"] = (nearest["dist_nearest_gauge_m"] / 1000.0).round(2)
villages["nearest_gauge_id"] = nearest["station_id"]
villages["nearest_gauge_name"] = nearest["station_name"]

print(f"\nNearest rain gauge distance computed in {time.time()-t0:.2f}s")
print(f"  Distance stats (km): mean {villages['dist_nearest_gauge_km'].mean():.2f}, min {villages['dist_nearest_gauge_km'].min():.2f}, max {villages['dist_nearest_gauge_km'].max():.2f}")

# ── 4. COUNT GAUGES WITHIN 20 KM BUFFER ───────────────────────────────────────
t0 = time.time()
village_buf = villages[["shrid2", "geometry"]].copy()
village_buf["geometry"] = village_buf.geometry.centroid.buffer(20_000)

joined = gpd.sjoin(
    village_buf,
    gauges_gdf[["geometry"]],
    how="left",
    predicate="contains"
)

valid_matches = joined.dropna(subset=["index_right"])
count_gauges = valid_matches.groupby("shrid2").size().rename("n_gauges_20km")
villages["n_gauges_20km"] = villages["shrid2"].map(count_gauges).fillna(0).astype(int)

print(f"Rain gauge density within 20 km computed in {time.time()-t0:.2f}s")
print(f"  Gauges within 20 km: mean {villages['n_gauges_20km'].mean():.1f}, min {villages['n_gauges_20km'].min()}, max {villages['n_gauges_20km'].max()}")

# ── 5. SAVE INTERIM GAUGE FEATURES ────────────────────────────────────────────
out_cols = [
    "shrid2", "village_code",
    "dist_nearest_gauge_km", "nearest_gauge_id", "nearest_gauge_name",
    "n_gauges_20km"
]
features_gauges = villages[out_cols].copy()
features_gauges.to_parquet("data/interim/features_rain_gauges.parquet", index=False)
gauges_gdf[["station_id", "station_name", "lon", "lat", "geometry"]].to_parquet(
    "data/interim/ksndmc_gauges_coastal.parquet", index=False
)

print("\nSaved data/interim/features_rain_gauges.parquet")
print("Saved data/interim/ksndmc_gauges_coastal.parquet")
print(features_gauges.describe().round(2).to_string())
print("\nSTAGE 3 COMPLETE: Rain gauge spatial join finished.")
