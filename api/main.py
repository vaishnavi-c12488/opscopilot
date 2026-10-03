from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent.graph import run_incident_investigation


# ============================================================
# Logging
# ============================================================

logger = logging.getLogger("opscopilot-api")
logger.setLevel(logging.INFO)
logger.propagate = False

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    )

    handler.setFormatter(formatter)
    logger.addHandler(handler)


# ============================================================
# FastAPI application
# ============================================================

app = FastAPI(
    title="OpsCopilot API",
    description=(
        "FastAPI service for OpsCopilot "
        "incident investigation using "
        "LangGraph, MCP tools and "
        "observability evidence."
    ),
    version="1.0.0",
)


# ============================================================
# Request schema
# ============================================================

class IncidentRequest(BaseModel):
    incident_id: str = Field(
        ...,
        min_length=1,
        description="Unique incident identifier.",
    )

    start_time: datetime = Field(
        ...,
        description=(
            "Incident start time in ISO-8601 format."
        ),
    )

    end_time: datetime = Field(
        ...,
        description=(
            "Incident end time in ISO-8601 format."
        ),
    )

    affected_entity: str = Field(
        default="",
        description=(
            "Affected VM, service, host or entity."
        ),
    )

    source: str = Field(
        default="openstack",
        min_length=1,
        description="Observability data source.",
    )

    metric_name: str = Field(
        default="opscopilot_cpu_usage_percent",
        min_length=1,
        description=(
            "Prometheus metric to investigate."
        ),
    )

    log_query: str = Field(
        default="failure error operation failed",
        min_length=1,
        description=(
            "Semantic query used for log retrieval."
        ),
    )


# ============================================================
# Response schema
# ============================================================

class IncidentResponse(BaseModel):
    status: str
    incident_id: str
    processing_time_seconds: float
    investigation: dict


# ============================================================
# Health endpoint
# ============================================================

@app.get(
    "/health",
    tags=["system"],
)
def health_check() -> dict:

    return {
        "status": "healthy",
        "service": "opscopilot-api",
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
    }


# ============================================================
# Root endpoint
# ============================================================

@app.get(
    "/",
    tags=["system"],
)
def root() -> dict:

    return {
        "service": "OpsCopilot API",
        "version": app.version,
        "docs": "/docs",
        "health": "/health",
        "investigation_endpoint": (
            "/v1/investigate"
        ),
    }


# ============================================================
# Incident investigation endpoint
# ============================================================

@app.post(
    "/v1/investigate",
    response_model=IncidentResponse,
    tags=["incident"],
)
def investigate_incident(
    request: IncidentRequest,
) -> IncidentResponse:

    start_processing = time.perf_counter()

    logger.info(
        "Incident investigation started | "
        "incident_id=%s | source=%s | metric=%s",
        request.incident_id,
        request.source,
        request.metric_name,
    )

    # --------------------------------------------------------
    # Validation
    # --------------------------------------------------------

    if request.end_time <= request.start_time:

        logger.warning(
            "Invalid incident window | "
            "incident_id=%s",
            request.incident_id,
        )

        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INVALID_TIME_WINDOW",
                    "message": (
                        "end_time must be later "
                        "than start_time."
                    ),
                }
            },
        )

    # --------------------------------------------------------
    # Run LangGraph investigation
    # --------------------------------------------------------

    try:

        investigation = run_incident_investigation(
            incident_id=request.incident_id,
            start_time=request.start_time.isoformat(),
            end_time=request.end_time.isoformat(),
            affected_entity=request.affected_entity,
            source=request.source,
            metric_name=request.metric_name,
            log_query=request.log_query,
        )

    except Exception as exc:

        logger.exception(
            "Incident investigation failed | "
            "incident_id=%s",
            request.incident_id,
        )

        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "INVESTIGATION_FAILED",
                    "message": (
                        "The incident investigation "
                        "could not be completed."
                    ),
                }
            },
        ) from exc

    # --------------------------------------------------------
    # Response
    # --------------------------------------------------------

    processing_time = (
        time.perf_counter()
        - start_processing
    )

    logger.info(
        "Incident investigation completed | "
        "incident_id=%s | duration=%.3fs",
        request.incident_id,
        processing_time,
    )

    return IncidentResponse(
        status="success",
        incident_id=request.incident_id,
        processing_time_seconds=round(
            processing_time,
            3,
        ),
        investigation=investigation,
    )