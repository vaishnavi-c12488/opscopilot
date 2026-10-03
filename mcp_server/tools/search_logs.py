from __future__ import annotations

from retrieval.vector_store import VectorStore


def search_logs(
    query: str,
    start_time: str,
    end_time: str,
    limit: int = 5,
) -> dict:
    """
    Search logs through Qdrant and return JSON-serializable evidence.

    The MCP layer deliberately converts Qdrant ScoredPoint objects into
    dictionaries so downstream agents can reliably inspect and cite
    individual log records.
    """

    try:
        store = VectorStore()

        results = store.search_logs(
            query=query,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
        )

        structured_results = []

        for result in results:
            payload = getattr(result, "payload", None) or {}

            structured_results.append(
                {
                    "id": str(getattr(result, "id", "")),
                    "score": float(getattr(result, "score", 0.0)),
                    "timestamp": payload.get("timestamp"),
                    "source": payload.get("source"),
                    "service": payload.get("service"),
                    "level": payload.get("level"),
                    "entity_id": payload.get("entity_id"),
                    "message": payload.get("message"),
                    "log_file": payload.get("log_file"),
                    "line_number": payload.get("line_number"),
                    "pid": payload.get("pid"),
                    "status": payload.get("status"),
                    "response_time": payload.get("response_time"),
                    "incident_id": payload.get("incident_id"),
                    "synthetic": payload.get("synthetic", False),
                }
            )

        return {
            "status": "success",
            "query": query,
            "start_time": start_time,
            "end_time": end_time,
            "result_count": len(structured_results),
            "data": structured_results,
        }

    except Exception as exc:
        return {
            "status": "error",
            "query": query,
            "start_time": start_time,
            "end_time": end_time,
            "result_count": 0,
            "message": f"Log search failed: {exc}",
            "data": [],
        }