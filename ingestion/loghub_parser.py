from pathlib import Path
import json
import re
from typing import Dict, Iterator, Optional


# ---------------------------------------------------------
# Regular expressions for the actual LogHub formats
# ---------------------------------------------------------

# HDFS example:
# 081109 203518 143 INFO dfs.DataNode$DataXceiver:
# Receiving block blk_-1608999687919862906 ...
HDFS_PATTERN = re.compile(
    r"^(?P<date>\d{6})\s+"
    r"(?P<time>\d{6})\s+"
    r"(?P<pid>\d+)\s+"
    r"(?P<level>\w+)\s+"
    r"(?P<component>[^:]+):\s*"
    r"(?P<message>.*)$"
)

# OpenStack example:
# nova-api.log... 2017-05-14 19:39:01.445 25746 INFO
# nova.osapi_compute.wsgi.server [...] ...
OPENSTACK_PATTERN = re.compile(
    r"^(?P<log_file>\S+)\s+"
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+"
    r"(?P<pid>\d+)\s+"
    r"(?P<level>\w+)\s+"
    r"(?P<service>\S+)\s+"
    r"(?P<message>.*)$"
)

# HDFS block ID
BLOCK_ID_PATTERN = re.compile(r"\b(blk_-?\d+)\b")

# OpenStack VM instance ID
INSTANCE_ID_PATTERN = re.compile(
    r"\[instance:\s*([0-9a-fA-F-]{36})\]"
)

# OpenStack HTTP status
STATUS_PATTERN = re.compile(r"\bstatus:\s*(\d+)\b")

# OpenStack request duration
TIME_PATTERN = re.compile(r"\btime:\s*([0-9.]+)\b")


# ---------------------------------------------------------
# HDFS parser
# ---------------------------------------------------------

def parse_hdfs_line(line: str) -> Optional[Dict]:
    """
    Parse one HDFS log line into a structured dictionary.
    """

    line = line.strip()

    if not line:
        return None

    match = HDFS_PATTERN.match(line)

    if not match:
        return None

    data = match.groupdict()

    block_match = BLOCK_ID_PATTERN.search(data["message"])

    block_id = block_match.group(1) if block_match else None

    return {
        "source": "hdfs",
        "timestamp": f'{data["date"]} {data["time"]}',
        "log_file": "HDFS.log",
        "pid": int(data["pid"]),
        "level": data["level"],
        "service": data["component"],
        "entity_id": block_id,
        "message": data["message"],
    }


# ---------------------------------------------------------
# OpenStack parser
# ---------------------------------------------------------

def parse_openstack_line(line: str) -> Optional[Dict]:
    """
    Parse one OpenStack log line into a structured dictionary.
    """

    line = line.strip()

    if not line:
        return None

    match = OPENSTACK_PATTERN.match(line)

    if not match:
        return None

    data = match.groupdict()

    instance_match = INSTANCE_ID_PATTERN.search(data["message"])
    status_match = STATUS_PATTERN.search(data["message"])
    time_match = TIME_PATTERN.search(data["message"])

    instance_id = (
        instance_match.group(1)
        if instance_match
        else None
    )

    status = (
        int(status_match.group(1))
        if status_match
        else None
    )

    response_time = (
        float(time_match.group(1))
        if time_match
        else None
    )

    return {
        "source": "openstack",
        "timestamp": data["timestamp"],
        "log_file": data["log_file"],
        "pid": int(data["pid"]),
        "level": data["level"],
        "service": data["service"],
        "entity_id": instance_id,
        "message": data["message"],
        "status": status,
        "response_time": response_time,
    }


# ---------------------------------------------------------
# Generic file parser
# ---------------------------------------------------------

def parse_log_file(
    input_path: Path,
    parser_function
) -> Iterator[Dict]:
    """
    Read a log file line by line and yield structured records.
    """

    with input_path.open(
        "r",
        encoding="utf-8",
        errors="replace"
    ) as file:

        for line_number, line in enumerate(file, start=1):

            record = parser_function(line)

            if record is not None:
                record["line_number"] = line_number
                yield record


# ---------------------------------------------------------
# Write structured logs as JSONL
# ---------------------------------------------------------

def write_jsonl(
    records: Iterator[Dict],
    output_path: Path
) -> int:
    """
    Write records one by one to a JSONL file.
    Returns the number of successfully parsed records.
    """

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    count = 0

    with output_path.open(
        "w",
        encoding="utf-8"
    ) as output_file:

        for record in records:

            output_file.write(
                json.dumps(record) + "\n"
            )

            count += 1

    return count


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main() -> None:

    project_root = Path(__file__).resolve().parent.parent

    # HDFS
    hdfs_input = (
        project_root
        / "data"
        / "raw"
        / "hdfs"
        / "HDFS.log"
    )

    hdfs_output = (
        project_root
        / "data"
        / "processed"
        / "hdfs_logs.jsonl"
    )

    # OpenStack abnormal logs
    openstack_input = (
        project_root
        / "data"
        / "raw"
        / "openstack"
        / "openstack_abnormal.log"
    )

    openstack_output = (
        project_root
        / "data"
        / "processed"
        / "openstack_logs.jsonl"
    )

    # Parse HDFS
    print("Parsing HDFS logs...")

    hdfs_count = write_jsonl(
        parse_log_file(
            hdfs_input,
            parse_hdfs_line
        ),
        hdfs_output
    )

    print(
        f"HDFS records written: {hdfs_count}"
    )
    print(
        f"Output: {hdfs_output}"
    )

    # Parse OpenStack
    print("\nParsing OpenStack logs...")

    openstack_count = write_jsonl(
        parse_log_file(
            openstack_input,
            parse_openstack_line
        ),
        openstack_output
    )

    print(
        f"OpenStack records written: {openstack_count}"
    )
    print(
        f"Output: {openstack_output}"
    )


if __name__ == "__main__":
    main()