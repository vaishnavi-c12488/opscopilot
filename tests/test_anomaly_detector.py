import pytest

from anomaly_detection.control_chart_detector import (
    calculate_control_limits,
    classify_value,
    detect_anomalies,
    find_normal_baseline,
)


def test_control_limits_are_based_on_normal_baseline():
    baseline = [
        40.0,
        41.0,
        39.0,
        40.5,
        41.5,
        40.2,
        39.8,
        40.7,
        41.1,
        39.9,
    ]

    limits = calculate_control_limits(
        baseline,
        sigma_multiplier=3.0,
    )

    assert limits["mean"] == pytest.approx(40.37)
    assert limits["std_dev"] > 0
    assert limits["upper_limit"] > limits["mean"]
    assert limits["lower_limit"] < limits["mean"]


def test_normal_value_is_not_anomaly():
    baseline = [
        40,
        41,
        39,
        40,
        41,
        40,
        39,
        40,
        41,
        40,
    ]

    limits = calculate_control_limits(baseline)

    result = classify_value(
        value=40.5,
        upper_limit=limits["upper_limit"],
        lower_limit=limits["lower_limit"],
    )

    assert result == "NORMAL"


def test_large_metric_spike_is_anomaly():
    baseline = [
        40,
        41,
        39,
        40,
        41,
        40,
        39,
        40,
        41,
        40,
    ]

    limits = calculate_control_limits(baseline)

    result = classify_value(
        value=90,
        upper_limit=limits["upper_limit"],
        lower_limit=limits["lower_limit"],
    )

    assert result == "ANOMALY"


def test_detector_detects_synthetic_spike():
    samples = []

    normal_values = [
        40.0,
        41.0,
        42.0,
        39.0,
        40.5,
        41.5,
        39.5,
        40.5,
        41.0,
        40.0,
    ]

    for index, value in enumerate(normal_values):
        samples.append(
            {
                "timestamp": float(index),
                "value": value,
            }
        )

    incident_values = [
        90.0,
        90.5,
        91.0,
        91.5,
        92.0,
        92.5,
        93.0,
        93.5,
        94.0,
        94.5,
    ]

    for index, value in enumerate(incident_values, start=10):
        samples.append(
            {
                "timestamp": float(index),
                "value": value,
            }
        )

    result = detect_anomalies(
        samples=samples,
        baseline_size=10,
        sigma_multiplier=3.0,
    )

    assert result["status"] == "success"
    assert result["anomaly_count"] == 10
    assert result["incident"] is not None
    assert result["incident"]["status"] == "ANOMALY_DETECTED"
    assert result["incident"]["peak_value"] == 94.5


def test_normal_stream_has_no_false_positives():
    samples = []

    normal_values = [
        40.0,
        41.0,
        42.0,
        39.0,
        40.5,
        41.5,
        39.5,
        40.5,
        41.0,
        40.0,
        40.5,
        41.0,
        39.5,
        40.0,
        41.5,
        40.5,
        39.5,
        40.0,
        41.0,
        40.5,
    ]

    for index, value in enumerate(normal_values):
        samples.append(
            {
                "timestamp": float(index),
                "value": value,
            }
        )

    result = detect_anomalies(
        samples=samples,
        baseline_size=10,
        sigma_multiplier=3.0,
    )

    assert result["anomaly_count"] == 0
    assert result["incident"] is None
    assert result["observed_anomaly_rate"] == 0.0


def test_baseline_skips_stale_constant_prefix():
    samples = []

    # Simulate old/stale Prometheus gauge data.
    for index in range(20):
        samples.append(
            {
                "timestamp": float(index),
                "value": 44.81897693142044,
            }
        )

    # Current normal behavior.
    normal_values = [
        40.0,
        44.21,
        44.55,
        40.71,
        36.22,
        35.21,
        38.60,
        43.28,
        44.95,
        42.06,
        37.28,
        35.00,
        37.32,
        42.10,
        44.95,
        43.25,
        38.56,
        35.19,
        36.25,
        40.75,
    ]

    for index, value in enumerate(normal_values, start=20):
        samples.append(
            {
                "timestamp": float(index),
                "value": value,
            }
        )

    # Synthetic incident.
    incident_values = [
        90.0,
        90.5,
        91.0,
        91.5,
        92.0,
        92.5,
        93.0,
        93.5,
        94.0,
        94.5,
    ]

    for index, value in enumerate(incident_values, start=40):
        samples.append(
            {
                "timestamp": float(index),
                "value": value,
            }
        )

    baseline_start, baseline = find_normal_baseline(
        samples=samples,
        baseline_size=20,
    )

    assert baseline_start == 20
    assert baseline[0]["value"] == 40.0
    assert baseline[-1]["value"] == 40.75


def test_stale_prefix_does_not_create_false_positives():
    samples = []

    # Old constant Prometheus value.
    for index in range(20):
        samples.append(
            {
                "timestamp": float(index),
                "value": 44.81897693142044,
            }
        )

    # Twenty normal observations.
    normal_values = [
        40.0,
        44.21,
        44.55,
        40.71,
        36.22,
        35.21,
        38.60,
        43.28,
        44.95,
        42.06,
        37.28,
        35.00,
        37.32,
        42.10,
        44.95,
        43.25,
        38.56,
        35.19,
        36.25,
        40.75,
    ]

    for index, value in enumerate(normal_values, start=20):
        samples.append(
            {
                "timestamp": float(index),
                "value": value,
            }
        )

    # Incident spike.
    incident_values = [
        90.0,
        90.5,
        91.0,
        91.5,
        92.0,
        92.5,
        93.0,
        93.5,
        94.0,
        94.5,
    ]

    for index, value in enumerate(incident_values, start=40):
        samples.append(
            {
                "timestamp": float(index),
                "value": value,
            }
        )

    result = detect_anomalies(
        samples=samples,
        baseline_size=20,
        sigma_multiplier=3.0,
    )

    # The 20 normal observations should not be part of detection.
    assert result["baseline_start_index"] == 20

    # All ten synthetic spike observations should be detected.
    assert result["anomaly_count"] == 10
    assert result["incident"] is not None
    assert result["incident"]["peak_value"] == 94.5