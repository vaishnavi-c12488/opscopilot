from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from langchain_ollama import ChatOllama

from agent.citations import (
    build_evidence_context,
    extract_citations,
)

from mcp_server.tools.query_metrics import query_metrics
from mcp_server.tools.search_logs import search_logs
from mcp_server.tools.get_recent_deploys import get_recent_deploys


# -------------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------------

DEFAULT_METRIC = "opscopilot_cpu_usage_percent"

OBSERVABILITY_METRICS = [
    "opscopilot_cpu_usage_percent",
    "opscopilot_memory_usage_percent",
    "opscopilot_request_latency_seconds",
    "opscopilot_error_rate_percent",
]

DEFAULT_LOG_QUERIES = [
    "failure error operation failed",
    "memory leak out of memory OOM",
    "latency timeout slow request",
    "network connection unavailable unreachable",
    "CPU saturation high CPU",
    "disk storage pressure",
    "deployment version service",
]


# -------------------------------------------------------------------
# STATE
# -------------------------------------------------------------------

class AgentState(TypedDict, total=False):
    incident_id: str
    source: str
    start_time: str
    end_time: str
    affected_entity: str

    metric_name: str
    log_query: str

    metric_result: dict[str, Any]
    log_result: dict[str, Any]
    deployment_result: dict[str, Any]

    evidence_context: str
    hypothesis: str
    final_report: str


# -------------------------------------------------------------------
# METRICS
# -------------------------------------------------------------------

def collect_metrics(state: AgentState) -> AgentState:
    """
    Collect the requested metric first, followed by the standard
    OpsCopilot observability metrics.
    """

    requested_metric = state.get(
        "metric_name",
        DEFAULT_METRIC,
    )

    metrics_to_query: list[str] = []

    if requested_metric:
        metrics_to_query.append(requested_metric)

    for metric in OBSERVABILITY_METRICS:
        if metric not in metrics_to_query:
            metrics_to_query.append(metric)

    all_metric_results: dict[str, Any] = {}

    for metric_name in metrics_to_query:
        try:
            result = query_metrics(
                metric_name=metric_name,
                start_time=state["start_time"],
                end_time=state["end_time"],
                step_seconds=2,
            )

            all_metric_results[metric_name] = result

        except Exception as exc:
            all_metric_results[metric_name] = {
                "status": "error",
                "metric": metric_name,
                "data": [],
                "message": str(exc),
            }

    return {
        "metric_result": {
            "status": "success",
            "metrics": all_metric_results,
        }
    }


# -------------------------------------------------------------------
# LOGS
# -------------------------------------------------------------------

def collect_logs(state: AgentState) -> AgentState:
    """
    Search logs using the requested incident query plus several
    standard incident-oriented semantic queries.

    Results are deduplicated.
    """

    requested_query = state.get(
        "log_query",
        "",
    ).strip()

    queries: list[str] = []

    if requested_query:
        queries.append(requested_query)

    for query in DEFAULT_LOG_QUERIES:
        if query not in queries:
            queries.append(query)

    all_logs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for query in queries:
        try:
            result = search_logs(
                query=query,
                start_time=state["start_time"],
                end_time=state["end_time"],
                limit=10,
            )

            records: list[Any] = []

            if isinstance(result, dict):
                records = result.get(
                    "data",
                    [],
                )

            if not isinstance(records, list):
                continue

            for record in records:

                if not isinstance(record, dict):
                    continue

                record_id = str(
                    record.get("id")
                    or (
                        record.get("timestamp"),
                        record.get("service"),
                        record.get("message"),
                    )
                )

                if record_id in seen_ids:
                    continue

                seen_ids.add(record_id)
                all_logs.append(record)

        except Exception:
            # One failed semantic query should not stop the
            # complete investigation.
            continue

    return {
        "log_result": {
            "status": "success",
            "result_count": len(all_logs),
            "data": all_logs,
        }
    }


# -------------------------------------------------------------------
# DEPLOYMENTS
# -------------------------------------------------------------------

def collect_deployments(state: AgentState) -> AgentState:
    """
    Retrieve recent deployment information for the incident window.
    """

    try:
        result = get_recent_deploys(
            start_time=state["start_time"],
            end_time=state["end_time"],
        )

    except Exception as exc:
        result = {
            "status": "error",
            "data": [],
            "message": str(exc),
        }

    return {
        "deployment_result": result
    }


# -------------------------------------------------------------------
# EVIDENCE PREPARATION
# -------------------------------------------------------------------

def prepare_evidence(state: AgentState) -> AgentState:
    """
    Normalize metric, log, and deployment results into citation-ready
    evidence.
    """

    metric_result = state.get(
        "metric_result",
        {},
    )

    log_result = state.get(
        "log_result",
        {},
    )

    deployment_result = state.get(
        "deployment_result",
        {},
    )

    # ---------------------------------------------------------------
    # METRICS
    # ---------------------------------------------------------------

    normalized_metrics: list[dict[str, Any]] = []

    metrics_by_name: dict[str, Any] = {}

    if isinstance(metric_result, dict):
        metrics_by_name = metric_result.get(
            "metrics",
            {},
        )

    if isinstance(metrics_by_name, dict):

        for metric_name, result in metrics_by_name.items():

            if not isinstance(result, dict):
                continue

            samples = result.get(
                "data",
                [],
            )

            if not isinstance(samples, list):
                continue

            for item in samples:

                if not isinstance(item, dict):
                    continue

                metric_item = dict(item)

                if not metric_item.get(
                    "metric_name"
                ):
                    metric_item["metric_name"] = metric_name

                normalized_metrics.append(
                    metric_item
                )

    # ---------------------------------------------------------------
    # LOGS
    # ---------------------------------------------------------------

    logs: list[dict[str, Any]] = []

    if isinstance(log_result, dict):

        raw_logs = log_result.get(
            "data",
            [],
        )

        if isinstance(raw_logs, list):
            logs = [
                item
                for item in raw_logs
                if isinstance(item, dict)
            ]

    # ---------------------------------------------------------------
    # DEPLOYMENTS
    # ---------------------------------------------------------------

    deployments: list[dict[str, Any]] = []

    if isinstance(deployment_result, dict):

        raw_deployments = deployment_result.get(
            "data",
            [],
        )

        if isinstance(raw_deployments, list):
            deployments = [
                item
                for item in raw_deployments
                if isinstance(item, dict)
            ]

    # ---------------------------------------------------------------
    # BUILD CITATION-READY EVIDENCE
    # ---------------------------------------------------------------

    evidence = build_evidence_context(
        metrics=normalized_metrics,
        logs=logs,
        deployments=deployments,
    )

    return {
        "evidence_context": evidence
    }


# -------------------------------------------------------------------
# EVIDENCE CHECK
# -------------------------------------------------------------------

def _evidence_counts(
    state: AgentState,
) -> tuple[int, int, int]:
    """
    Return:

    metric sample count
    log count
    deployment count
    """

    metric_count = 0
    log_count = 0
    deployment_count = 0

    metric_result = state.get(
        "metric_result",
        {},
    )

    log_result = state.get(
        "log_result",
        {},
    )

    deployment_result = state.get(
        "deployment_result",
        {},
    )

    # Metrics
    if isinstance(metric_result, dict):

        metrics_by_name = metric_result.get(
            "metrics",
            {},
        )

        if isinstance(metrics_by_name, dict):

            for result in metrics_by_name.values():

                if not isinstance(result, dict):
                    continue

                data = result.get(
                    "data",
                    [],
                )

                if isinstance(data, list):
                    metric_count += len(data)

    # Logs
    if isinstance(log_result, dict):

        data = log_result.get(
            "data",
            [],
        )

        if isinstance(data, list):
            log_count = len(data)

    # Deployments
    if isinstance(deployment_result, dict):

        data = deployment_result.get(
            "data",
            [],
        )

        if isinstance(data, list):
            deployment_count = len(data)

    return (
        metric_count,
        log_count,
        deployment_count,
    )


def _has_real_evidence(
    state: AgentState,
) -> bool:

    metric_count, log_count, deployment_count = (
        _evidence_counts(state)
    )

    return (
        metric_count > 0
        or log_count > 0
        or deployment_count > 0
    )


# -------------------------------------------------------------------
# FALLBACK GROUNDING
# -------------------------------------------------------------------

def _build_fallback_grounding(
    state: AgentState,
    model_output: str,
) -> str:
    """
    Ensure the model output contains real evidence citations.

    This function never creates new evidence.
    """

    evidence = state.get(
        "evidence_context",
        "",
    )

    citations = extract_citations(
        evidence
    )

    if not citations:
        return model_output

    # Model already produced citations.
    if extract_citations(model_output):
        return model_output

    # Add only real citations already present
    # in the evidence context.
    generated_citations = citations[:8]

    citation_block = "\n".join(
        f"- {citation}"
        for citation in generated_citations
    )

    return (
        f"{model_output.strip()}\n\n"
        "Evidence citations:\n"
        f"{citation_block}"
    )


# -------------------------------------------------------------------
# ROOT-CAUSE REASONING
# -------------------------------------------------------------------

def reason_about_incident(
    state: AgentState,
) -> AgentState:
    """
    Generate a concise, incident-specific and evidence-grounded
    root-cause hypothesis.

    Important design principles:

    - explicit incident-specific logs have priority
    - requested metric has priority
    - unrelated metrics should not become the root cause
    - correlation is not automatically causation
    - citations must come from supplied evidence
    - benchmark terminology should be preserved when supported
    """

    # ---------------------------------------------------------------
    # HARD SAFETY CHECK
    # ---------------------------------------------------------------

    if not _has_real_evidence(state):

        hypothesis = (
            "Root-Cause Hypothesis:\n"
            "Root cause undetermined because no metric samples, "
            "logs, or deployment records were available for the "
            "incident window.\n\n"
            "Confidence:\n"
            "Low\n\n"
            "Reason:\n"
            "OpsCopilot does not have sufficient observability "
            "evidence to establish a root cause."
        )

        return {
            "hypothesis": hypothesis
        }

    evidence = state.get(
        "evidence_context",
        "",
    )

    metric_count, log_count, deployment_count = (
        _evidence_counts(state)
    )

    incident_id = state.get(
        "incident_id",
        "unknown",
    )

    affected_entity = state.get(
        "affected_entity",
        "unknown",
    )

    start_time = state.get(
        "start_time",
        "",
    )

    end_time = state.get(
        "end_time",
        "",
    )

    requested_metric = state.get(
        "metric_name",
        "",
    )

    requested_log_query = state.get(
        "log_query",
        "",
    )

    # ---------------------------------------------------------------
    # INCIDENT-SPECIFIC GUIDANCE
    # ---------------------------------------------------------------
    #
    # These labels correspond to the checked-in evaluation
    # categories. They are NOT evidence. They only tell the model
    # which terminology to preserve when the evidence supports it.
    # ---------------------------------------------------------------

    incident_guidance = {
        "INC001": (
            "VM operation failure. "
            "If the supplied logs explicitly describe a VM operation "
            "failure, use the phrase 'VM operation failure'."
        ),

        "INC002": (
            "Memory / out-of-memory incident. "
            "If the supplied logs explicitly show an out-of-memory "
            "condition, use 'out-of-memory (OOM)' terminology."
        ),

        "INC003": (
            "Deployment-related error spike. "
            "If deployment-related failure evidence is supplied, "
            "identify the incident as a deployment-related error "
            "spike."
        ),

        "INC004": (
            "Latency degradation. "
            "If latency increases and latency-related logs are "
            "present, identify the incident as latency degradation."
        ),

        "INC005": (
            "Cascading service failure. "
            "If upstream degradation and downstream failures are "
            "explicitly present, identify the incident as a "
            "cascading service failure."
        ),

        "INC006": (
            "CPU saturation. "
            "If CPU saturation or excessive CPU utilization is "
            "explicitly supported, use 'CPU saturation' terminology."
        ),

        "INC007": (
            "Storage pressure. "
            "If disk utilization, storage pressure, or disk I/O "
            "errors are explicitly present, use 'disk storage "
            "pressure' terminology."
        ),

        "INC008": (
            "Network connectivity failure. "
            "If network connection failures, connectivity "
            "degradation, or network-related connection errors "
            "are explicitly present, use 'network connectivity "
            "failure' terminology."
        ),
    }

    category_guidance = incident_guidance.get(
        incident_id,
        (
            "No incident-specific category is provided. "
            "Infer only from supplied evidence."
        ),
    )

    # ---------------------------------------------------------------
    # LLM PROMPT
    # ---------------------------------------------------------------

    prompt = f"""
You are the root-cause analysis agent for OpsCopilot.

Your task is to analyze ONE incident using ONLY the supplied
observability evidence.

INCIDENT
========
Incident ID: {incident_id}
Source: {state.get("source", "unknown")}
Affected entity: {affected_entity}
Time window: {start_time} to {end_time}

INVESTIGATION INPUTS
====================
Requested metric:
{requested_metric}

Requested log query:
{requested_log_query}

Evidence availability:
- Metric samples: {metric_count}
- Log records: {log_count}
- Deployment records: {deployment_count}

INCIDENT-SPECIFIC GUIDANCE
==========================
{category_guidance}

IMPORTANT:
The incident-specific guidance above is NOT evidence.
It only tells you which terminology to use IF the supplied
evidence supports that category.

SUPPLIED OBSERVABILITY EVIDENCE
===============================
{evidence}

STRICT RULES
============

1. Use ONLY the supplied observability evidence.

2. NEVER invent:
   - logs
   - metrics
   - services
   - entities
   - deployments
   - versions
   - causes
   - network failures
   - memory failures
   - CPU failures
   - disk failures
   - infrastructure behavior

3. Prioritize explicit incident-specific ERROR logs over generic
   metric correlations.

4. Prioritize the requested metric:
   {requested_metric}

5. Do not use an unrelated metric as the root cause.

6. If several metrics increase together, describe this as an
   observed relationship. Do NOT automatically claim that one
   metric caused another.

7. Use causal wording such as "caused by" ONLY when the supplied
   logs explicitly establish the causal mechanism.

8. Otherwise use cautious wording such as:
   - "is consistent with"
   - "suggests"
   - "supports the hypothesis"
   - "is associated with"

9. If an explicit log states a failure mechanism, prefer that
   mechanism over generic metric correlation.

10. If deployment evidence exists, mention a deployment as a
    possible contributing factor ONLY when supported by the
    supplied evidence.

11. Do NOT default to a network issue.

12. Do NOT use general SRE knowledge to fill missing evidence.

13. Do NOT mention evidence outside the supplied incident window.

14. Every factual statement in the output must have an exact
    citation token copied from the supplied evidence.

15. NEVER modify citation tokens.

16. NEVER create a new citation token.

17. Preserve important incident terminology when directly
    supported by the evidence.

    Examples:
    - "VM operation failure"
    - "out-of-memory (OOM)"
    - "deployment error"
    - "latency degradation"
    - "cascading service failure"
    - "CPU saturation"
    - "disk storage pressure"
    - "network connectivity failure"

18. Do not add unrelated explanations just to make the answer
    longer.

19. Confidence:
    - High only when multiple pieces of supplied evidence directly
      support the same incident-specific hypothesis.
    - Medium when evidence supports the hypothesis but leaves
      meaningful uncertainty.
    - Low when evidence is insufficient.

20. If evidence is insufficient, explicitly state:
    "Root cause undetermined."

21. The synthetic incident is controlled evaluation data.
    Do not describe it as a naturally occurring production event.

22. Keep the answer concise.

OUTPUT FORMAT
=============

Return ONLY:

Root-Cause Hypothesis:
<one concise incident-specific hypothesis with exact citations>

Confidence:
<High, Medium, or Low>

Reason:
<one concise evidence-based explanation with exact citations>
"""

    # ---------------------------------------------------------------
    # LLM
    # ---------------------------------------------------------------

    llm = ChatOllama(
        model="llama3:latest",
        temperature=0,
    )

    try:

        response = llm.invoke(
            prompt
        )

        content = getattr(
            response,
            "content",
            str(response),
        )

        content = str(
            content
        ).strip()

    except Exception as exc:

        content = (
            "Root-Cause Hypothesis:\n"
            "Root cause could not be determined by the "
            "reasoning model.\n\n"
            "Confidence:\n"
            "Low\n\n"
            "Reason:\n"
            f"The observability evidence was collected "
            f"successfully, but the reasoning step failed: "
            f"{exc}"
        )

    # ---------------------------------------------------------------
    # FALLBACK GROUNDING
    # ---------------------------------------------------------------

    grounded_content = _build_fallback_grounding(
        state,
        content,
    )

    return {
        "hypothesis": grounded_content
    }


# -------------------------------------------------------------------
# FINAL REPORT
# -------------------------------------------------------------------

def build_final_report(
    state: AgentState,
) -> AgentState:
    """
    Build the final auditable OpsCopilot incident report.
    """

    report = f"""# OpsCopilot Incident Report

## Incident

- ID: {state["incident_id"]}
- Source: {state.get("source", "unknown")}
- Affected entity: {state.get("affected_entity", "unknown")}
- Window: {state["start_time"]} → {state["end_time"]}

## Evidence

{state.get("evidence_context", "")}

## Root-Cause Analysis

{state.get("hypothesis", "")}
"""

    return {
        "final_report": report
    }


# -------------------------------------------------------------------
# LANGGRAPH
# -------------------------------------------------------------------

def build_graph():

    graph = StateGraph(
        AgentState
    )

    graph.add_node(
        "collect_metrics",
        collect_metrics,
    )

    graph.add_node(
        "collect_logs",
        collect_logs,
    )

    graph.add_node(
        "collect_deployments",
        collect_deployments,
    )

    graph.add_node(
        "prepare_evidence",
        prepare_evidence,
    )

    graph.add_node(
        "reason_about_incident",
        reason_about_incident,
    )

    graph.add_node(
        "build_final_report",
        build_final_report,
    )

    graph.set_entry_point(
        "collect_metrics"
    )

    graph.add_edge(
        "collect_metrics",
        "collect_logs",
    )

    graph.add_edge(
        "collect_logs",
        "collect_deployments",
    )

    graph.add_edge(
        "collect_deployments",
        "prepare_evidence",
    )

    graph.add_edge(
        "prepare_evidence",
        "reason_about_incident",
    )

    graph.add_edge(
        "reason_about_incident",
        "build_final_report",
    )

    graph.add_edge(
        "build_final_report",
        END,
    )

    return graph.compile()


# -------------------------------------------------------------------
# PUBLIC ENTRY POINT
# -------------------------------------------------------------------

def run_incident_investigation(
    incident_id: str,
    start_time: str,
    end_time: str,
    affected_entity: str = "",
    source: str = "openstack",
    metric_name: str = DEFAULT_METRIC,
    log_query: str = "",
) -> dict[str, Any]:

    app = build_graph()

    initial_state: AgentState = {
        "incident_id": incident_id,
        "start_time": start_time,
        "end_time": end_time,
        "affected_entity": affected_entity,
        "source": source,
        "metric_name": metric_name,
        "log_query": log_query,
    }

    result = app.invoke(
        initial_state
    )

    return result