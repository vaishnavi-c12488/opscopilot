from __future__ import annotations

import json
import re
from typing import Any

from langchain_ollama import ChatOllama

from agent.citations import extract_citations


# ============================================================
# Basic helpers
# ============================================================

def normalize(text: str) -> str:
    return " ".join(
        str(text).lower().strip().split()
    )


def extract_hypothesis(
    investigation: dict[str, Any],
) -> str:
    return str(
        investigation.get(
            "hypothesis",
            ""
        )
    )


# ============================================================
# Exact-match scoring
# ============================================================

def keyword_match(
    hypothesis: str,
    expected_keywords: list[str],
) -> dict[str, Any]:

    normalized = normalize(hypothesis)

    matched = []
    missing = []

    for keyword in expected_keywords:

        if normalize(keyword) in normalized:
            matched.append(keyword)
        else:
            missing.append(keyword)

    return {
        "matched": matched,
        "missing": missing,
        "all_matched": len(missing) == 0,
    }


# ============================================================
# Citation / grounding scoring
# ============================================================

def grounding_score(
    hypothesis: str,
    evidence_context: str,
) -> dict[str, Any]:

    citations = extract_citations(
        hypothesis
    )

    valid_citations = [
        citation
        for citation in citations
        if citation in evidence_context
    ]

    return {
        "citation_count": len(citations),
        "valid_citation_count": len(
            valid_citations
        ),
        "grounded": (
            len(citations) > 0
            and len(citations)
            == len(valid_citations)
        ),
        "citations": citations,
        "invalid_citations": [
            citation
            for citation in citations
            if citation not in evidence_context
        ],
    }


# ============================================================
# Evidence coverage
# ============================================================

def evidence_coverage(
    hypothesis: str,
    expected_evidence: list[str],
) -> dict[str, Any]:

    normalized = normalize(hypothesis)

    matched = []
    missing = []

    for evidence_item in expected_evidence:

        if normalize(evidence_item) in normalized:
            matched.append(evidence_item)
        else:
            missing.append(evidence_item)

    total = len(expected_evidence)

    return {
        "matched": matched,
        "missing": missing,
        "coverage_count": len(matched),
        "expected_count": total,
        "coverage_ratio": (
            len(matched) / total
            if total
            else 1.0
        ),
    }


# ============================================================
# Relevant evidence extraction
# ============================================================

def build_judge_evidence(
    label: dict[str, Any],
    investigation: dict[str, Any],
) -> str:
    """
    Build a compact evidence package for the LLM judge.

    The full investigation may contain many unrelated metrics.
    The judge should primarily evaluate evidence relevant to the
    labeled incident rather than being distracted by unrelated
    observability signals.
    """

    evidence_context = str(
        investigation.get(
            "evidence_context",
            ""
        )
    )

    expected_evidence = [
        str(item)
        for item in label.get(
            "expected_evidence",
            []
        )
    ]

    expected_keywords = [
        str(item)
        for item in label.get(
            "expected_keywords",
            []
        )
    ]

    # --------------------------------------------------------
    # Split evidence into sections
    # --------------------------------------------------------

    sections = re.split(
        r"\n(?=== )",
        evidence_context
    )

    relevant_lines = []

    search_terms = [
        normalize(item)
        for item in (
            expected_evidence
            + expected_keywords
        )
        if str(item).strip()
    ]

    for section in sections:

        section_lines = section.splitlines()

        for line in section_lines:

            normalized_line = normalize(line)

            if not normalized_line:
                continue

            if any(
                term in normalized_line
                for term in search_terms
            ):
                relevant_lines.append(line)

    # --------------------------------------------------------
    # Always preserve log evidence because the logs can contain
    # the most direct root-cause information.
    # --------------------------------------------------------

    log_section = re.search(
        r"=== LOG EVIDENCE ===.*?(?=\n=== DEPLOYMENT EVIDENCE ===|\Z)",
        evidence_context,
        re.DOTALL,
    )

    if log_section:
        log_lines = log_section.group(0).splitlines()

        for line in log_lines:
            if line not in relevant_lines:
                relevant_lines.append(line)

    # --------------------------------------------------------
    # Preserve deployment evidence.
    # --------------------------------------------------------

    deployment_section = re.search(
        r"=== DEPLOYMENT EVIDENCE ===.*",
        evidence_context,
        re.DOTALL,
    )

    if deployment_section:
        deployment_lines = deployment_section.group(0).splitlines()

        for line in deployment_lines:
            if line not in relevant_lines:
                relevant_lines.append(line)

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    if not relevant_lines:
        return evidence_context

    return "\n".join(relevant_lines)


# ============================================================
# JSON extraction
# ============================================================

def _extract_json(text: str) -> dict[str, Any]:

    text = str(text).strip()

    # Direct JSON
    try:

        parsed = json.loads(text)

        if isinstance(parsed, dict):
            return parsed

    except json.JSONDecodeError:
        pass

    # JSON inside markdown code block
    match = re.search(
        r"```json\s*(\{.*?\})\s*```",
        text,
        re.DOTALL | re.IGNORECASE,
    )

    if match:

        try:

            parsed = json.loads(
                match.group(1)
            )

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

    # First JSON object
    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end > start:

        try:

            parsed = json.loads(
                text[start:end + 1]
            )

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

    return {}


# ============================================================
# Local LLM judge
# ============================================================

def llm_judge(
    label: dict[str, Any],
    investigation: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate the agent's reasoning with a local Ollama judge.

    This is a secondary evaluation layer. It does not replace
    exact-match scoring.

    The judge evaluates:
    - root-cause alignment
    - reasoning coherence
    - evidence grounding
    - evidence completeness
    - unsupported claims
    """

    hypothesis = extract_hypothesis(
        investigation
    )

    expected_type = str(
        label.get(
            "incident_type",
            ""
        )
    )

    ground_truth = str(
        label.get(
            "ground_truth",
            ""
        )
    )

    expected_keywords = label.get(
        "expected_keywords",
        []
    )

    expected_evidence = label.get(
        "expected_evidence",
        []
    )

    judge_evidence = build_judge_evidence(
        label,
        investigation,
    )

    # --------------------------------------------------------
    # Strong semantic guidance based on the benchmark label.
    # --------------------------------------------------------

    expected_category = " ".join(
        str(item)
        for item in expected_keywords
    )

    prompt = f"""
You are the evaluation judge for an AI SRE
incident root-cause analysis system.

Your job is to evaluate whether the candidate investigation
correctly identifies the labeled incident category and whether
its reasoning is supported by the supplied evidence.

This is a controlled benchmark.

Do NOT invent facts.

Do NOT penalize the candidate merely because it uses different
wording from the benchmark.

For example:
- "network connectivity degraded" can express the same
  category as "network connectivity failure" when the supplied
  logs explicitly show connection failures.
- "disk storage capacity critically low" can express the same
  category as "disk storage pressure".
- "out-of-memory condition" can express the same category as
  "OOM".
- "high CPU utilization" can express the same category as
  "CPU saturation" when the metric and logs support it.

Judge the MEANING, not literal keyword repetition.

At the same time, do not accept a completely different
root cause simply because it sounds plausible.

------------------------------------------------------------
LABELED INCIDENT
------------------------------------------------------------

Incident type:
{label.get("incident_type", "")}

Ground-truth description:
{ground_truth}

Expected root-cause category:
{expected_category}

Expected evidence:
{json.dumps(expected_evidence)}

------------------------------------------------------------
SUPPLIED RELEVANT EVIDENCE
------------------------------------------------------------

{judge_evidence}

------------------------------------------------------------
CANDIDATE INVESTIGATION
------------------------------------------------------------

{hypothesis}

------------------------------------------------------------
SCORING RULES
------------------------------------------------------------

Score every dimension from 1 to 5.

1. root_cause_alignment

5 = Candidate identifies the same root-cause category as
    the labeled incident and the evidence supports it.

4 = Correct root-cause category with minor wording or
    specificity differences.

3 = Partially correct or somewhat vague, but substantially
    related to the labeled root cause.

2 = Weak or substantially incomplete alignment.

1 = Incorrect root cause.

2. reasoning_coherence

5 = Clear, logical reasoning connecting the observed evidence
    to the proposed root cause.

4 = Mostly clear with minor unnecessary statements.

3 = Understandable but incomplete.

2 = Significant logical gaps.

1 = Incoherent.

3. evidence_grounding

5 = Main factual claims are directly supported by supplied
    metrics or logs and citations are valid.

4 = Strongly supported with minor irrelevant statements.

3 = Partially supported.

2 = Several unsupported claims.

1 = Mostly unsupported.

4. evidence_completeness

5 = Uses the important evidence needed to explain the incident.

4 = Uses most important evidence.

3 = Uses some important evidence but misses relevant details.

2 = Misses substantial relevant evidence.

1 = Largely ignores the supplied evidence.

5. unsupported_claims

5 = No meaningful unsupported claims.

4 = Only minor wording/speculation issues.

3 = Some unsupported statements, but they do not change
    the main diagnosis.

2 = Several unsupported claims that weaken the analysis.

1 = Major unsupported causal or factual claims.

IMPORTANT CAUSALITY RULE:

Do not require proof of causation when the benchmark itself
is evaluating root-cause identification from correlated
observability evidence.

However, if the candidate claims a specific mechanism that
is NOT present in the supplied evidence, penalize that claim.

For example, if the evidence shows increasing disk usage and
disk I/O errors, it is acceptable to identify disk/storage
pressure as the root-cause category.

Do not invent a specific process, application, network device,
deployment, memory leak, or infrastructure mechanism unless
the evidence actually contains it.

IMPORTANT:

A correct diagnosis should not receive a low score merely
because the candidate uses cautious wording such as
"associated with", "consistent with", or "suggests".

A correct diagnosis should also not receive a low score merely
because it contains additional observability metrics, provided
those metrics do not contradict the diagnosis.

------------------------------------------------------------
OUTPUT FORMAT
------------------------------------------------------------

Return ONLY one valid JSON object.

Do not use markdown.

Do not add commentary before or after the JSON.

Use exactly these fields:

{{
  "root_cause_alignment": 1,
  "reasoning_coherence": 1,
  "evidence_grounding": 1,
  "evidence_completeness": 1,
  "unsupported_claims": 1,
  "reason": "short explanation"
}}
"""

    try:

        llm = ChatOllama(
            model="llama3:latest",
            temperature=0,
        )

        response = llm.invoke(
            prompt
        )

        content = getattr(
            response,
            "content",
            str(response),
        )

        result = _extract_json(
            content
        )

        if not result:

            return {
                "status": "error",
                "message": (
                    "LLM judge returned "
                    "non-JSON output."
                ),
            }

        dimensions = [
            "root_cause_alignment",
            "reasoning_coherence",
            "evidence_grounding",
            "evidence_completeness",
            "unsupported_claims",
        ]

        # ----------------------------------------------------
        # Validate and normalize scores
        # ----------------------------------------------------

        for dimension in dimensions:

            value = result.get(
                dimension,
                0
            )

            try:
                value = int(value)
            except (TypeError, ValueError):
                value = 0

            result[dimension] = max(
                0,
                min(5, value)
            )

        # ----------------------------------------------------
        # Recalculate overall score ourselves.
        # Never trust the LLM's overall_score.
        # ----------------------------------------------------

        scores = [
            result[dimension]
            for dimension in dimensions
        ]

        result["overall_score"] = round(
            sum(scores) / len(scores),
            2,
        )

        # ----------------------------------------------------
        # Determine pass ourselves.
        # ----------------------------------------------------

        result["pass"] = (
            result["overall_score"] >= 3.5
            and result[
                "root_cause_alignment"
            ] >= 3
            and result[
                "evidence_grounding"
            ] >= 3
        )

        result["status"] = "success"

        return result

    except Exception as exc:

        return {
            "status": "error",
            "message": (
                f"LLM judge failed: {exc}"
            ),
        }


# ============================================================
# Incident scoring
# ============================================================

def score_incident(
    label: dict[str, Any],
    investigation: dict[str, Any],
) -> dict[str, Any]:

    hypothesis = extract_hypothesis(
        investigation
    )

    evidence_context = str(
        investigation.get(
            "evidence_context",
            ""
        )
    )

    expected_keywords = label.get(
        "expected_keywords",
        []
    )

    expected_evidence = label.get(
        "expected_evidence",
        []
    )

    keyword_result = keyword_match(
        hypothesis,
        expected_keywords,
    )

    grounding_result = grounding_score(
        hypothesis,
        evidence_context,
    )

    coverage_result = evidence_coverage(
        hypothesis,
        expected_evidence,
    )

    # --------------------------------------------------------
    # Traditional exact-match benchmark
    # --------------------------------------------------------

    exact_match = (
        keyword_result["all_matched"]
    )

    # --------------------------------------------------------
    # LLM-as-judge
    # --------------------------------------------------------

    judge_result = llm_judge(
        label,
        investigation,
    )

    return {
        "incident_id": label.get(
            "incident_id",
            "unknown",
        ),

        "incident_type": label.get(
            "incident_type",
            "unknown",
        ),

        "exact_match": exact_match,

        "keyword_match": keyword_result,

        "grounding": grounding_result,

        "evidence_coverage": coverage_result,

        "llm_judge": judge_result,

        "hypothesis": hypothesis,

        "expected_keywords": (
            expected_keywords
        ),

        "expected_evidence": (
            expected_evidence
        ),
    }


# ============================================================
# Aggregate scoring
# ============================================================

def aggregate_scores(
    scores: list[dict[str, Any]],
) -> dict[str, Any]:

    if not scores:

        return {
            "incident_count": 0,
            "exact_match_accuracy": 0.0,
            "grounded_accuracy": 0.0,
            "mean_evidence_coverage": 0.0,
            "llm_judge": {
                "successful_judgments": 0,
                "judge_pass_rate": 0.0,
                "mean_overall_score": 0.0,
            },
        }

    count = len(scores)

    exact_matches = sum(
        1
        for score in scores
        if score.get("exact_match")
    )

    grounded = sum(
        1
        for score in scores
        if score.get(
            "grounding",
            {}
        ).get("grounded")
    )

    coverage_values = [
        score.get(
            "evidence_coverage",
            {}
        ).get(
            "coverage_ratio",
            0.0,
        )
        for score in scores
    ]

    successful_judgments = [
        score.get(
            "llm_judge",
            {}
        )
        for score in scores
        if score.get(
            "llm_judge",
            {}
        ).get("status") == "success"
    ]

    judge_passes = sum(
        1
        for judge in successful_judgments
        if judge.get("pass") is True
    )

    judge_scores = [
        float(
            judge.get(
                "overall_score",
                0.0,
            )
        )
        for judge in successful_judgments
    ]

    return {
        "incident_count": count,

        "exact_match_accuracy": round(
            exact_matches / count,
            4,
        ),

        "grounded_accuracy": round(
            grounded / count,
            4,
        ),

        "mean_evidence_coverage": round(
            sum(coverage_values)
            / len(coverage_values),
            4,
        ),

        "llm_judge": {
            "successful_judgments": len(
                successful_judgments
            ),

            "judge_pass_rate": round(
                (
                    judge_passes
                    / len(successful_judgments)
                )
                if successful_judgments
                else 0.0,
                4,
            ),

            "mean_overall_score": round(
                (
                    sum(judge_scores)
                    / len(judge_scores)
                )
                if judge_scores
                else 0.0,
                2,
            ),
        },
    }