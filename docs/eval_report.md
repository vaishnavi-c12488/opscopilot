# OpsCopilot Evaluation Report

## 1. Evaluation Overview

OpsCopilot is evaluated using a controlled benchmark of synthetic production-style incidents.

The purpose of the evaluation is to determine whether the investigation agent can:

- Identify the correct incident type
- Retrieve relevant observability evidence
- Ground its conclusions in retrieved evidence
- Produce a coherent root-cause hypothesis
- Avoid unsupported causal claims

The evaluation combines exact keyword matching, evidence grounding, evidence coverage, and LLM-as-judge scoring.

## 2. Evaluation Architecture

The evaluation pipeline is:

```text
Synthetic Incident
       ↓
Ground-Truth Label
       ↓
OpsCopilot Investigation
       ↓
Metric Collection
       ↓
Log Retrieval
       ↓
Deployment Retrieval
       ↓
Evidence Preparation
       ↓
Root-Cause Hypothesis
       ↓
Exact-Match Scoring
       ↓
Evidence Grounding
       ↓
LLM-as-Judge
       ↓
Evaluation Report
```

The benchmark is designed to evaluate the complete investigation pipeline rather than only the final language-model response.

## 3. Benchmark Design

The current benchmark contains eight synthetic incident scenarios.

| Incident ID | Incident Type | Primary Metric | Log Query |
|---|---|---|---|
| INC001 | VM operation failure | CPU usage | VM operation failure |
| INC002 | Memory leak / OOM | Memory usage | memory OOM |
| INC003 | Deployment error | Error rate | deployment error |
| INC004 | Latency degradation | Request latency | latency degradation |
| INC005 | Cascading service failure | Error rate | cascading service failure |
| INC006 | CPU saturation | CPU usage | CPU saturation |
| INC007 | Disk/storage pressure | Disk usage | disk storage |
| INC008 | Network connectivity failure | Network error rate | network connectivity failure |

Each incident contains:

- Incident ID
- Incident type
- Affected entity
- Incident start time
- Incident end time
- Ground-truth description
- Expected keywords
- Expected evidence
- Associated metric
- Incident-specific log query

## 4. Ground-Truth Scenarios

### INC001 — VM Operation Failure

Expected root cause:

```text
VM operation failure
```

Expected evidence includes:

- CPU metric anomaly
- VM operation failure
- ERROR log evidence

### INC002 — Memory Leak / OOM

Expected root cause:

```text
Memory leak / out-of-memory condition
```

Expected evidence includes:

- Memory metric anomaly
- Memory-related evidence
- OOM evidence

### INC003 — Deployment Error

Expected root cause:

```text
Deployment error
```

Expected evidence includes:

- Error-rate anomaly
- Deployment evidence
- ERROR logs

### INC004 — Latency Degradation

Expected root cause:

```text
Latency degradation
```

Expected evidence includes:

- Request latency anomaly
- Latency-related logs
- Slow request evidence

### INC005 — Cascading Service Failure

Expected root cause:

```text
Cascading service failure
```

Expected evidence includes:

- Error-rate anomaly
- Upstream service evidence
- Downstream service evidence

### INC006 — CPU Saturation

Expected root cause:

```text
CPU saturation
```

Expected evidence includes:

- CPU metric anomaly
- CPU-related evidence
- Timeout evidence

### INC007 — Disk / Storage Pressure

Expected root cause:

```text
Disk/storage pressure
```

Expected evidence includes:

- Disk usage anomaly
- Disk-related evidence
- I/O evidence

### INC008 — Network Connectivity Failure

Expected root cause:

```text
Network connectivity failure
```

Expected evidence includes:

- Network error-rate anomaly
- Connection-related evidence
- Network-related logs

## 5. Evaluation Metrics

The evaluation uses four main groups of metrics.

### 5.1 Exact-Match Accuracy

Exact-match evaluation checks whether the generated hypothesis contains the expected benchmark keywords.

The metric is:

```text
Exact-Match Accuracy
=
Correctly matched incidents
/
Total incidents
```

This metric is intentionally strict and can miss semantically equivalent wording.

For example:

```text
Expected: OOM
Generated: out-of-memory condition
```

may be semantically correct but fail a literal keyword check.

### 5.2 Grounded Accuracy

Grounded accuracy checks whether the generated conclusion is supported by evidence retrieved during the investigation.

Evidence can include:

- Prometheus metric observations
- Retrieved log records
- Deployment information

The agent should not receive credit for a conclusion that is unsupported by the retrieved evidence.

### 5.3 Evidence Coverage

Evidence coverage measures how much of the expected evidence was represented in the investigation context.

The evaluation checks expected evidence terms against the evidence supplied to the reasoning layer.

### 5.4 LLM-as-Judge

The LLM judge evaluates the generated investigation using five dimensions:

1. Root-cause alignment
2. Reasoning coherence
3. Evidence grounding
4. Evidence completeness
5. Unsupported claims

The judge produces scores on a five-point scale.

The evaluation pass threshold is based on:

```text
Overall Score >= 3.5
AND
Root-Cause Alignment >= 3
AND
Evidence Grounding >= 3
```

## 6. Initial Evaluation Results

The initial benchmark run produced the following results:

| Incident | Exact Match | Grounded | LLM Judge | Result |
|---|---:|---:|---:|---|
| INC001 | True | True | 1.0 / 5 | Fail |
| INC002 | False | True | 5.0 / 5 | Pass |
| INC003 | True | True | 1.0 / 5 | Fail |
| INC004 | True | True | 1.0 / 5 | Fail |
| INC005 | True | True | 1.0 / 5 | Fail |
| INC006 | True | True | 5.0 / 5 | Pass |
| INC007 | True | True | 1.0 / 5 | Fail |
| INC008 | False | True | Error | Not judged |

## 7. Initial Aggregate Results

The initial evaluation produced:

```json
{
  "incident_count": 8,
  "exact_match_accuracy": 0.75,
  "grounded_accuracy": 1.0,
  "mean_evidence_coverage": 0.9167,
  "llm_judge": {
    "successful_judgments": 7,
    "judge_pass_rate": 0.2857,
    "mean_overall_score": 2.14
  }
}
```

Therefore:

```text
Total incidents:             8
Exact-match accuracy:        75.00%
Grounded accuracy:           100.00%
Mean evidence coverage:      91.67%
Successful LLM judgments:    7 / 8
LLM judge pass rate:         28.57%
Mean LLM judge score:        2.14 / 5
```

These values represent the initial completed benchmark run.

## 8. Exact-Match Failures

Two incidents failed the literal exact-match check.

### INC002

The agent generated wording equivalent to:

```text
out-of-memory condition
```

while the benchmark expected:

```text
OOM
```

The investigation was still grounded in the correct memory-related evidence.

This demonstrates a limitation of literal keyword matching: semantically equivalent terminology can be marked incorrect.

### INC008

The agent generated wording equivalent to:

```text
Network connectivity degraded
```

while the benchmark expected:

```text
Network connectivity failure
```

Again, the underlying investigation was grounded in the retrieved network evidence.

## 9. Grounding Results

The initial benchmark achieved:

```text
Grounded Accuracy = 100%
```

All eight investigations had evidence supporting their generated hypotheses.

This indicates that the agent was generally able to connect its conclusions to retrieved observability information.

However, grounded accuracy does not mean that every conclusion was perfectly phrased or causally proven.

A grounded hypothesis can still contain overly strong causal wording or include less relevant evidence.

## 10. LLM-as-Judge Results

The initial LLM judge results showed substantial variation.

Two investigations received a score of:

```text
5.0 / 5
```

These were:

- INC002
- INC006

The remaining successful judgments received lower scores, while INC008 produced a judge error.

The initial mean judge score was:

```text
2.14 / 5
```

with a pass rate of:

```text
28.57%
```

among the seven successful judgments.

## 11. Problems Identified by the Initial Evaluation

The initial evaluation revealed several important weaknesses.

### 11.1 Literal Keyword Sensitivity

The exact-match scorer was too dependent on literal terminology.

Examples include:

```text
OOM
vs.
out-of-memory condition
```

and:

```text
network connectivity failure
vs.
network connectivity degraded
```

These phrases can describe the same incident concept but are not identical strings.

### 11.2 Causal Overstatement

Some generated hypotheses used stronger causal language than the retrieved evidence justified.

For example, a model may describe an incident as:

```text
X caused Y
```

when the available evidence only establishes:

```text
X occurred during the same incident window as Y.
```

The evaluation therefore highlighted the importance of distinguishing correlation from confirmed causation.

### 11.3 Irrelevant Evidence

Some investigations included additional metrics or evidence that were not central to the benchmark scenario.

Extra evidence is not necessarily incorrect, but it can make the reasoning less focused.

### 11.4 Incident-Specific Evidence

INC005 demonstrated the importance of focusing on the evidence specific to the scenario.

For a cascading service failure, the important evidence includes:

```text
Upstream service degradation
        ↓
Upstream requests failing
        ↓
Downstream errors increasing
        ↓
Dependent services becoming unavailable
```

The investigation should prioritize this evidence instead of unrelated infrastructure signals.

## 12. Scorer Improvement

The evaluation scorer was subsequently revised.

The revised scorer was designed to better recognize semantic equivalents.

Examples include:

```text
out-of-memory ↔ OOM
network degraded ↔ network failure
high CPU ↔ CPU saturation
```

The revised judge prompt also instructs the evaluator to:

- Accept semantically equivalent terminology
- Avoid penalizing cautious wording
- Avoid penalizing non-contradictory additional metrics
- Focus on evidence relevant to the incident
- Distinguish correlation from confirmed causation

The scorer itself recomputes the overall score and pass decision rather than relying only on the LLM's final classification.

## 13. Post-Revision Validation

A complete eight-incident aggregate rerun after the scorer revision was not completed.

The evaluation process was interrupted during a local run because the LLM evaluation placed significant resource load on the development laptop.

Therefore, no updated eight-incident aggregate metrics are claimed for the revised scorer.

Two incidents were manually validated successfully after the revision:

```text
INC002
INC005
```

The revised evaluation logic also successfully produced improved judgments for the early incidents in the interrupted run.

The full revised benchmark should be rerun on a machine with sufficient resources before reporting a new aggregate score.

## 14. Where This Agent Gets It Wrong

This section documents known failure modes rather than hiding them.

### Failure 1: Terminology Mismatch

The agent can identify the correct concept but express it using terminology that does not exactly match the benchmark label.

Example:

```text
Ground Truth:
OOM

Agent:
out-of-memory condition
```

This can reduce exact-match accuracy even when the semantic interpretation is correct.

### Failure 2: Causal Language

The agent can sometimes use causal wording when the evidence only supports temporal correlation.

For example:

```text
Deployment caused the error increase.
```

may be stronger than the available evidence supports.

A safer interpretation is:

```text
The deployment occurred during the incident window and is
consistent with the observed increase in errors.
```

The system therefore treats root-cause outputs as hypotheses rather than confirmed causal diagnoses.

### Failure 3: Deployment Tool Coverage

The deployment retrieval tool can return no deployment records even when deployment-related evidence exists inside retrieved logs.

For example, an incident may contain log messages indicating:

```text
Deployment started
Deployment completed
HTTP 500 errors increased
Requests started failing
```

while the deployment-history tool itself returns:

```text
0 deployment records
```

This demonstrates that deployment evidence may currently be available through logs even when the dedicated deployment metadata source has no matching record.

### Failure 4: Resource Constraints

Running multiple LLM-based evaluations locally can place significant memory and CPU load on the development laptop.

The benchmark run was interrupted because of local resource constraints.

This is an engineering limitation of the current development environment rather than an intended behaviour of the agent.

### Failure 5: Small Benchmark

The current benchmark contains only eight synthetic incidents.

Although the scenarios cover different incident categories, a larger benchmark would provide stronger evidence about generalization.

## 15. Evaluation Reproducibility

The benchmark is designed to be reproducible.

The evaluation pipeline uses:

```text
Ground-Truth Incident Labels
        +
Synthetic Incident Logs
        +
Synthetic Metric Signals
        +
OpsCopilot Investigation Agent
        +
Deterministic Evaluation Logic
```

The benchmark labels and scoring code are stored in the repository.

The evaluation can be rerun using the project's evaluation script after the required services and Ollama model are available.

## 16. Evaluation Interpretation

The initial evaluation demonstrates several important characteristics of the system.

The agent achieved:

```text
75% exact-match accuracy
100% grounded accuracy
91.67% mean evidence coverage
```

in the completed initial benchmark.

The difference between exact-match accuracy and grounded accuracy is important.

The agent sometimes produced semantically correct conclusions using different wording from the benchmark labels.

At the same time, the initial LLM-as-judge results show that the quality of reasoning and presentation requires further refinement.

The evaluation therefore should not be interpreted as proof that the system can reliably diagnose real production incidents.

Instead, it demonstrates that the current prototype can perform structured, evidence-grounded investigation on a controlled synthetic benchmark.

## 17. Evaluation Limitations

The current evaluation has several limitations:

1. The benchmark incidents are synthetic.
2. The benchmark contains only eight scenarios.
3. Exact-match scoring is sensitive to terminology.
4. LLM-as-judge scores depend on the local Llama 3 evaluation model.
5. The complete revised benchmark was not rerun after the scorer change.
6. The development environment has limited local compute resources.
7. The evaluation does not represent real production incident distributions.
8. Root-cause hypotheses are not equivalent to confirmed causal diagnoses.

## 18. Future Evaluation Improvements

Future evaluation work should include:

- Increasing the number of benchmark incidents
- Adding more subtle failure scenarios
- Adding multi-service incidents
- Testing overlapping incident signals
- Testing noisy and incomplete logs
- Testing missing metrics
- Testing missing deployment metadata
- Improving semantic scoring
- Running repeated evaluation trials
- Comparing different LLMs
- Adding human evaluation
- Measuring investigation latency
- Measuring evidence retrieval precision and recall
- Evaluating robustness to irrelevant logs

A larger benchmark would provide a stronger assessment of the agent's generalization.

## 19. Final Evaluation Status

Current completed benchmark status:

```text
Benchmark scenarios:       8
Initial exact-match:       75.00%
Initial grounded accuracy: 100.00%
Mean evidence coverage:    91.67%
Successful LLM judgments:  7 / 8
Initial judge pass rate:   28.57%
Initial mean judge score:  2.14 / 5
```

The revised scorer has been implemented and partially validated, but the complete post-revision eight-incident benchmark has not yet been completed.

Therefore, the initial aggregate results remain the official recorded evaluation results for this report.

## 20. Conclusion

The evaluation shows that OpsCopilot can perform structured incident investigation by combining:

- Metric anomaly detection
- Semantic log retrieval
- Deployment information
- MCP observability tools
- LangGraph orchestration
- Llama 3 reasoning
- Evidence-grounded reporting

The strongest result from the initial benchmark was the ability to maintain evidence grounding across all eight incidents.

The main areas requiring improvement are:

- Semantic evaluation
- Reasoning focus
- Causal-language control
- Deployment metadata coverage
- Larger-scale evaluation
- Local resource requirements

The system is therefore best described as a prototype AI SRE investigation assistant that performs evidence-grounded root-cause analysis on a controlled synthetic benchmark.

It should not be presented as a production-ready autonomous incident diagnosis system.