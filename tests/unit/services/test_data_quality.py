"""Tests for app/services/data_quality.py -- validate_samples()."""

import pytest

from app.services.data_quality import summarize, validate_samples

pytestmark = pytest.mark.unit


def _codes(issues):
    return {i["code"] for i in issues}


def test_clean_data_has_no_issues():
    samples = [
        {"timestamp": str(1700000000 + i * 2), "temp": str(20.0 + i * 0.5), "temp_ref": "60.0"}
        for i in range(30)
    ]
    issues = validate_samples(samples, ["temp", "temp_ref"])
    assert issues == []


def test_empty_samples_is_an_error():
    issues = validate_samples([], [])
    assert "no_samples" in _codes(issues)
    errors, warnings = summarize(issues)
    assert errors == 1


def test_no_numeric_columns_is_an_error():
    samples = [{"timestamp": "1700000000", "label": "abc"}]
    issues = validate_samples(samples, [])
    assert "no_numeric_columns" in _codes(issues)


def test_missing_timestamp_column_is_a_warning():
    samples = [{"temp": "20.0"}, {"temp": "21.0"}]
    issues = validate_samples(samples, ["temp"])
    assert "missing_timestamp_column" in _codes(issues)


def test_invalid_timestamps_detected():
    samples = [
        {"timestamp": "1700000000", "temp": "20.0"},
        {"timestamp": "not-a-number", "temp": "21.0"},
    ]
    issues = validate_samples(samples, ["temp"])
    assert "invalid_timestamps" in _codes(issues)


def test_non_monotonic_timestamps_detected():
    samples = [
        {"timestamp": "1700000010", "temp": "20.0"},
        {"timestamp": "1700000000", "temp": "21.0"},  # earlier than the previous row
    ]
    issues = validate_samples(samples, ["temp"])
    assert "non_monotonic_timestamps" in _codes(issues)


def test_duplicate_rows_detected():
    samples = [
        {"timestamp": "1700000000", "temp": "20.0"},
        {"timestamp": "1700000000", "temp": "20.0"},
    ]
    issues = validate_samples(samples, ["temp"])
    assert "duplicate_rows" in _codes(issues)
    assert "duplicate_timestamps" in _codes(issues)


def test_duplicate_timestamps_without_identical_rows():
    samples = [
        {"timestamp": "1700000000", "temp": "20.0"},
        {"timestamp": "1700000000", "temp": "25.0"},  # same ts, different temp -- not a dup row
    ]
    issues = validate_samples(samples, ["temp"])
    assert "duplicate_timestamps" in _codes(issues)
    assert "duplicate_rows" not in _codes(issues)


def test_sample_gap_detected():
    # Regular 2s cadence except one huge jump.
    timestamps = list(range(1700000000, 1700000020, 2)) + [1700000200]
    samples = [{"timestamp": str(t), "temp": "20.0"} for t in timestamps]
    issues = validate_samples(samples, ["temp"])
    assert "sample_gaps" in _codes(issues)


def test_irregular_sampling_rate_detected():
    import random

    random.seed(0)
    t = 1700000000.0
    timestamps = []
    for _ in range(20):
        t += random.choice([0.5, 1.0, 8.0, 15.0])
        timestamps.append(t)
    samples = [{"timestamp": str(t), "temp": "20.0"} for t in timestamps]
    issues = validate_samples(samples, ["temp"])
    assert "irregular_sampling_rate" in _codes(issues)


def test_regular_sampling_rate_not_flagged():
    timestamps = [1700000000 + i * 2 for i in range(20)]
    samples = [{"timestamp": str(t), "temp": "20.0"} for t in timestamps]
    issues = validate_samples(samples, ["temp"])
    assert "irregular_sampling_rate" not in _codes(issues)


def test_nonnumeric_values_in_numeric_column_detected():
    samples = [
        {"timestamp": "1700000000", "temp": "20.0"},
        {"timestamp": "1700000002", "temp": "oops"},
        {"timestamp": "1700000004", "temp": "21.0"},
    ]
    issues = validate_samples(samples, ["temp"])
    assert "nonnumeric_values" in _codes(issues)


def test_implausible_temperature_detected():
    samples = [{"timestamp": str(1700000000 + i), "temp": "20.0"} for i in range(5)]
    samples.append({"timestamp": "1700000005", "temp": "99999.0"})
    issues = validate_samples(samples, ["temp"])
    assert "implausible_sensor_value" in _codes(issues)


def test_implausible_non_temperature_outlier_detected():
    samples = [{"timestamp": str(1700000000 + i), "pressure": "1.0"} for i in range(10)]
    samples.append({"timestamp": "1700000010", "pressure": "5000.0"})
    issues = validate_samples(samples, ["pressure"])
    assert "implausible_sensor_value" in _codes(issues)


def test_possible_unit_inconsistency_detected():
    # First half around 20-25 (Celsius-like), second half around 290-295 (Kelvin-like).
    samples = [{"timestamp": str(1700000000 + i), "temp": str(20.0 + i)} for i in range(10)]
    samples += [{"timestamp": str(1700000010 + i), "temp": str(290.0 + i)} for i in range(10)]
    issues = validate_samples(samples, ["temp"])
    assert "possible_unit_inconsistency" in _codes(issues)


def test_summarize_counts_errors_and_warnings_separately():
    issues = [
        {"severity": "error", "code": "a", "message": "m"},
        {"severity": "warning", "code": "b", "message": "m"},
        {"severity": "warning", "code": "c", "message": "m"},
    ]
    assert summarize(issues) == (1, 2)


def test_never_raises_on_malformed_input():
    # Rows missing keys entirely, wildly inconsistent shapes.
    samples = [{}, {"temp": None}, {"timestamp": ""}]
    issues = validate_samples(samples, ["temp"])
    assert isinstance(issues, list)
