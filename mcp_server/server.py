from mcp.server import MCPServer

from mcp_server.tools.query_metrics import (
    query_metrics
)

from mcp_server.tools.search_logs import (
    search_logs
)

from mcp_server.tools.get_recent_deploys import (
    get_recent_deploys
)


# ---------------------------------------------------------
# MCP Server
# ---------------------------------------------------------

mcp = MCPServer(
    "OpsCopilot MCP Server"
)


# ---------------------------------------------------------
# Tool 1 — Query Metrics
# ---------------------------------------------------------

@mcp.tool()
def query_metrics_tool(
    metric_name: str,
    start_time: str,
    end_time: str,
    step_seconds: int = 2
) -> dict:
    """
    Query Prometheus metrics during an incident
    time window.
    """

    return query_metrics(
        metric_name=metric_name,
        start_time=start_time,
        end_time=end_time,
        step_seconds=step_seconds
    )


# ---------------------------------------------------------
# Tool 2 — Search Logs
# ---------------------------------------------------------

@mcp.tool()
def search_logs_tool(
    query: str,
    start_time: str,
    end_time: str,
    limit: int = 5
) -> dict:
    """
    Search operational logs using semantic similarity
    and incident time-window filtering.
    """

    return search_logs(
        query=query,
        start_time=start_time,
        end_time=end_time,
        limit=limit
    )


# ---------------------------------------------------------
# Tool 3 — Recent Deployments
# ---------------------------------------------------------

@mcp.tool()
def get_recent_deploys_tool(
    start_time: str,
    end_time: str
) -> dict:
    """
    Retrieve deployment events occurring around
    an incident.
    """

    return get_recent_deploys(
        start_time=start_time,
        end_time=end_time
    )


# ---------------------------------------------------------
# Start MCP Server
# ---------------------------------------------------------

if __name__ == "__main__":
    mcp.run()