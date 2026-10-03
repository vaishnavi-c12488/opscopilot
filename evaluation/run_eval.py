from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.graph import run_incident_investigation
from evaluation.scorer import (
    aggregate_scores,
    score_incident,
)


ROOT = Path(__file__).resolve().parents[1]

LABEL_DIR = (
    ROOT
    / "evaluation"
    / "labeled_incidents"
)

RESULT_DIR = (
    ROOT
    / "evaluation"
    / "results"
)

RESULT_FILE = (
    RESULT_DIR
    / "latest_eval.json"
)


def load_labels() -> list[dict[str, Any]]:

    labels = []

    for path in sorted(
        LABEL_DIR.glob("INC*.json")
    ):

        with path.open(
            "r",
            encoding="utf-8",
        ) as f:

            labels.append(
                json.load(f)
            )

    return labels


def main() -> None:

    labels = load_labels()

    if not labels:
        raise RuntimeError(
            "No labeled incidents found."
        )

    results = []

    print(
        "\n"
        "=========================================="
    )

    print(
        "OpsCopilot Phase 8 Evaluation"
    )

    print(
        "Exact Match + LLM-as-Judge"
    )

    print(
        "==========================================\n"
    )

    for label in labels:

        if label.get("status") != "ready":
            continue

        incident_id = label[
            "incident_id"
        ]

        print(
            f"Evaluating {incident_id}..."
        )

        investigation = (
            run_incident_investigation(
                incident_id=incident_id,
                start_time=label[
                    "incident_start_time"
                ],
                end_time=label[
                    "incident_end_time"
                ],
                affected_entity=label.get(
                    "affected_entity",
                    "",
                ),
                source=label.get(
                    "source",
                    "openstack",
                ),
                metric_name=label.get(
                    "metric_name",
                    "opscopilot_cpu_usage_percent",
                ),
                log_query=label.get(
                    "log_query",
                    "failure error operation failed",
                ),
            )
        )

        score = score_incident(
            label,
            investigation,
        )

        results.append(
            {
                "incident_id": incident_id,
                "score": score,
                "investigation": investigation,
            }
        )

        judge = score.get(
            "llm_judge",
            {}
        )

        print(
            f"  Exact match: "
            f"{score.get('exact_match')}"
        )

        print(
            f"  Grounded: "
            f"{score.get('grounding', {}).get('grounded')}"
        )

        if judge.get("status") == "success":

            print(
                f"  LLM judge: "
                f"{judge.get('overall_score')}/5 "
                f"→ "
                f"{'PASS' if judge.get('pass') else 'FAIL'}"
            )

        else:

            print(
                "  LLM judge: ERROR"
            )

        print()

    summary = aggregate_scores(
        [
            item["score"]
            for item in results
        ]
    )

    output = {
        "version": "phase8-v3",
        "evaluation_method": {
            "exact_match": (
                "Literal expected-keyword "
                "root-cause category check."
            ),
            "llm_as_judge": (
                "Local Ollama judge evaluating "
                "semantic root-cause alignment, "
                "reasoning coherence, evidence "
                "grounding, evidence completeness, "
                "and unsupported claims."
            ),
            "calibration": {
                "status": (
                    "pending_human_labeled_sample"
                ),
                "note": (
                    "The handbook requires "
                    "judge/human agreement "
                    "calibration before treating "
                    "LLM-judge scores as validated."
                ),
            },
        },
        "incident_count": len(results),
        "summary": summary,
        "results": results,
    }

    RESULT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with RESULT_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            output,
            f,
            indent=2,
            default=str,
        )

    print(
        "=========================================="
    )

    print(
        "FINAL EVALUATION SUMMARY"
    )

    print(
        "=========================================="
    )

    print(
        json.dumps(
            summary,
            indent=2,
        )
    )

    print(
        f"\nResults saved to:\n"
        f"{RESULT_FILE}"
    )


if __name__ == "__main__":
    main()