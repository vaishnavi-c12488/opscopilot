from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

DEPLOYMENT_FILE = (
    ROOT
    / "data"
    / "processed"
    / "deploy_history.json"
)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )


def _load_deployments() -> list[dict]:
    """
    Load deployment history from the processed data directory.

    Missing deployment history is treated as valid empty
    evidence rather than an exception.
    """

    if not DEPLOYMENT_FILE.exists():
        return []

    try:

        with DEPLOYMENT_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        if not isinstance(data, list):
            return []

        return data

    except (
        json.JSONDecodeError,
        OSError,
    ):
        return []


def get_recent_deploys(
    start_time: str,
    end_time: str,
) -> dict:

    try:

        start = _parse_timestamp(
            start_time
        )

        end = _parse_timestamp(
            end_time
        )

        deployments = _load_deployments()

        matching_deployments = []

        for deployment in deployments:

            timestamp = deployment.get(
                "timestamp"
            )

            if not timestamp:
                continue

            try:

                deployment_time = _parse_timestamp(
                    timestamp
                )

            except ValueError:
                continue

            if start <= deployment_time <= end:

                matching_deployments.append(
                    {
                        "deployment_id": deployment.get(
                            "deployment_id",
                            "unknown",
                        ),
                        "service": deployment.get(
                            "service",
                            "unknown",
                        ),
                        "version": deployment.get(
                            "version",
                            "unknown",
                        ),
                        "timestamp": timestamp,
                        "status": deployment.get(
                            "status",
                            "unknown",
                        ),
                    }
                )

        return {
            "status": "success",
            "start_time": start_time,
            "end_time": end_time,
            "deployment_count": len(
                matching_deployments
            ),
            "data": matching_deployments,
        }

    except ValueError as exc:

        return {
            "status": "error",
            "start_time": start_time,
            "end_time": end_time,
            "deployment_count": 0,
            "message": (
                f"Invalid timestamp format: {exc}"
            ),
            "data": [],
        }


if __name__ == "__main__":

    result = get_recent_deploys(
        start_time="2026-09-19T05:00:00+00:00",
        end_time="2026-09-19T07:00:00+00:00",
    )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )