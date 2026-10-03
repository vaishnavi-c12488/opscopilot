import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ingestion.metric_feeder import (
    start_metric_server,
    run_normal_period,
    run_incident_period,
    run_recovery_period
)


# =========================================================
# Configuration
# =========================================================

INPUT_FILE = Path(
    "data/processed/openstack_logs.jsonl"
)

OUTPUT_LOG_FILE = Path(
    "data/processed/synthetic_openstack_incident.jsonl"
)

OUTPUT_LABEL_FILE = Path(
    "data/processed/synthetic_incidents.json"
)

INCIDENT_ID = "INC001"

# Number of real records used as surrounding context
WINDOW_SIZE = 50


# =========================================================
# Load JSONL Logs
# =========================================================

def load_jsonl(file_path):
    """
    Load structured JSON records from a JSONL file.
    """

    records = []

    with file_path.open(
        "r",
        encoding="utf-8"
    ) as file:

        for line in file:

            line = line.strip()

            if line:

                records.append(
                    json.loads(line)
                )

    return records


# =========================================================
# Find VM Record
# =========================================================

def find_vm_record(records):
    """
    Find the first OpenStack record containing
    a real VM instance ID.
    """

    for record in records:

        entity_id = record.get(
            "entity_id"
        )

        if entity_id:

            return record

    return None


# =========================================================
# Create Incident Log Context
# =========================================================

def create_incident_context(
    records,
    incident_start_time,
    incident_end_time
):
    """
    Create a controlled incident using a real OpenStack
    VM record and synthetic incident events.

    The synthetic incident events are explicitly placed
    inside the same time window as the Prometheus
    metric incident.
    """

    # -----------------------------------------------------
    # Find a real VM-related record
    # -----------------------------------------------------

    target_record = find_vm_record(
        records
    )

    if target_record is None:

        raise ValueError(
            "No OpenStack record containing "
            "a VM instance ID was found."
        )

    target_vm = target_record[
        "entity_id"
    ]

    target_index = records.index(
        target_record
    )

    # -----------------------------------------------------
    # Select surrounding real records
    # -----------------------------------------------------

    start_index = max(
        0,
        target_index - WINDOW_SIZE
    )

    end_index = min(
        len(records),
        target_index + WINDOW_SIZE + 1
    )

    context_records = records[
        start_index:end_index
    ].copy()

    # -----------------------------------------------------
    # Keep the real log context
    #
    # We preserve the original timestamp and add
    # incident metadata. These records are context,
    # not synthetic anomaly events.
    # -----------------------------------------------------

    incident_records = []

    for record in context_records:

        updated_record = record.copy()

        updated_record[
            "original_timestamp"
        ] = record.get(
            "timestamp"
        )

        updated_record[
            "incident_id"
        ] = INCIDENT_ID

        updated_record[
            "synthetic"
        ] = False

        incident_records.append(
            updated_record
        )

    # -----------------------------------------------------
    # Synthetic incident messages
    # -----------------------------------------------------

    messages = [

        "SYNTHETIC INCIDENT: VM operation started",

        "SYNTHETIC INCIDENT: VM operation encountered a failure",

        "SYNTHETIC INCIDENT: VM operation failed",

        "SYNTHETIC INCIDENT: VM operation retry failed",

        "SYNTHETIC INCIDENT: VM operation terminated unexpectedly"

    ]

    synthetic_events = []

    # -----------------------------------------------------
    # Create synthetic events INSIDE the metric window
    #
    # The five events are distributed across the
    # incident duration.
    # -----------------------------------------------------

    incident_duration = (
        incident_end_time
        - incident_start_time
    )

    if len(messages) == 1:

        event_offsets = [0]

    else:

        interval = (
            incident_duration.total_seconds()
            / (len(messages) - 1)
        )

        event_offsets = [
            interval * index
            for index in range(
                len(messages)
            )
        ]

    for message, offset in zip(
        messages,
        event_offsets
    ):

        event = target_record.copy()

        # Preserve original LogHub timestamp
        event[
            "original_timestamp"
        ] = target_record.get(
            "timestamp"
        )

        # Put synthetic event inside
        # the Prometheus incident window
        event_time = (
            incident_start_time
            + timedelta(
                seconds=offset
            )
        )

        event[
            "timestamp"
        ] = event_time.isoformat()

        # Synthetic incident information
        event[
            "level"
        ] = "ERROR"

        event[
            "entity_id"
        ] = target_vm

        event[
            "message"
        ] = message

        # Not an HTTP response
        event[
            "status"
        ] = None

        event[
            "response_time"
        ] = None

        # Synthetic metadata
        event[
            "synthetic"
        ] = True

        event[
            "incident_id"
        ] = INCIDENT_ID

        synthetic_events.append(
            event
        )

    # -----------------------------------------------------
    # Add synthetic events
    # -----------------------------------------------------

    incident_records.extend(
        synthetic_events
    )

    # -----------------------------------------------------
    # Ground Truth
    # -----------------------------------------------------

    ground_truth = {

        "incident_id":
            INCIDENT_ID,

        "source":
            "openstack",

        "incident_type":
            "synthetic_vm_operation_failure",

        "affected_entity":
            target_vm,

        "incident_start_time":
            incident_start_time.isoformat(),

        "incident_end_time":
            incident_end_time.isoformat(),

        "ground_truth":
            (
                "A synthetic VM operation failure "
                "was intentionally introduced for "
                "evaluation."
            ),

        "synthetic_event_count":
            len(synthetic_events),

        "metric_source":
            "prometheus",

        "time_aligned":
            True
    }

    return (
        incident_records,
        ground_truth
    )


# =========================================================
# Write JSONL
# =========================================================

def write_jsonl(
    records,
    file_path
):
    """
    Save records in JSON Lines format.
    """

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with file_path.open(
        "w",
        encoding="utf-8"
    ) as file:

        for record in records:

            file.write(
                json.dumps(record)
                + "\n"
            )


# =========================================================
# Write Ground Truth
# =========================================================

def write_ground_truth(
    ground_truth,
    file_path
):
    """
    Save synthetic incident ground truth.
    """

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with file_path.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            ground_truth,
            file,
            indent=4
        )


# =========================================================
# Main
# =========================================================

def main():

    print(
        "=========================================="
    )

    print(
        "OpsCopilot Synthetic Incident Injector"
    )

    print(
        "=========================================="
    )

    # -----------------------------------------------------
    # Start Prometheus metric server
    # -----------------------------------------------------

    print(
        "\nStarting Prometheus metric server..."
    )

    start_metric_server()

    # -----------------------------------------------------
    # Generate normal baseline
    # -----------------------------------------------------

    print(
        "\nCreating normal metric baseline..."
    )

    run_normal_period()

    # -----------------------------------------------------
    # Load OpenStack logs
    # -----------------------------------------------------

    print(
        "\nLoading OpenStack logs..."
    )

    records = load_jsonl(
        INPUT_FILE
    )

    print(
        f"Records loaded: {len(records)}"
    )

    # -----------------------------------------------------
    # Start the metric incident FIRST
    #
    # This gives us the actual Prometheus incident
    # start/end timestamps.
    # -----------------------------------------------------

    print(
        "\nStarting corresponding "
        "Prometheus metric incident..."
    )

    metric_result = run_incident_period(
        INCIDENT_ID
    )

    metric_start_time = datetime.fromisoformat(
        metric_result[
            "metric_start_time"
        ]
    )

    metric_end_time = datetime.fromisoformat(
        metric_result[
            "metric_end_time"
        ]
    )

    # -----------------------------------------------------
    # Create logs using the EXACT SAME window
    # -----------------------------------------------------

    print(
        "\nCreating synthetic log incident..."
    )

    (
        incident_records,
        ground_truth
    ) = create_incident_context(
        records,
        metric_start_time,
        metric_end_time
    )

    print(
        f"Incident ID: "
        f"{ground_truth['incident_id']}"
    )

    print(
        f"Selected VM: "
        f"{ground_truth['affected_entity']}"
    )

    print(
        f"Incident start: "
        f"{ground_truth['incident_start_time']}"
    )

    print(
        f"Incident end: "
        f"{ground_truth['incident_end_time']}"
    )

    # -----------------------------------------------------
    # Save incident logs
    # -----------------------------------------------------

    write_jsonl(
        incident_records,
        OUTPUT_LOG_FILE
    )

    print(
        "\nIncident logs written to:"
    )

    print(
        OUTPUT_LOG_FILE
    )

    # -----------------------------------------------------
    # Add metric timestamps to ground truth
    # -----------------------------------------------------

    ground_truth[
        "metric_start_time"
    ] = metric_result[
        "metric_start_time"
    ]

    ground_truth[
        "metric_end_time"
    ] = metric_result[
        "metric_end_time"
    ]

    # -----------------------------------------------------
    # Save ground truth
    # -----------------------------------------------------

    write_ground_truth(
        ground_truth,
        OUTPUT_LABEL_FILE
    )

    print(
        "\nGround truth written to:"
    )

    print(
        OUTPUT_LABEL_FILE
    )

    # -----------------------------------------------------
    # Verification
    # -----------------------------------------------------

    print(
        "\n=========================================="
    )

    print(
        "TIME ALIGNMENT CHECK"
    )

    print(
        "=========================================="
    )

    print(
        f"Metric start : "
        f"{ground_truth['metric_start_time']}"
    )

    print(
        f"Metric end   : "
        f"{ground_truth['metric_end_time']}"
    )

    print(
        f"Log window   : "
        f"{ground_truth['incident_start_time']}"
        f" → "
        f"{ground_truth['incident_end_time']}"
    )

    print(
        "\nLogs + metrics belong to the same "
        "INC001 time window."
    )

    # -----------------------------------------------------
    # Return metrics to normal behavior
    # -----------------------------------------------------

    print(
        "\n=========================================="
    )

    print(
        "Starting metric recovery period..."
    )

    print(
        "=========================================="
    )

    run_recovery_period()

    print(
        "\nMetric system returned to normal."
    )

    # -----------------------------------------------------
    # Keep Prometheus server alive
    # -----------------------------------------------------

    print(
        "\n=========================================="
    )

    print(
        "Synthetic incident completed."
    )

    print(
        "=========================================="
    )

    print(
        f"Incident ID: {INCIDENT_ID}"
    )

    print(
        f"Incident logs: "
        f"{OUTPUT_LOG_FILE}"
    )

    print(
        f"Ground truth: "
        f"{OUTPUT_LABEL_FILE}"
    )

    print(
        "\nKeeping Prometheus server alive..."
    )

    try:

        while True:
            time.sleep(60)

    except KeyboardInterrupt:

        print(
            "\nOpsCopilot incident injector stopped."
        )


# =========================================================
# Program Entry Point
# =========================================================

if __name__ == "__main__":
    main()