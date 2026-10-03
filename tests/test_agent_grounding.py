from agent.citations import (
    build_evidence_context,
    format_deployment_citation,
    format_log_citation,
    format_metric_citation,
    validate_grounding,
)


def test_metric_citation():
    citation = format_metric_citation(
        metric_name="opscopilot_cpu_usage_percent",
        timestamp="2026-09-20T11:00:42+00:00",
        value=90.0,
    )

    assert citation.startswith("[METRIC:")
    assert "90.0" in citation


def test_log_citation():
    citation = format_log_citation(
        timestamp="2026-09-20T11:00:42+00:00",
        service="nova",
        level="ERROR",
        message="operation failed",
    )

    assert citation.startswith("[LOG|")
    assert "operation failed" in citation


def test_deployment_citation():
    citation = format_deployment_citation(
        deployment_id="DEPLOY-001",
        service="nova",
        version="synthetic-v1",
        timestamp="2026-09-19T06:00:00+00:00",
        status="success",
    )

    assert citation.startswith("[DEPLOY:")
    assert "DEPLOY-001" in citation


def test_grounding_requires_citations():
    statements = [
        "CPU increased sharply [METRIC:cpu|time=x|value=90]",
        "The service emitted an error [LOG|time=x|service=nova|level=ERROR|message=failure]",
    ]

    assert validate_grounding(statements)


def test_grounding_rejects_uncited_claim():
    statements = [
        "CPU increased sharply [METRIC:cpu|time=x|value=90]",
        "The database caused the incident.",
    ]

    assert not validate_grounding(statements)


def test_evidence_context_contains_all_sources():
    context = build_evidence_context(
        metrics=[
            {
                "metric_name": "opscopilot_cpu_usage_percent",
                "timestamp": "2026-09-20T11:00:42+00:00",
                "value": 90.0,
            }
        ],
        logs=[
            {
                "timestamp": "2026-09-20T11:00:42+00:00",
                "service": "nova",
                "level": "ERROR",
                "message": "operation failed",
            }
        ],
        deployments=[
            {
                "deployment_id": "DEPLOY-001",
                "service": "nova",
                "version": "synthetic-v1",
                "timestamp": "2026-09-19T06:00:00+00:00",
                "status": "success",
            }
        ],
    )

    assert "METRIC:" in context
    assert "LOG|" in context
    assert "DEPLOY:" in context