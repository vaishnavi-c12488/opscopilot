from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from prometheus_client import Gauge, start_http_server


ROOT = Path(__file__).resolve().parents[1]

LABEL_DIR = ROOT / "evaluation" / "labeled_incidents"
LOG_FILE = ROOT / "data" / "processed" / "synthetic_benchmark_logs.jsonl"

LABEL_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


# ============================================================
# Prometheus metrics
# ============================================================

CPU = Gauge(
    "opscopilot_cpu_usage_percent",
    "Synthetic CPU usage percentage",
)

MEMORY = Gauge(
    "opscopilot_memory_usage_percent",
    "Synthetic memory usage percentage",
)

LATENCY = Gauge(
    "opscopilot_request_latency_seconds",
    "Synthetic request latency",
)

ERROR_RATE = Gauge(
    "opscopilot_error_rate_percent",
    "Synthetic error rate percentage",
)

DISK = Gauge(
    "opscopilot_disk_usage_percent",
    "Synthetic disk usage percentage",
)

NETWORK_ERRORS = Gauge(
    "opscopilot_network_error_rate_percent",
    "Synthetic network error rate",
)


# ============================================================
# Phase 8 scenarios
# ============================================================

SCENARIOS = [
    {
        "incident_id": "INC001",
        "incident_type": "synthetic_vm_operation_failure",
        "metric": "opscopilot_cpu_usage_percent",
        "affected_entity": "vm-eval-001",
        "keywords": ["VM operation", "failure"],
        "evidence": [
            "opscopilot_cpu_usage_percent",
            "VM operation",
            "ERROR",
        ],
        "messages": [
            "VM operation started",
            "VM operation encountered a failure",
            "VM operation failed",
            "VM operation retry failed",
            "VM operation terminated unexpectedly",
        ],
    },
    {
        "incident_id": "INC002",
        "incident_type": "memory_leak_oom",
        "metric": "opscopilot_memory_usage_percent",
        "affected_entity": "vm-eval-002",
        "keywords": ["memory", "OOM"],
        "evidence": [
            "opscopilot_memory_usage_percent",
            "memory",
            "OOM",
        ],
        "messages": [
            "Memory usage increasing steadily",
            "Memory pressure detected",
            "Available memory critically low",
            "Process terminated due to OOM",
            "Out of memory condition detected",
        ],
    },
    {
        "incident_id": "INC003",
        "incident_type": "bad_deployment_error_spike",
        "metric": "opscopilot_error_rate_percent",
        "affected_entity": "service-eval-003",
        "keywords": ["deployment", "error"],
        "evidence": [
            "opscopilot_error_rate_percent",
            "deployment",
            "ERROR",
        ],
        "messages": [
            "Deployment version v2.4.1 started",
            "Deployment completed successfully",
            "Application error rate increased",
            "HTTP 500 errors detected after deployment",
            "Service requests failing after deployment",
        ],
    },
    {
        "incident_id": "INC004",
        "incident_type": "latency_degradation",
        "metric": "opscopilot_request_latency_seconds",
        "affected_entity": "service-eval-004",
        "keywords": ["latency", "degradation"],
        "evidence": [
            "opscopilot_request_latency_seconds",
            "latency",
            "slow",
        ],
        "messages": [
            "Request latency beginning to increase",
            "Slow requests detected",
            "Request latency degradation observed",
            "Service response time exceeded threshold",
            "Requests experiencing severe latency",
        ],
    },
    {
        "incident_id": "INC005",
        "incident_type": "cascading_service_failure",
        "metric": "opscopilot_error_rate_percent",
        "affected_entity": "service-eval-005",
        "keywords": ["cascading", "service", "failure"],
        "evidence": [
            "opscopilot_error_rate_percent",
            "upstream",
            "downstream",
        ],
        "messages": [
            "Upstream service dependency degraded",
            "Upstream requests beginning to fail",
            "Downstream service errors increased",
            "Cascading service failure detected",
            "Multiple dependent services unavailable",
        ],
    },
    {
        "incident_id": "INC006",
        "incident_type": "cpu_saturation",
        "metric": "opscopilot_cpu_usage_percent",
        "affected_entity": "vm-eval-006",
        "keywords": ["CPU", "saturation"],
        "evidence": [
            "opscopilot_cpu_usage_percent",
            "CPU",
            "timeout",
        ],
        "messages": [
            "CPU utilization increasing",
            "CPU utilization exceeded safe threshold",
            "CPU saturation detected",
            "Request processing timeout observed",
            "High CPU causing request timeouts",
        ],
    },
    {
        "incident_id": "INC007",
        "incident_type": "storage_pressure",
        "metric": "opscopilot_disk_usage_percent",
        "affected_entity": "vm-eval-007",
        "keywords": ["disk", "storage"],
        "evidence": [
            "opscopilot_disk_usage_percent",
            "disk",
            "I/O",
        ],
        "messages": [
            "Disk utilization increasing",
            "Storage pressure detected",
            "Disk usage exceeded warning threshold",
            "Disk I/O errors detected",
            "Storage capacity critically low",
        ],
    },
    {
        "incident_id": "INC008",
        "incident_type": "network_connectivity_failure",
        "metric": "opscopilot_network_error_rate_percent",
        "affected_entity": "service-eval-008",
        "keywords": ["network", "connectivity", "failure"],
        "evidence": [
            "opscopilot_network_error_rate_percent",
            "connection",
            "network",
        ],
        "messages": [
            "Network connection errors increasing",
            "Connection attempts timing out",
            "Network connectivity degraded",
            "Service connection failure detected",
            "Multiple connection attempts failed",
        ],
    },
]


# ============================================================
# Metric generation
# ============================================================

def set_metrics(
    scenario_index: int,
    phase: str,
    step: int,
) -> None:

    normal_cpu = 40 + 5 * math.sin(step / 2)
    normal_memory = 50 + 3 * math.sin(step / 3)
    normal_latency = 0.20 + 0.03 * math.sin(step / 2)
    normal_errors = 1 + 0.2 * math.sin(step / 2)
    normal_disk = 45 + 2 * math.sin(step / 3)
    normal_network = 0.5 + 0.1 * math.sin(step / 2)

    if phase == "normal":

        CPU.set(normal_cpu)
        MEMORY.set(normal_memory)
        LATENCY.set(normal_latency)
        ERROR_RATE.set(normal_errors)
        DISK.set(normal_disk)
        NETWORK_ERRORS.set(normal_network)

        return

    if phase == "recovery":

        factor = max(
            0.0,
            1.0 - step / 8,
        )

        CPU.set(normal_cpu + 45 * factor)
        MEMORY.set(normal_memory + 35 * factor)
        LATENCY.set(normal_latency + 2.0 * factor)
        ERROR_RATE.set(normal_errors + 12 * factor)
        DISK.set(normal_disk + 45 * factor)
        NETWORK_ERRORS.set(normal_network + 15 * factor)

        return

    # Incident phase

    if scenario_index == 1:

        CPU.set(90 + step * 0.5)
        MEMORY.set(85 + step * 0.3)
        LATENCY.set(2 + step * 0.1)
        ERROR_RATE.set(10 + step * 0.5)

    elif scenario_index == 2:

        MEMORY.set(65 + step * 3.0)
        CPU.set(45 + step * 0.8)
        LATENCY.set(0.3 + step * 0.08)
        ERROR_RATE.set(2 + step * 0.5)

    elif scenario_index == 3:

        ERROR_RATE.set(15 + step * 1.5)
        CPU.set(55 + step * 1.2)
        MEMORY.set(55 + step * 0.4)
        LATENCY.set(0.5 + step * 0.12)

    elif scenario_index == 4:

        LATENCY.set(1.0 + step * 0.35)
        CPU.set(50 + step * 0.8)
        MEMORY.set(52 + step * 0.3)
        ERROR_RATE.set(2 + step * 0.4)

    elif scenario_index == 5:

        ERROR_RATE.set(8 + step * 1.4)
        LATENCY.set(1.0 + step * 0.15)
        CPU.set(55 + step * 1.0)
        MEMORY.set(60 + step * 0.5)

    elif scenario_index == 6:

        CPU.set(85 + step * 1.0)
        LATENCY.set(1.0 + step * 0.25)
        MEMORY.set(55 + step * 0.5)
        ERROR_RATE.set(3 + step * 0.8)

    elif scenario_index == 7:

        DISK.set(82 + step * 1.5)
        CPU.set(50 + step * 0.4)
        MEMORY.set(55 + step * 0.3)
        LATENCY.set(0.5 + step * 0.1)
        ERROR_RATE.set(2 + step * 0.3)

    elif scenario_index == 8:

        NETWORK_ERRORS.set(10 + step * 1.5)
        LATENCY.set(1.0 + step * 0.2)
        ERROR_RATE.set(8 + step * 0.8)
        CPU.set(50 + step * 0.5)
        MEMORY.set(55 + step * 0.3)


# ============================================================
# Synthetic log generation
# ============================================================

def create_logs(
    scenario: dict,
    start: datetime,
    end: datetime,
) -> list[dict]:

    records = []

    duration = (
        end - start
    ).total_seconds()

    messages = scenario["messages"]

    for index, message in enumerate(messages):

        offset = (
            duration
            * index
            / max(1, len(messages) - 1)
        )

        timestamp = (
            start.timestamp()
            + offset
        )

        event_time = datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc,
        )

        records.append(
            {
                "timestamp": event_time.isoformat(),
                "source": "openstack",
                "service": "synthetic-evaluation-service",
                "level": "ERROR",
                "entity_id": scenario["affected_entity"],
                "message": message,
                "incident_id": scenario["incident_id"],
                "synthetic": True,
            }
        )

    return records


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 60)
    print("OpsCopilot Phase 8 Benchmark Generator")
    print("=" * 60)

    print("\nStarting Prometheus metric server on port 8001...")

    start_http_server(8001)

    print("Generating 8 evaluation scenarios...")
    print("Normal -> Incident -> Recovery")

    all_logs = []
    labels = []

    normal_steps = 5
    incident_steps = 8
    recovery_steps = 5

    for scenario_index, scenario in enumerate(
        SCENARIOS,
        start=1,
    ):

        print()
        print(
            f"[{scenario['incident_id']}] "
            f"{scenario['incident_type']}"
        )

        # -------------------------
        # Normal baseline
        # -------------------------

        for step in range(normal_steps):

            set_metrics(
                scenario_index,
                "normal",
                step,
            )

            time.sleep(2)

        # -------------------------
        # Incident
        # -------------------------

        incident_start = datetime.now(
            timezone.utc
        )

        for step in range(incident_steps):

            set_metrics(
                scenario_index,
                "incident",
                step,
            )

            time.sleep(2)

        incident_end = datetime.now(
            timezone.utc
        )

        # -------------------------
        # Logs
        # -------------------------

        logs = create_logs(
            scenario,
            incident_start,
            incident_end,
        )

        all_logs.extend(logs)

        # -------------------------
        # Recovery
        # -------------------------

        for step in range(recovery_steps):

            set_metrics(
                scenario_index,
                "recovery",
                step,
            )

            time.sleep(2)

        # -------------------------
        # Ground truth
        # -------------------------

        label = {
            "incident_id": scenario["incident_id"],
            "status": "ready",
            "source": "openstack",
            "incident_type": scenario["incident_type"],
            "affected_entity": scenario["affected_entity"],
            "incident_start_time": incident_start.isoformat(),
            "incident_end_time": incident_end.isoformat(),
            "ground_truth": (
                f"{scenario['incident_type']} was "
                "intentionally introduced for evaluation."
            ),
            "expected_keywords": scenario["keywords"],
            "expected_evidence": scenario["evidence"],
            "metric_name": scenario["metric"],
            "log_query": " ".join(
                scenario["keywords"]
            ),
            "metric_source": "prometheus",
            "time_aligned": True,
            "metric_start_time": incident_start.isoformat(),
            "metric_end_time": incident_end.isoformat(),
            "synthetic_event_count": len(logs),
        }

        label_path = (
            LABEL_DIR
            / f"{scenario['incident_id']}.json"
        )

        with label_path.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                label,
                file,
                indent=4,
            )

        labels.append(label)

        print(
            f"  Start: {incident_start.isoformat()}"
        )

        print(
            f"  End:   {incident_end.isoformat()}"
        )

        print(
            f"  Label: {label_path}"
        )

    # ========================================================
    # Write combined logs
    # ========================================================

    with LOG_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:

        for record in all_logs:

            file.write(
                json.dumps(record)
                + "\n"
            )

    print()
    print("=" * 60)
    print("PHASE 8 BENCHMARK GENERATED")
    print("=" * 60)

    print(
        f"Scenarios generated: {len(labels)}"
    )

    print(
        f"Logs generated:      {len(all_logs)}"
    )

    print(
        f"Labels directory:    {LABEL_DIR}"
    )

    print(
        f"Logs file:           {LOG_FILE}"
    )

    print("\nGenerated incidents:")

    for label in labels:

        print(
            f"  {label['incident_id']} "
            f"-> {label['incident_type']}"
        )

    print()
    print(
        "Next: index synthetic_benchmark_logs.jsonl "
        "into Qdrant."
    )


if __name__ == "__main__":
    main()