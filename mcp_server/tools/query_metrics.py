import requests


PROMETHEUS_URL = "http://localhost:9090"


def query_metrics(
    metric_name: str,
    start_time: str,
    end_time: str,
    step_seconds: int = 2
) -> dict:
    """
    Query Prometheus for a metric over a time window.
    """

    url = f"{PROMETHEUS_URL}/api/v1/query_range"

    params = {
        "query": metric_name,
        "start": start_time,
        "end": end_time,
        "step": step_seconds
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=10
        )

        response.raise_for_status()

        result = response.json()

    except requests.RequestException as exc:

        return {
            "status": "error",
            "metric": metric_name,
            "message": (
                f"Prometheus request failed: {exc}"
            ),
            "data": []
        }

    if result.get("status") != "success":

        return {
            "status": "error",
            "metric": metric_name,
            "message": (
                "Prometheus returned an "
                "unsuccessful response."
            ),
            "data": []
        }

    result_data = result.get(
        "data",
        {}
    )

    series = result_data.get(
        "result",
        []
    )

    if not series:

        return {
            "status": "success",
            "metric": metric_name,
            "start_time": start_time,
            "end_time": end_time,
            "sample_count": 0,
            "message": (
                "No metric data found "
                "in the requested window."
            ),
            "data": []
        }

    values = []

    for series_item in series:

        labels = series_item.get(
            "metric",
            {}
        )

        for timestamp, value in series_item.get(
            "values",
            []
        ):

            values.append(
                {
                    "timestamp": float(
                        timestamp
                    ),
                    "value": float(
                        value
                    ),
                    "labels": labels
                }
            )

    return {
        "status": "success",
        "metric": metric_name,
        "start_time": start_time,
        "end_time": end_time,
        "sample_count": len(values),
        "data": values
    }