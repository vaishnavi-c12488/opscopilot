import time
import math
from datetime import datetime, timezone

from prometheus_client import Gauge, start_http_server


# =========================================================
# Configuration
# =========================================================

METRICS_PORT = 8001

NORMAL_SAMPLES = 20
INCIDENT_SAMPLES = 10
RECOVERY_SAMPLES = 20

SAMPLE_INTERVAL = 2


# =========================================================
# Prometheus Metrics
# =========================================================

cpu_usage = Gauge(
    "opscopilot_cpu_usage_percent",
    "Synthetic CPU usage percentage"
)

memory_usage = Gauge(
    "opscopilot_memory_usage_percent",
    "Synthetic memory usage percentage"
)

request_latency = Gauge(
    "opscopilot_request_latency_seconds",
    "Synthetic request latency in seconds"
)

error_rate = Gauge(
    "opscopilot_error_rate_percent",
    "Synthetic error rate percentage"
)


# =========================================================
# Normal Metrics
# =========================================================

def generate_normal_metrics(sample_number):
    """
    Generate normal system behavior.
    """

    cpu = 40 + 5 * math.sin(sample_number)

    memory = 50 + 3 * math.sin(sample_number / 2)

    latency = 0.20 + 0.03 * math.sin(sample_number)

    errors = 1 + 0.2 * math.sin(sample_number)

    return cpu, memory, latency, errors


# =========================================================
# Incident Metrics
# =========================================================

def generate_incident_metrics(sample_number):
    """
    Generate abnormal metric behavior during
    the synthetic incident.
    """

    cpu = 90 + sample_number * 0.5

    memory = 85 + sample_number * 0.3

    latency = 2.0 + sample_number * 0.1

    errors = 10 + sample_number * 0.5

    return cpu, memory, latency, errors


# =========================================================
# Update Prometheus Metrics
# =========================================================

def update_metrics(cpu, memory, latency, errors):
    """
    Update Prometheus metric values.
    """

    cpu_usage.set(cpu)
    memory_usage.set(memory)
    request_latency.set(latency)
    error_rate.set(errors)


# =========================================================
# Start Metric Server
# =========================================================

def start_metric_server():
    """
    Start the HTTP server that Prometheus scrapes.
    """

    start_http_server(METRICS_PORT)

    print(
        f"Prometheus metrics available at "
        f"http://localhost:{METRICS_PORT}/metrics"
    )


# =========================================================
# Normal Metric Period
# =========================================================

def run_normal_period():
    """
    Generate the normal baseline before an incident.
    """

    print("\nGenerating normal metric baseline...")

    for i in range(NORMAL_SAMPLES):

        cpu, memory, latency, errors = (
            generate_normal_metrics(i)
        )

        update_metrics(
            cpu,
            memory,
            latency,
            errors
        )

        print(
            f"[NORMAL] "
            f"CPU={cpu:.2f}% | "
            f"Memory={memory:.2f}% | "
            f"Latency={latency:.2f}s | "
            f"Errors={errors:.2f}%"
        )

        time.sleep(SAMPLE_INTERVAL)


# =========================================================
# Incident Metric Period
# =========================================================

def run_incident_period(incident_id):
    """
    Generate the metric spike for a synthetic incident.

    The returned start and end times represent the
    actual runtime window of the metric incident.
    """

    metric_start_time = datetime.now(
        timezone.utc
    )

    print()

    print(
        f"Synthetic metric incident started: "
        f"{incident_id}"
    )

    print(
        f"Metric incident start time: "
        f"{metric_start_time.isoformat()}"
    )

    for i in range(INCIDENT_SAMPLES):

        cpu, memory, latency, errors = (
            generate_incident_metrics(i)
        )

        update_metrics(
            cpu,
            memory,
            latency,
            errors
        )

        print(
            f"[{incident_id}] "
            f"[INCIDENT] "
            f"CPU={cpu:.2f}% | "
            f"Memory={memory:.2f}% | "
            f"Latency={latency:.2f}s | "
            f"Errors={errors:.2f}%"
        )

        time.sleep(SAMPLE_INTERVAL)

    metric_end_time = datetime.now(
        timezone.utc
    )

    print(
        f"Synthetic metric incident completed: "
        f"{incident_id}"
    )

    print(
        f"Metric incident end time: "
        f"{metric_end_time.isoformat()}"
    )

    return {
        "incident_id": incident_id,
        "metric_start_time":
            metric_start_time.isoformat(),
        "metric_end_time":
            metric_end_time.isoformat()
    }


# =========================================================
# Recovery / Return to Normal
# =========================================================

def run_recovery_period():
    """
    Return the system metrics to normal behavior
    after the synthetic incident.
    """

    print(
        "\nReturning metrics to normal behavior..."
    )

    for i in range(RECOVERY_SAMPLES):

        cpu, memory, latency, errors = (
            generate_normal_metrics(
                NORMAL_SAMPLES + i
            )
        )

        update_metrics(
            cpu,
            memory,
            latency,
            errors
        )

        print(
            f"[RECOVERY] "
            f"CPU={cpu:.2f}% | "
            f"Memory={memory:.2f}% | "
            f"Latency={latency:.2f}s | "
            f"Errors={errors:.2f}%"
        )

        time.sleep(SAMPLE_INTERVAL)

    print(
        "Metric recovery completed."
    )


# =========================================================
# Standalone Mode
# =========================================================

def main():

    print(
        "Starting OpsCopilot metric feeder..."
    )

    start_metric_server()

    # -----------------------------------------------------
    # 1. Normal baseline
    # -----------------------------------------------------

    run_normal_period()

    # -----------------------------------------------------
    # 2. Synthetic incident
    # -----------------------------------------------------

    run_incident_period("INC001")

    # -----------------------------------------------------
    # 3. Return to normal behavior
    # -----------------------------------------------------

    run_recovery_period()

    print(
        "\nMetric feeder completed."
    )

    print(
        "Keeping Prometheus metric server alive..."
    )

    try:

        while True:
            time.sleep(60)

    except KeyboardInterrupt:

        print(
            "\nMetric feeder stopped."
        )


# =========================================================
# Program Entry Point
# =========================================================

if __name__ == "__main__":
    main()