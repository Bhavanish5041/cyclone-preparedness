# Milestone 2C: Unified Dataset Enrichment with Logistic Regression Predictions

This document describes the technical specifications, data lineage, schema additions, and validation results for **Milestone 2C**. In this milestone, the reproduced Multinomial Logistic Regression model's predictions, class probabilities, and split provenance tags were joined onto the unified village preparedness dataset without altering Milestone 1 artifacts or baseline scores.

---

## 1. Source Datasets & Join Methodology

| Dataset Role | File Path | Record Count | Join Key | Key Role |
| :--- | :--- | :--- | :--- | :--- |
| **Milestone 1 Unified Table** | `data/processed/unified_village_preparedness.parquet` | 1,879 rows | `shrid2` | Primary Key (Canonical SHRUG v2.1) |
| **Model Predictions & Probabilities** | `data/processed/village_preparedness_probabilities.parquet` | 1,879 rows | `area_id` | Foreign Key (matches `shrid2`) |
| **Fitted Model Pipeline** | `models/logistic_regression_tier.joblib` | Scaler + Model | — | Serialized in Milestone 2B |
| **Model Metadata** | `models/logistic_regression_metadata.json` | JSON audit log | — | Experiment tracking & split indices |

### Validated Join Logic
$$\text{unified\_v1.shrid2} == \text{probabilities.area_id}$$

- Executed as a verified 1:1 left-join.
- Zero unmatched records (1,879 / 1,879 matched).
- Zero duplicated records; row count is strictly preserved at 1,879.
- Milestone 1 files (`unified_village_preparedness.parquet` and `.csv`) were **not overwritten**.
- The enriched dataset is persisted to a dedicated new output:
  - `data/processed/unified_village_preparedness_v2.parquet`
  - `data/processed/unified_village_preparedness_v2.csv`

---

## 2. Enriched Output Schema (`unified_village_preparedness_v2.parquet`)

The enriched v2 dataset contains **63 columns** (57 original columns + 6 new model-derived columns).

### New Columns Added in Milestone 2C

| Column Name | Data Type | Nullable | Source | Description |
| :--- | :--- | :--- | :--- | :--- |
| `predicted_preparedness_tier` | `object` (string) | No | Logistic Regression | Model predicted tier (`'High'`, `'Low'`, `'Medium'`). Reflects maximum class probability. |
| `prob_low` | `float64` | No | Logistic Regression | Model class probability $[0.0, 1.0]$ for `'Low'` preparedness tier. |
| `prob_medium` | `float64` | No | Logistic Regression | Model class probability $[0.0, 1.0]$ for `'Medium'` preparedness tier. |
| `prob_high` | `float64` | No | Logistic Regression | Model class probability $[0.0, 1.0]$ for `'High'` preparedness tier. |
| `prediction_provenance` | `object` (string) | No | Model Metadata | Split provenance tag (`'TRAIN_IN_SAMPLE'`, `'VAL_OUT_OF_SAMPLE'`, `'TEST_OUT_OF_SAMPLE'`). |
| `probability_disclaimer` | `object` (string) | No | Integration Pipeline | Mandatory disclaimer on statistical interpretation of probabilities. |

### Preserved Milestone 1 Columns
- **Administrative Identifiers:** `shrid2`, `area_id`, `pc11_id`, `village_code`, `village_name`, `district_name`, `district_code`, `subdistrict_name`, `unit_type`, `lat`, `lon`, `village_area_sqkm` (12 columns).
- **AHP/MCDA Preparedness Assessment:** `preparedness_score`, `preparedness_tier`, `score_medical`, `score_shelters`, `score_infrastructure`, `score_early_warning`, `score_socioeconomic`, `vulnerability_tier`, `cvi_physical`, `cvi_social`, `cvi_integrated` (11 columns).
- **K-Means Vulnerability Archetypes:** `vulnerability_archetype_id`, `vulnerability_archetype_label`, `archetype_intervention_need`, `cluster_assignment_status` (4 columns).
- **Contextual Demographics & Amenities:** `population`, `households`, `pop_density_sqkm`, `avg_household_size`, `sc_share`, `st_share`, `vulnerable_pop_share`, `elevation_mean`, `dist_coast_km`, `dist_nearest_shelter_km`, `n_shelters_10km`, `shelter_capacity_nearby`, `shelter_capacity_per_capita`, `shelter_road_access`, `dist_nearest_hc_km`, `dist_nearest_phc_km`, `dist_nearest_hospital_km`, `n_hc_10km`, `n_phc_chc_10km`, `has_phc_or_chc`, `dist_nearest_gauge_km`, `n_gauges_20km`, `nearest_gauge_name`, `road_connectivity_score`, `drinking_water_score`, `has_pucca_road`, `has_major_district_road`, `bus_connectivity`, `tauktae_affected`, `data_disclaimer` (30 columns).

---

## 3. Class Mapping & Probability Interpretation

### Class Mapping
The model output probabilities were mapped using the estimator's `classes_` attribute and the fitted `LabelEncoder`:
- `le.classes_[0]` = `'High'` $\rightarrow$ `prob_high = probs[:, 0]`
- `le.classes_[1]` = `'Low'` $\rightarrow$ `prob_low = probs[:, 1]`
- `le.classes_[2]` = `'Medium'` $\rightarrow$ `prob_medium = probs[:, 2]`

### Mathematical Validity
- **Finiteness:** 100% of probability values are finite numbers.
- **Bounds:** All values are strictly within $[0.0000, 1.0000]$.
- **Probability Simplex:** $\text{prob\_low} + \text{prob\_medium} + \text{prob\_high} = 1.0000$ across all 1,879 rows ($\Delta < 10^{-3}$).
- **Argmax Agreement:** `predicted_preparedness_tier` matches the class with the highest probability for 100% of villages.

---

## 4. Prediction Provenance Tracking

To prevent presenting in-sample predictions as independent out-of-sample evaluations, each village is tagged with its role from the 70/15/15 stratified experiment:

```
Total Study Area: 1,879 Villages
├── TRAIN_IN_SAMPLE:   1,315 villages (70.0%) -> In-sample fit; training accuracy = 95.89%
├── VAL_OUT_OF_SAMPLE:   282 villages (15.0%) -> Out-of-sample tuning set; accuracy = 93.97%
└── TEST_OUT_OF_SAMPLE:  282 villages (15.0%) -> Independent holdout benchmark; accuracy = 94.33%
```

Overall classification agreement between `predicted_preparedness_tier` and the original `preparedness_tier` across all 1,879 records is **95.37%**.

---

## 5. Study-Area Coverage Preservation

The geographic scope and cluster assignments established in Milestone 1 are preserved without alteration:

| District Name | Total Units | `cluster_assignment_status` | Archetype Fields Status | Preparedness Model Predictions |
| :--- | :--- | :--- | :--- | :--- |
| **Dakshina Kannada** | 369 | `ASSIGNED` | Fully populated (Clusters 0..3) | Fully populated (`prob_low`, `prob_med`, `prob_high`) |
| **Udupi** | 253 | `ASSIGNED` | Fully populated (Clusters 0..3) | Fully populated (`prob_low`, `prob_med`, `prob_high`) |
| **Uttara Kannada** | 1,257 | `UNASSIGNED_OUT_OF_STUDY_AREA` | **Strictly `NULL` (`<NA>`)** | Fully populated (`prob_low`, `prob_med`, `prob_high`) |
| **Total** | **1,879** | **622 Assigned / 1,257 Unassigned** | **0 Synthetic Clusters** | **1,879 Finite Probability Vectors** |

- The 1,257 Uttara Kannada units have valid model predictions because they were part of the teammate's 1,879-village preparedness modelling dataset.
- The 1,257 Uttara Kannada units **remain strictly unassigned** with respect to vulnerability archetypes. No synthetic cluster IDs or default archetypes were applied.

---

## 6. Validation Test Suite

A dedicated Pytest test suite, `tests/test_unified_model_outputs.py`, was executed alongside regression tests:

```
============================== test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.1.1, pluggy-1.7.0
rootdir: /home/bhavanish/cyclone-preparedness-assistant
configfile: pyproject.toml
plugins: anyio-4.15.1, platformdirs-4.13.5
collected 34 items

tests/test_unified_model_outputs.py ..............                       [ 41%]
tests/test_integration_integrity.py ............                         [ 76%]
tests/test_model_reproduction.py ........                                [100%]

============================== 34 passed in 1.99s ==============================
```

All 14 tests in `test_unified_model_outputs.py` passed:
1. `test_1_row_count`: Exactly 1,879 rows.
2. `test_2_primary_key_unique_and_non_null`: Zero nulls, 1,879 unique keys.
3. `test_3_exact_one_to_one_join_with_probabilities`: 100% key alignment.
4. `test_4_probability_columns_exist`: All 5 prediction columns present.
5. `test_5_probabilities_are_finite`: Zero `NaN`/`Inf`.
6. `test_6_probabilities_within_zero_one`: Bounded in $[0, 1]$.
7. `test_7_probability_simplex_sum`: Sums to 1.0 within tolerance.
8. `test_8_predicted_tier_agrees_with_argmax`: Tier matches probability maximum.
9. `test_9_correct_class_label_mapping`: Alphabetical class mapping verified.
10. `test_10_prediction_provenance_counts`: Exactly 1,315 train, 282 val, 282 test.
11. `test_11_original_ahp_scores_and_tiers_unchanged`: Exact parity with Milestone 1.
12. `test_12_original_kmeans_archetypes_unchanged`: 100% agreement on archetypes.
13. `test_13_study_area_coverage_counts`: Exactly 622 assigned and 1,257 unassigned.
14. `test_14_no_cartesian_growth_or_duplicates`: 0 duplicated keys.

---

## 7. Methodological Limitations & Safeguards

> [!WARNING]
> **Mandatory Statistical Disclaimer:**
> 1. **Not Physical Disaster Risk:** The probabilities (`prob_low`, `prob_medium`, `prob_high`) represent multinomial logistic regression class likelihoods approximating the structural baseline capacity tiers derived from the AHP/MCDA framework. They are **NOT** calibrated physical cyclone-risk probabilities, storm-surge damage forecasts, or casualty predictions.
> 2. **In-Sample vs. Out-of-Sample Performance:** While the overall dataset classification agreement is 95.37%, users must note that for the 1,315 training-set villages (`TRAIN_IN_SAMPLE`), predictions are in-sample fits. The true out-of-sample generalization accuracy is represented by the 282 test-set villages (`TEST_OUT_OF_SAMPLE`: 94.33%).
> 3. **Preservation of Dual Tiers:** `preparedness_tier` (the original AHP ground truth) and `predicted_preparedness_tier` (the statistical approximation) are kept as distinct columns to ensure transparency where the model diverges from the heuristic index.
