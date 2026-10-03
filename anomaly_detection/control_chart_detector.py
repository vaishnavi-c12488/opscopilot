"""
OpsCopilot - Prometheus Control Chart Anomaly Detector

Phase 4:
Detect abnormal metric behavior from Prometheus using a statistical
control-chart approach.

The detector:
1. Retrieves a metric stream from Prometheus.
2. Finds a usable normal baseline.
3. Uses the normal baseline to calculate control limits.
4. Classifies subsequent observations as NORMAL or ANOMALY.
5. Creates an incident window when anomalous observations occur.
6. Reports the observed anomaly rate for the monitored stream.

Important:
- The baseline must represent normal behavior.
- A stale constant Prometheus prefix is skipped when detected.
- The detector does not claim that observed anomaly rate is a
  verified false-positive rate unless the evaluation stream is known
  to be normal.

This module is intentionally independent from the LLM agent.
"""

from __future__ import annotations

import argparse
import math
from datetime import datetime, timezone
from typing import Any

import requests


# ============================================================
# Configuration
# ============================================================

PROMETHEUS_URL = "http://localhost:9090"

DEFAULT_METRIC = "opscopilot_cpu_usage_percent"
DEFAULT_LOOKBACK_SECONDS = 600
DEFAULT_STEP_SECONDS = 2

DEFAULT_BASELINE_SIZE = 20
DEFAULT_SIGMA_MULTIPLIER = 3.0


# ============================================================
# Prometheus Retrieval
# ============================================================

def query_prometheus(
    metric_name: str,
    lookback_seconds: int = DEFAULT_LOOKBACK_SECONDS,
    step_seconds: int = DEFAULT_STEP_SECONDS,
) -> list[dict[str, float]]:
    """
    Retrieve a metric time series from Prometheus.

    Returns:
        [
            {
                "timestamp": <unix timestamp>,
                "value": <metric value>
            },
            ...
        ]
    """

    end_time = datetime.now(timezone.utc).timestamp()
    start_time = end_time - lookback_seconds

    url = f"{PROMETHEUS_URL}/api/v1/query_range"

    params = {
        "query": metric_name,
        "start": start_time,
        "end": end_time,
        "step": step_seconds,
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=10,
        )

        response.raise_for_status()
        payload = response.json()

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Unable to query Prometheus: {exc}"
        ) from exc

    if payload.get("status") != "success":
        raise RuntimeError(
            "Prometheus returned an unsuccessful response."
        )

    results = payload.get(
        "data",
        {},
    ).get(
        "result",
        [],
    )

    if not results:
        return []

    values: list[dict[str, float]] = []

    for series in results:

        for timestamp, value in series.get(
            "values",
            [],
        ):
            values.append(
                {
                    "timestamp": float(timestamp),
                    "value": float(value),
                }
            )

    values.sort(
        key=lambda item: item["timestamp"]
    )

    return values


# ============================================================
# Control Chart Calculation
# ============================================================

def calculate_control_limits(
    baseline_values: list[float],
    sigma_multiplier: float = DEFAULT_SIGMA_MULTIPLIER,
) -> dict[str, float]:
    """
    Calculate control-chart limits from a known normal baseline.

    Control limits:

        UCL = mean + k * standard_deviation
        LCL = mean - k * standard_deviation

    where k defaults to 3.

    Important:
        The baseline must represent normal behavior.
        It must NOT be taken from the current anomalous stream.
    """

    if len(baseline_values) < 2:
        raise ValueError(
            "At least two baseline observations are required."
        )

    if sigma_multiplier <= 0:
        raise ValueError(
            "sigma_multiplier must be greater than zero."
        )

    mean = sum(baseline_values) / len(
        baseline_values
    )

    variance = sum(
        (value - mean) ** 2
        for value in baseline_values
    ) / len(baseline_values)

    std_dev = math.sqrt(variance)

    upper_limit = (
        mean
        + sigma_multiplier * std_dev
    )

    lower_limit = (
        mean
        - sigma_multiplier * std_dev
    )

    return {
        "mean": mean,
        "std_dev": std_dev,
        "upper_limit": upper_limit,
        "lower_limit": lower_limit,
    }


# ============================================================
# Baseline Selection
# ============================================================

def find_normal_baseline(
    samples: list[dict[str, float]],
    baseline_size: int = DEFAULT_BASELINE_SIZE,
) -> tuple[int, list[dict[str, float]]]:
    """
    Find a usable normal baseline from a metric stream.

    Normal case:
        If the first baseline_size samples contain variation,
        they are used as the baseline.

    Stale-prefix case:
        If the first baseline_size samples are all the same value,
        they are treated as a stale/flat Prometheus prefix.

        The detector finds the end of that constant prefix and
        starts the baseline immediately afterward.

    Example:

        stale:
        44.82 44.82 44.82 ... 44.82
        --------------------------------
        normal:
        40.0 44.2 44.5 40.7 ...
        --------------------------------
        incident:
        90.0 90.5 91.0 ...

    With baseline_size=20:

        baseline_start_index = 20

    Returns:
        (
            baseline_start_index,
            baseline_samples
        )
    """

    if baseline_size < 2:
        raise ValueError(
            "baseline_size must be at least 2."
        )

    if len(samples) <= baseline_size:
        raise ValueError(
            f"Need more than {baseline_size} samples "
            "to find a baseline."
        )

    # --------------------------------------------------------
    # Step 1:
    # Examine the initial baseline window.
    # --------------------------------------------------------

    initial_window = samples[
        :baseline_size
    ]

    initial_values = [
        sample["value"]
        for sample in initial_window
    ]

    initial_min = min(initial_values)
    initial_max = max(initial_values)

    # --------------------------------------------------------
    # Step 2:
    # If the initial window already has variation,
    # use it directly.
    # --------------------------------------------------------

    if not math.isclose(
        initial_min,
        initial_max,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        return 0, initial_window

    # --------------------------------------------------------
    # Step 3:
    # Initial window is constant.
    #
    # Treat this as a possible stale Prometheus prefix.
    # Find exactly where that constant prefix ends.
    # --------------------------------------------------------

    constant_value = initial_values[0]

    prefix_end = 0

    for sample in samples:

        value = sample["value"]

        if math.isclose(
            value,
            constant_value,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            prefix_end += 1

        else:
            break

    # --------------------------------------------------------
    # Step 4:
    # Check whether a complete baseline exists after
    # the constant prefix.
    # --------------------------------------------------------

    if (
        prefix_end > 0
        and prefix_end + baseline_size
        <= len(samples)
    ):

        baseline_start = prefix_end

        baseline = samples[
            baseline_start:
            baseline_start + baseline_size
        ]

        return (
            baseline_start,
            baseline,
        )

    # --------------------------------------------------------
    # Step 5:
    # If there is not enough data after the prefix,
    # fall back to the initial window.
    #
    # This prevents the detector from inventing a baseline
    # when insufficient data is available.
    # --------------------------------------------------------

    return 0, initial_window


# ============================================================
# Single Observation Classification
# ============================================================

def classify_value(
    value: float,
    upper_limit: float,
    lower_limit: float,
) -> str:
    """
    Classify a metric value using the control limits.
    """

    if (
        value > upper_limit
        or value < lower_limit
    ):
        return "ANOMALY"

    return "NORMAL"


# ============================================================
# Stream Detection
# ============================================================

def detect_anomalies(
    samples: list[dict[str, float]],
    baseline_size: int = DEFAULT_BASELINE_SIZE,
    sigma_multiplier: float = DEFAULT_SIGMA_MULTIPLIER,
) -> dict[str, Any]:
    """
    Detect anomalies in a metric stream.

    The detector first identifies a normal baseline.

    If the stream begins with a stale constant prefix,
    that prefix is skipped.

    Detection begins only after the selected normal baseline.

    Returns:
        {
            "status": "success",
            "baseline_size": ...,
            "baseline_start_index": ...,
            "sigma_multiplier": ...,
            "baseline": {...},
            "observations": [...],
            "anomaly_count": ...,
            "observed_anomaly_rate": ...,
            "incident": {...} | None
        }
    """

    if baseline_size < 2:
        raise ValueError(
            "baseline_size must be at least 2."
        )

    if len(samples) <= baseline_size:
        raise ValueError(
            f"Need more than {baseline_size} samples "
            "to perform detection."
        )

    # --------------------------------------------------------
    # Find a valid normal baseline.
    # --------------------------------------------------------

    baseline_start_index, baseline_samples = (
        find_normal_baseline(
            samples=samples,
            baseline_size=baseline_size,
        )
    )

    # --------------------------------------------------------
    # Detection starts AFTER the selected baseline.
    # --------------------------------------------------------

    detection_start_index = (
        baseline_start_index
        + len(baseline_samples)
    )

    detection_samples = samples[
        detection_start_index:
    ]

    # --------------------------------------------------------
    # Calculate control limits.
    # --------------------------------------------------------

    baseline_values = [
        sample["value"]
        for sample in baseline_samples
    ]

    limits = calculate_control_limits(
        baseline_values,
        sigma_multiplier=sigma_multiplier,
    )

    # --------------------------------------------------------
    # Classify detection samples.
    # --------------------------------------------------------

    observations: list[dict[str, Any]] = []

    anomaly_samples: list[dict[str, Any]] = []

    for sample in detection_samples:

        classification = classify_value(
            value=sample["value"],
            upper_limit=limits["upper_limit"],
            lower_limit=limits["lower_limit"],
        )

        observation = {
            "timestamp": sample["timestamp"],
            "value": sample["value"],
            "status": classification,
        }

        observations.append(
            observation
        )

        if classification == "ANOMALY":
            anomaly_samples.append(
                observation
            )

    # --------------------------------------------------------
    # Observed anomaly rate
    #
    # This is intentionally NOT called a verified FPR.
    #
    # A false-positive rate requires a known-normal stream.
    # --------------------------------------------------------

    total_detection_samples = len(
        detection_samples
    )

    anomaly_count = len(
        anomaly_samples
    )

    observed_anomaly_rate = (
        anomaly_count
        / total_detection_samples
        if total_detection_samples > 0
        else 0.0
    )

    # --------------------------------------------------------
    # Build incident window.
    # --------------------------------------------------------

    incident = None

    if anomaly_samples:

        incident = {
            "incident_id": generate_incident_id(
                anomaly_samples[0]["timestamp"]
            ),
            "status": "ANOMALY_DETECTED",
            "start_time": timestamp_to_iso(
                anomaly_samples[0]["timestamp"]
            ),
            "end_time": timestamp_to_iso(
                anomaly_samples[-1]["timestamp"]
            ),
            "anomaly_count": len(
                anomaly_samples
            ),
            "trigger_value": (
                anomaly_samples[0]["value"]
            ),
            "peak_value": max(
                sample["value"]
                for sample in anomaly_samples
            ),
        }

    return {
        "status": "success",

        "baseline_size": len(
            baseline_samples
        ),

        "baseline_start_index": (
            baseline_start_index
        ),

        "detection_start_index": (
            detection_start_index
        ),

        "sigma_multiplier": (
            sigma_multiplier
        ),

        "baseline": {
            "sample_count": len(
                baseline_values
            ),
            **limits,
        },

        "observations": observations,

        "anomaly_count": anomaly_count,

        "observed_anomaly_rate": (
            observed_anomaly_rate
        ),

        "incident": incident,
    }


# ============================================================
# Helpers
# ============================================================

def timestamp_to_iso(
    timestamp: float,
) -> str:
    """
    Convert Unix timestamp to UTC ISO-8601 timestamp.
    """

    return datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc,
    ).isoformat()


def generate_incident_id(
    timestamp: float,
) -> str:
    """
    Generate a deterministic incident ID
    based on detection time.
    """

    dt = datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc,
    )

    return (
        f"DET-"
        f"{dt.strftime('%Y%m%d-%H%M%S')}"
    )


# ============================================================
# Console Output
# ============================================================

def print_detection_report(
    metric_name: str,
    result: dict[str, Any],
) -> None:
    """
    Print a readable detector report.
    """

    baseline = result["baseline"]

    print()
    print("=" * 60)
    print(
        "OpsCopilot Prometheus Anomaly Detector"
    )
    print("=" * 60)

    print(
        f"Metric: {metric_name}"
    )

    print(
        f"Baseline start index: "
        f"{result['baseline_start_index']}"
    )

    print(
        f"Baseline samples: "
        f"{result['baseline_size']}"
    )

    print(
        f"Detection start index: "
        f"{result['detection_start_index']}"
    )

    print(
        f"Sigma multiplier: "
        f"{result['sigma_multiplier']}"
    )

    print()
    print("Control Chart")
    print("-" * 60)

    print(
        f"Mean:          "
        f"{baseline['mean']:.4f}"
    )

    print(
        f"Std deviation: "
        f"{baseline['std_dev']:.4f}"
    )

    print(
        f"Upper limit:   "
        f"{baseline['upper_limit']:.4f}"
    )

    print(
        f"Lower limit:   "
        f"{baseline['lower_limit']:.4f}"
    )

    print()
    print("Metric Stream Detection")
    print("-" * 60)

    for observation in result[
        "observations"
    ]:

        timestamp = timestamp_to_iso(
            observation["timestamp"]
        )

        print(
            f"{timestamp} | "
            f"Value={observation['value']:.2f} | "
            f"{observation['status']}"
        )

    print()
    print("Detection Summary")
    print("-" * 60)

    print(
        f"Detection samples: "
        f"{len(result['observations'])}"
    )

    print(
        f"Anomalies detected: "
        f"{result['anomaly_count']}"
    )

    print(
        f"Observed anomaly rate: "
        f"{result['observed_anomaly_rate']:.2%}"
    )

    if result["incident"]:

        incident = result["incident"]

        print()
        print("Incident Created")
        print("-" * 60)

        print(
            f"Incident ID: "
            f"{incident['incident_id']}"
        )

        print(
            f"Start: "
            f"{incident['start_time']}"
        )

        print(
            f"End: "
            f"{incident['end_time']}"
        )

        print(
            f"Trigger value: "
            f"{incident['trigger_value']:.2f}"
        )

        print(
            f"Peak value: "
            f"{incident['peak_value']:.2f}"
        )

    else:

        print()
        print(
            "No anomaly detected."
        )


# ============================================================
# Main
# ============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "OpsCopilot Prometheus "
            "control-chart anomaly detector"
        )
    )

    parser.add_argument(
        "--metric",
        default=DEFAULT_METRIC,
        help="Prometheus metric name",
    )

    parser.add_argument(
        "--lookback",
        type=int,
        default=DEFAULT_LOOKBACK_SECONDS,
        help="Prometheus lookback period in seconds",
    )

    parser.add_argument(
        "--step",
        type=int,
        default=DEFAULT_STEP_SECONDS,
        help="Prometheus query step in seconds",
    )

    parser.add_argument(
        "--baseline-size",
        type=int,
        default=DEFAULT_BASELINE_SIZE,
        help="Number of normal baseline samples",
    )

    parser.add_argument(
        "--sigma",
        type=float,
        default=DEFAULT_SIGMA_MULTIPLIER,
        help="Control-chart sigma multiplier",
    )

    args = parser.parse_args()

    print()
    print("=" * 60)
    print(
        "OpsCopilot Prometheus Anomaly Detector"
    )
    print("=" * 60)

    print()
    print(
        f"Prometheus: "
        f"{PROMETHEUS_URL}"
    )

    print(
        f"Metric: "
        f"{args.metric}"
    )

    print(
        f"Lookback: "
        f"{args.lookback} seconds"
    )

    print(
        f"Baseline size: "
        f"{args.baseline_size} samples"
    )

    print()
    print(
        "Querying Prometheus..."
    )

    samples = query_prometheus(
        metric_name=args.metric,
        lookback_seconds=args.lookback,
        step_seconds=args.step,
    )

    print(
        f"Samples received: "
        f"{len(samples)}"
    )

    if not samples:

        print()
        print(
            "No metric samples found."
        )

        return

    result = detect_anomalies(
        samples=samples,
        baseline_size=args.baseline_size,
        sigma_multiplier=args.sigma,
    )

    print_detection_report(
        metric_name=args.metric,
        result=result,
    )


if __name__ == "__main__":
    main()