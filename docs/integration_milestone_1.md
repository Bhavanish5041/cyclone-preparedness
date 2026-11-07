# Milestone 1: Relational Reconciliation & Archetype Integration Documentation

This document provides the complete technical specification and execution record for **Milestone 1** of the integration between the **Vulnerability Clustering** repository (`/home/bhavanish/cyclone-preparedness-assistant`) and the **Disaster Preparedness Assistant** repository (`/home/bhavanish/cyclone-preparedness`).

---

## 1. Source Datasets

| Dataset Role | Repository | File Path | Format | Records | Districts Covered |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Vulnerability Archetypes** | `cyclone-preparedness-assistant` | `data/processed/coastal_vulnerability_archetypes.parquet` | GeoParquet (EPSG:4326) | 622 units | Dakshina Kannada (369), Udupi (253) |
| **Preparedness Master** | `cyclone-preparedness` | `data/processed/master_village_preparedness.parquet` | Parquet (tabular) | 1,879 units | Dakshina Kannada (369), Udupi (253), Uttara Kannada (1,257) |

---

## 2. Canonical Join Key

The integration uses a **deterministic 1:1 relational join** on:

$$\text{clustering.shrid2} == \text{preparedness.area_id}$$

### Why `shrid2` / `area_id` Is the Exclusive Join Key
1. **Uniqueness:** Both `shrid2` (in clustering) and `area_id` (in preparedness) are strictly unique, non-null primary keys conforming to the SHRUG v2.1 schema: `11-SS-DDD-TTTTT-VVVVVV`.
2. **Rejection of `village_code` / `pc11_id`:** The audit revealed that in `cyclone-preparedness/src/data/02_prepare_boundaries.py`, `village_code` was cast from shapefile properties via `.str.zfill(6)`. Two features had null `pc11_id` values in SHRUG, resulting in a `'00None'` string collision between `11-29-575-05564-617728` (Kodimbala, DK) and `11-29-569-05523-608856` (Mallar town, Udupi). Joining on `village_code` would cause incorrect row expansion and corruption.
3. **Identifier Harmonization:** In the unified dataset, `shrid2` is the canonical primary key. `area_id` is retained for backwards compatibility (`shrid2 == area_id`). `pc11_id` and `village_code` are reconciled from token 5 of `shrid2`, eliminating the `'00None'` issue.

---

## 3. Join Statistics and Verification

```
================================================================================
JOIN SUMMARY
================================================================================
Total Output Rows:             1,879 (100.0% of Preparedness records preserved)
Total Output Columns:             57
Exact Primary Key Matches:       622 (100.0% of Clustering records)
Unmatched Clustering Records:      0 (  0.0% data loss)
Unmatched Preparedness Records:1,257 (100.0% located in Uttara Kannada)
Duplication / Cartesian Growth:    0 (Strict 1:1 match)
================================================================================
```

### Breakdown by District and Verified Unit Type

| District Name | District Code | Total Units | Verified Villages | Verified Towns | Assignment Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Dakshina Kannada** | 575 | 369 | 330 | 39 | `ASSIGNED` (622 total) |
| **Udupi** | 569 | 253 | 233 | 20 | `ASSIGNED` (622 total) |
| **Uttara Kannada** | 563 | 1,257 | Unverified (Census Village list) | 0 verified | `UNASSIGNED_OUT_OF_STUDY_AREA` |
| **Total** | — | **1,879** | **563** | **59** | — |

> [!NOTE]
> **Resolution of Village / Town Counts:**
> Earlier inspection documents referenced "561 villages + 61 towns" as an approximation. The actual parquet file ground truth was audited and confirmed: exactly **563 villages** and **59 towns** (total = 622 units).

---

## 4. Output Schema (`data/processed/unified_village_preparedness.parquet`)

The unified output contains 57 columns, organized into distinct logical domains:

### A. Administrative and Geographic Identifiers
- `shrid2`: Canonical SHRUG v2.1 primary key string (`11-SS-DDD-TTTTT-VVVVVV`).
- `area_id`: Retained identifier matching `shrid2` for traceability.
- `pc11_id`: Clean Census 2011 6-digit village/town code.
- `village_code`: Clean Census code matching `pc11_id`.
- `village_name`: Harmonized name (canonical town/village name from clustering for matched units; trimmed name for unmatched units).
- `district_name`: `'Dakshina Kannada'`, `'Udupi'`, or `'Uttara Kannada'`.
- `district_code`: `575`, `569`, or `563`.
- `subdistrict_name`: Taluk name.
- `unit_type`: `'VILLAGE'` or `'TOWN'` for verified units; null for unverified units.
- `lat`, `lon`: Spatial centroid / coordinates.
- `village_area_sqkm`: Geographical area in square kilometers.

### B. Preparedness Assessment (AHP/MCDA)
- `preparedness_score`: Composite preparedness index `[0.0, 100.0]`.
- `preparedness_tier`: Categorical readiness classification (`'Low'`, `'Medium'`, `'High'`).
- `score_medical`: Medical facility accessibility component score.
- `score_shelters`: Cyclone shelter accessibility and capacity score.
- `score_infrastructure`: Road and water infrastructure composite score.
- `score_early_warning`: Rain gauge network monitoring coverage score.
- `score_socioeconomic`: Demographic and social resilience score.
- `vulnerability_tier`: Coastal vulnerability index tier.
- `cvi_physical`, `cvi_social`, `cvi_integrated`: Coastal vulnerability indices.

### C. Vulnerability Archetype Dimensions
- `vulnerability_archetype_id`: Nullable `Int16` cluster index (`0`, `1`, `2`, `3`; null for unassigned).
- `vulnerability_archetype_label`: Descriptive archetype string:
  - `0`: Urban & Peri-Urban Well-Resourced Corridor
  - `1`: Remote Foothill & Healthcare-Isolated Communities
  - `2`: Socioeconomically Vulnerable Rural Interior
  - `3`: High-Exposure Coastal Rural Belt
- `archetype_intervention_need`: Canonical operational intervention guidance.
- `cluster_assignment_status`: `'ASSIGNED'` (622 units) or `'UNASSIGNED_OUT_OF_STUDY_AREA'` (1,257 units).

### D. Contextual Infrastructure & Demographic Baseline
- `population`, `households`, `pop_density_sqkm`, `avg_household_size`, `sc_share`, `st_share`, `vulnerable_pop_share`
- `elevation_mean`, `dist_coast_km`
- `dist_nearest_shelter_km`, `n_shelters_10km`, `shelter_capacity_nearby`, `shelter_capacity_per_capita`, `shelter_road_access`
- `dist_nearest_hc_km`, `dist_nearest_phc_km`, `dist_nearest_hospital_km`, `n_hc_10km`, `n_phc_chc_10km`, `has_phc_or_chc`
- `dist_nearest_gauge_km`, `n_gauges_20km`, `nearest_gauge_name`
- `road_connectivity_score`, `drinking_water_score`, `has_pucca_road`, `has_major_district_road`, `bus_connectivity`
- `tauktae_affected`: Historical marker for Cyclone Tauktae (May 2021) impact.
- `data_disclaimer`: Mandatory analytical and vintage caveat.

---

## 5. Handling of Unmatched Units

The 1,257 units in Uttara Kannada are explicitly handled according to strict methodological standards:
- `cluster_assignment_status` is explicitly set to `'UNASSIGNED_OUT_OF_STUDY_AREA'`.
- `vulnerability_archetype_id`, `vulnerability_archetype_label`, and `archetype_intervention_need` are populated with `null` (`<NA>`).
- **No silent defaults:** Units outside the study area are never forced into an arbitrary cluster.
- All original preparedness scores, tiers, sub-scores, and raw census indicators are preserved with 100% fidelity.

---

## 6. Automated Validation Results

All 12 validation tests in `tests/test_integration_integrity.py` were executed with `pytest`:

```
============================== test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.1.1, pluggy-1.7.0
rootdir: /home/bhavanish/cyclone-preparedness-assistant
configfile: pyproject.toml
collected 12 items

tests/test_integration_integrity.py ............                         [100%]

============================== 12 passed in 0.97s ==============================
```

### Verified Test Cases
1. `test_1_row_count`: Exactly 1,879 rows in unified output.
2. `test_2_shrid2_unique_and_non_null`: 100% uniqueness and zero nulls in `shrid2`.
3. `test_3_assigned_count`: Exactly 622 records marked `ASSIGNED`.
4. `test_4_unassigned_count`: Exactly 1,257 records marked `UNASSIGNED_OUT_OF_STUDY_AREA`.
5. `test_5_archetype_ids_match_clustering_source`: 100% agreement on `vulnerability_archetype_id`.
6. `test_6_archetype_labels_match_clustering_source`: 100% agreement on `vulnerability_archetype_label`.
7. `test_7_intervention_descriptions_match_clustering_source`: 100% agreement on `archetype_intervention_need`.
8. `test_8_preparedness_scores_and_tiers_preserved`: Exact float parity (`atol=1e-5`) on `preparedness_score` and tier strings.
9. `test_9_no_cartesian_join_or_row_loss`: Input and output key sets are identical.
10. `test_10_matched_town_records_names_and_unit_types`: 59 towns retain `unit_type == 'TOWN'` and canonical names without `'Village_'` prefix.
11. `test_11_unmatched_records_have_null_archetype_fields`: All 1,257 Uttara Kannada records have null archetype fields.
12. `test_12_no_duplicate_primary_keys`: Zero duplicated keys in `shrid2` or `area_id`.

---

## 7. Methodological Safeguards & Known Limitations

> [!IMPORTANT]
> 1. **Descriptive Archetypes, Not Hazard Classes:**
>    Discovered vulnerability archetypes reflect structural socioeconomic and spatial accessibility deficits (K-Means on 4 normalized dimensions). They are **not** real-time cyclone landfall predictions, storm-surge inundation zones, or casualty estimates.
> 2. **AHP/MCDA Preparedness Baseline:**
>    Preparedness scores and tiers are derived from the teammate's Analytic Hierarchy Process / Multi-Criteria Decision Analysis framework. They represent structural resource baseline capacity rather than empirical post-disaster performance.
> 3. **Data Vintage Caveat:**
>    Demographic indicators and administrative boundaries derive from the 2011 Census of India and SHRUG v2.1. They serve as a structural baseline and do not capture post-2011 urbanization or local infrastructure upgrades.
> 4. **No Fabricated Probabilities:**
>    In accordance with Milestone 1 scope, no synthetic probability columns or unverified inference outputs have been added.

---

## 8. How to Rerun the Integration Pipeline

### CLI Execution
From the root of `/home/bhavanish/cyclone-preparedness-assistant`:

```bash
# Execute with default paths
.venv/bin/python src/integration/join_preparedness_archetypes.py

# Or specify custom paths if needed
.venv/bin/python src/integration/join_preparedness_archetypes.py \
    --preparedness-path /home/bhavanish/cyclone-preparedness/data/processed/master_village_preparedness.parquet \
    --archetypes-path /home/bhavanish/cyclone-preparedness-assistant/data/processed/coastal_vulnerability_archetypes.parquet \
    --output-path data/processed/unified_village_preparedness.parquet
```

### Python Programmatic Usage
```python
from src.integration import integrate_preparedness_and_archetypes

unified_df = integrate_preparedness_and_archetypes()
print(f"Generated unified dataset with {len(unified_df)} rows.")
```

### Running Validation Tests
```bash
.venv/bin/pytest tests/test_integration_integrity.py -v
```
