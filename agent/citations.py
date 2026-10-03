from __future__ import annotations

import re
from typing import Any


METRIC_CITATION_PATTERN = re.compile(
    r"\[METRIC:[^\]]+\]"
)

LOG_CITATION_PATTERN = re.compile(
    r"\[LOG\|[^\]]+\]"
)

DEPLOYMENT_CITATION_PATTERN = re.compile(
    r"\[DEPLOY:[^\]]+\]"
)


def format_metric_citation(
    metric_name: str,
    timestamp: str,
    value: Any,
) -> str:
    """Create a citation for a Prometheus metric observation."""

    return (
        f"[METRIC:{metric_name}|time={timestamp}|value={value}]"
    )


def format_log_citation(
    timestamp: str,
    service: str,
    level: str,
    message: str,
) -> str:
    """Create a citation for a retrieved log."""

    return (
        f"[LOG|time={timestamp}|service={service}|level={level}|"
        f"message={message}]"
    )


def format_deployment_citation(
    deployment_id: str,
    service: str,
    version: str,
    timestamp: str,
    status: str,
) -> str:
    """Create a citation for a deployment record."""

    return (
        f"[DEPLOY:{deployment_id}|service={service}|version={version}|"
        f"time={timestamp}|status={status}]"
    )


def build_evidence_context(
    metrics: list[dict],
    logs: list[dict],
    deployments: list[dict],
) -> str:
    """
    Convert raw tool results into compact evidence
    for the reasoning model.
    """

    sections: list[str] = []

    # ---------------------------------------------------------
    # METRICS
    # ---------------------------------------------------------

    sections.append("=== METRIC EVIDENCE ===")

    if metrics:

        for item in metrics:

            metric_name = str(
                item.get(
                    "metric_name",
                    item.get(
                        "metric",
                        "unknown_metric",
                    ),
                )
            )

            timestamp = str(
                item.get(
                    "timestamp",
                    "",
                )
            )

            value = item.get("value")

            sections.append(
                format_metric_citation(
                    metric_name=metric_name,
                    timestamp=timestamp,
                    value=value,
                )
            )

    else:

        sections.append(
            "No metric observations found."
        )

    # ---------------------------------------------------------
    # LOGS
    # ---------------------------------------------------------

    sections.append(
        "\n=== LOG EVIDENCE ==="
    )

    if logs:

        for item in logs:

            sections.append(
                format_log_citation(
                    timestamp=str(
                        item.get(
                            "timestamp",
                            "",
                        )
                    ),
                    service=str(
                        item.get(
                            "service",
                            "unknown",
                        )
                    ),
                    level=str(
                        item.get(
                            "level",
                            "unknown",
                        )
                    ),
                    message=str(
                        item.get(
                            "message",
                            "",
                        )
                    ),
                )
            )

    else:

        sections.append(
            "No logs found in the incident window."
        )

    # ---------------------------------------------------------
    # DEPLOYMENTS
    # ---------------------------------------------------------

    sections.append(
        "\n=== DEPLOYMENT EVIDENCE ==="
    )

    if deployments:

        for item in deployments:

            sections.append(
                format_deployment_citation(
                    deployment_id=str(
                        item.get(
                            "deployment_id",
                            "unknown",
                        )
                    ),
                    service=str(
                        item.get(
                            "service",
                            "unknown",
                        )
                    ),
                    version=str(
                        item.get(
                            "version",
                            "unknown",
                        )
                    ),
                    timestamp=str(
                        item.get(
                            "timestamp",
                            "",
                        )
                    ),
                    status=str(
                        item.get(
                            "status",
                            "unknown",
                        )
                    ),
                )
            )

    else:

        sections.append(
            "No deployments found in the incident window."
        )

    return "\n".join(sections)


def extract_citations(text: str) -> list[str]:
    """
    Extract all supported citation tokens from generated text.
    """

    citations: list[str] = []

    citations.extend(
        METRIC_CITATION_PATTERN.findall(text)
    )

    citations.extend(
        LOG_CITATION_PATTERN.findall(text)
    )

    citations.extend(
        DEPLOYMENT_CITATION_PATTERN.findall(text)
    )

    return citations


def has_citation(text: str) -> bool:
    """
    Return True when text contains at least one
    supported evidence citation.
    """

    return bool(
        extract_citations(text)
    )


def citations_exist_in_evidence(
    text: str,
    evidence_context: str,
) -> bool:
    """
    Verify that every citation used by the model
    exists exactly in the supplied evidence.
    """

    citations = extract_citations(text)

    if not citations:
        return False

    return all(
        citation in evidence_context
        for citation in citations
    )


def validate_grounding(
    statements: list[str],
    evidence_context: str | None = None,
) -> bool:
    """
    Validate evidence grounding.

    Every non-empty statement must contain a supported
    citation. When evidence_context is provided, every
    citation must exactly match supplied evidence.
    """

    if not statements:
        return False

    for statement in statements:

        statement = statement.strip()

        if not statement:
            continue

        if not has_citation(statement):
            return False

        if evidence_context is not None:

            if not citations_exist_in_evidence(
                statement,
                evidence_context,
            ):
                return False

    return True