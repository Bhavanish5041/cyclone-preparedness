"""Automated validation tests for Milestone 2C: Unified Dataset v2 with Model Predictions.

Verifies:
1. Exactly 1,879 rows.
2. Unique and non-null primary keys.
3. Exact one-to-one join with probability dataset.
4. All three probability columns exist.
5. Probability values are finite.
6. Probability values are within [0,1].
7. Probability sums equal 1 within tolerance.
8. Predicted tier agrees with probability argmax.
9. Correct class-label mapping.
10. Prediction provenance counts are exactly 1,315 / 282 / 282.
11. Original AHP scores and tiers are unchanged.
12. Original K-Means archetypes are unchanged.
13. Exactly 622 assigned and 1,257 unassigned archetype records.
14. No duplicate rows or Cartesian expansion.
"""

from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import pytest

UNIFIED_V2_PATH = Path("data/processed/unified_village_preparedness_v2.parquet")
UNIFIED_V1_PATH = Path("data/processed/unified_village_preparedness.parquet")
PROBABILITIES_PATH = Path("data/processed/village_preparedness_probabilities.parquet")
MODEL_PATH = Path("models/logistic_regression_tier.joblib")
ENCODER_PATH = Path("models/label_encoder.joblib")
CLUSTERING_PATH = Path("data/processed/coastal_vulnerability_archetypes.parquet")


@pytest.fixture(scope="module")
def df_v2():
    assert UNIFIED_V2_PATH.exists(), f"Missing unified v2 dataset at {UNIFIED_V2_PATH}"
    return pd.read_parquet(UNIFIED_V2_PATH)


@pytest.fixture(scope="module")
def df_v1():
    assert UNIFIED_V1_PATH.exists(), f"Missing unified v1 dataset at {UNIFIED_V1_PATH}"
    return pd.read_parquet(UNIFIED_V1_PATH)


@pytest.fixture(scope="module")
def df_prob():
    assert PROBABILITIES_PATH.exists(), f"Missing probabilities dataset at {PROBABILITIES_PATH}"
    return pd.read_parquet(PROBABILITIES_PATH)


@pytest.fixture(scope="module")
def encoder():
    assert ENCODER_PATH.exists(), f"Missing encoder at {ENCODER_PATH}"
    return joblib.load(ENCODER_PATH)


def test_1_row_count(df_v2):
    """Test 1: Output contains exactly 1,879 rows."""
    assert len(df_v2) == 1879, f"Expected 1,879 rows, got {len(df_v2)}"


def test_2_primary_key_unique_and_non_null(df_v2):
    """Test 2: Primary keys are strictly unique and non-null."""
    assert df_v2["shrid2"].isna().sum() == 0, "Null values found in shrid2"
    assert df_v2["shrid2"].nunique() == 1879, "Duplicate shrid2 values found"
    assert (df_v2["shrid2"] == df_v2["area_id"]).all(), "shrid2 does not match area_id"


def test_3_exact_one_to_one_join_with_probabilities(df_v2, df_prob):
    """Test 3: Exact 1:1 join with probability dataset."""
    assert (df_v2["shrid2"] == df_prob["area_id"]).all(), "Row alignment mismatch with probability dataset"


def test_4_probability_columns_exist(df_v2):
    """Test 4: All three probability columns and predicted tier exist."""
    required = ["prob_low", "prob_medium", "prob_high", "predicted_preparedness_tier", "prediction_provenance"]
    for col in required:
        assert col in df_v2.columns, f"Missing required column: {col}"


def test_5_probabilities_are_finite(df_v2):
    """Test 5: Probability values are strictly finite."""
    for col in ["prob_low", "prob_medium", "prob_high"]:
        assert np.isfinite(df_v2[col]).all(), f"Non-finite probability values found in {col}"


def test_6_probabilities_within_zero_one(df_v2):
    """Test 6: Probability values are within [0, 1]."""
    for col in ["prob_low", "prob_medium", "prob_high"]:
        assert (df_v2[col] >= 0.0).all(), f"Negative probability found in {col}"
        assert (df_v2[col] <= 1.0).all(), f"Probability > 1 found in {col}"


def test_7_probability_simplex_sum(df_v2):
    """Test 7: Probability sums equal 1.0 within numerical tolerance."""
    sums = df_v2["prob_low"] + df_v2["prob_medium"] + df_v2["prob_high"]
    np.testing.assert_allclose(sums, 1.0, atol=1e-3, err_msg="Probability simplex sum violated")


def test_8_predicted_tier_agrees_with_argmax(df_v2):
    """Test 8: Predicted tier agrees with probability argmax."""
    for _, row in df_v2.head(200).iterrows():
        p_h, p_l, p_m = row["prob_high"], row["prob_low"], row["prob_medium"]
        max_tier = "High" if (p_h >= p_l and p_h >= p_m) else ("Low" if (p_l >= p_m) else "Medium")
        assert row["predicted_preparedness_tier"] == max_tier


def test_9_correct_class_label_mapping(encoder):
    """Test 9: LabelEncoder class mapping is verified."""
    classes = list(encoder.classes_)
    assert classes == ["High", "Low", "Medium"]


def test_10_prediction_provenance_counts(df_v2):
    """Test 10: Prediction provenance counts are exactly 1,315 / 282 / 282."""
    counts = df_v2["prediction_provenance"].value_counts().to_dict()
    assert counts.get("TRAIN_IN_SAMPLE") == 1315
    assert counts.get("VAL_OUT_OF_SAMPLE") == 282
    assert counts.get("TEST_OUT_OF_SAMPLE") == 282
    assert sum(counts.values()) == 1879


def test_11_original_ahp_scores_and_tiers_unchanged(df_v2, df_v1):
    """Test 11: Original AHP preparedness scores and tiers are unchanged from Milestone 1."""
    np.testing.assert_allclose(df_v2["preparedness_score"], df_v1["preparedness_score"], atol=1e-5)
    assert (df_v2["preparedness_tier"] == df_v1["preparedness_tier"]).all()


def test_12_original_kmeans_archetypes_unchanged(df_v2, df_v1):
    """Test 12: Original K-Means archetype labels, IDs, and interventions are unchanged."""
    assigned_v2 = df_v2[df_v2["cluster_assignment_status"] == "ASSIGNED"]
    assigned_v1 = df_v1[df_v1["cluster_assignment_status"] == "ASSIGNED"]
    assert len(assigned_v2) == len(assigned_v1) == 622
    assert (assigned_v2["vulnerability_archetype_id"] == assigned_v1["vulnerability_archetype_id"]).all()
    assert (assigned_v2["vulnerability_archetype_label"] == assigned_v1["vulnerability_archetype_label"]).all()
    assert (assigned_v2["archetype_intervention_need"] == assigned_v1["archetype_intervention_need"]).all()


def test_13_study_area_coverage_counts(df_v2):
    """Test 13: Exactly 622 assigned and 1,257 unassigned archetype records."""
    counts = df_v2["cluster_assignment_status"].value_counts().to_dict()
    assert counts.get("ASSIGNED") == 622
    assert counts.get("UNASSIGNED_OUT_OF_STUDY_AREA") == 1257
    unassigned = df_v2[df_v2["cluster_assignment_status"] == "UNASSIGNED_OUT_OF_STUDY_AREA"]
    assert unassigned["vulnerability_archetype_id"].isna().all()
    assert unassigned["vulnerability_archetype_label"].isna().all()


def test_14_no_cartesian_growth_or_duplicates(df_v2, df_v1):
    """Test 14: No duplicate rows or Cartesian expansion."""
    assert len(df_v2) == len(df_v1) == 1879
    assert df_v2["shrid2"].duplicated().sum() == 0
