"""
OpsCopilot Console
==================
AI SRE Copilot for Observability & Root-Cause Analysis.

Presentation layer ONLY. This app talks to the existing FastAPI service
(GET /health, POST /v1/investigate) and renders what comes back. It contains
no agent, MCP, retrieval or LLM logic.

Run:
    streamlit run console/streamlit_app.py

Configuration (environment variables, all optional):
    OPSCOPILOT_API_URL   FastAPI base URL        (default http://127.0.0.1:8000)
    OPSCOPILOT_TIMEOUT   Investigation timeout s (default 600)
"""

from __future__ import annotations

import base64
import concurrent.futures
import html
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

import altair as alt
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEFAULT_API_URL = os.getenv("OPSCOPILOT_API_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT_S = float(os.getenv("OPSCOPILOT_TIMEOUT", "600"))
HEALTH_TIMEOUT_S = 3.0

# Form defaults mirror the documented request schema of POST /v1/investigate.
# Benchmark incident presets. Selecting an incident updates every dependent
# request field together, so the UI can never send a previous incident's
# window/metric/query after the Incident ID changes.
INCIDENT_PRESETS: dict[str, dict[str, str]] = {
    "INC001": {
        "f_start": "2026-09-29T13:20:20.608701+00:00",
        "f_end": "2026-09-29T13:20:36.612979+00:00",
        "f_entity": "vm-eval-001",
        "f_source": "openstack",
        "f_metric": "opscopilot_cpu_usage_percent",
        "f_query": "failure error operation failed",
    },
    "INC002": {
        "f_start": "2026-09-29T13:20:56.625899+00:00",
        "f_end": "2026-09-29T13:21:12.630436+00:00",
        "f_entity": "vm-eval-002",
        "f_source": "openstack",
        "f_metric": "opscopilot_memory_usage_percent",
        "f_query": "memory OOM",
    },
    "INC003": {
        "f_start": "2026-09-29T13:21:32.638820+00:00",
        "f_end": "2026-09-29T13:21:48.644872+00:00",
        "f_entity": "service-eval-003",
        "f_source": "openstack",
        "f_metric": "opscopilot_error_rate_percent",
        "f_query": "deployment error",
    },
    "INC004": {
        "f_start": "2026-09-29T13:22:08.669397+00:00",
        "f_end": "2026-09-29T13:22:24.674755+00:00",
        "f_entity": "service-eval-004",
        "f_source": "openstack",
        "f_metric": "opscopilot_request_latency_seconds",
        "f_query": "latency degradation",
    },
    "INC005": {
        "f_start": "2026-09-29T13:22:44.685833+00:00",
        "f_end": "2026-09-29T13:23:00.690959+00:00",
        "f_entity": "service-eval-005",
        "f_source": "openstack",
        "f_metric": "opscopilot_error_rate_percent",
        "f_query": "cascading service failure",
    },
    "INC006": {
        "f_start": "2026-09-29T13:23:20.721548+00:00",
        "f_end": "2026-09-29T13:23:36.728462+00:00",
        "f_entity": "vm-eval-006",
        "f_source": "openstack",
        "f_metric": "opscopilot_cpu_usage_percent",
        "f_query": "CPU saturation",
    },
    "INC007": {
        "f_start": "2026-09-29T13:23:56.737765+00:00",
        "f_end": "2026-09-29T13:24:12.749155+00:00",
        "f_entity": "vm-eval-007",
        "f_source": "openstack",
        "f_metric": "opscopilot_disk_usage_percent",
        "f_query": "disk storage",
    },
    "INC008": {
        "f_start": "2026-09-29T13:24:32.759396+00:00",
        "f_end": "2026-09-29T13:24:48.768087+00:00",
        "f_entity": "service-eval-008",
        "f_source": "openstack",
        "f_metric": "opscopilot_network_error_rate_percent",
        "f_query": "network connectivity failure",
    },
}

FORM_DEFAULTS: dict[str, str] = {
    "f_incident": "INC001",
    **INCIDENT_PRESETS["INC001"],
}

# Palette (kept in sync with the CSS tokens below).
C_CYAN = "#4cc9f0"
C_AMBER = "#f2b84b"
C_RED = "#f0616d"
C_GREEN = "#4fd18b"
C_MUTED = "#7d8896"
C_GRID = "#222c38"
C_TEXT = "#d5dde6"

CITE_RE = re.compile(r"\[(METRIC|LOG|DEPLOY|DEPLOYMENT)\s*[:|][^\[\]]*\]", re.IGNORECASE)

# The wide-layout keyword changed across Streamlit versions.
_ST_VERSION = tuple(int(p) for p in re.findall(r"\d+", st.__version__)[:2])
WIDE: dict[str, Any] = (
    {"width": "stretch"} if _ST_VERSION >= (1, 50) else {"use_container_width": True}
)

# --------------------------------------------------------------------------- #
# Styling
# --------------------------------------------------------------------------- #

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
  --bg: #0c1117; --panel: #121922; --panel2: #161f2a; --line: #222c38;
  --text: #d5dde6; --muted: #7d8896; --cyan: #4cc9f0; --amber: #f2b84b;
  --red: #f0616d; --green: #4fd18b; --cite-log: #8fa3ff; --cite-dep: #c39bff;
  --mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --sans: 'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;
}
html { font-size: 17.5px !important; }
.stApp { background: var(--bg); color: var(--text); font-family: var(--sans); }
[data-testid="stHeader"] { background: transparent; }
.block-container { padding: 1.1rem 2rem 3rem 2rem; max-width: 100% !important; width: 100%; }
[data-testid="stSidebar"] { background: var(--panel); border-right: 1px solid var(--line); }
[data-testid="stSidebar"] .block-container { padding-top: 1rem; }
h1, h2, h3, h4 { font-family: var(--sans); color: var(--text); }
code, pre, .mono { font-family: var(--mono) !important; }

/* inputs */
.stTextInput input, .stTextArea textarea {
  background: var(--bg) !important; border: 1px solid var(--line) !important;
  font-family: var(--mono) !important; font-size: 15px !important; color: var(--text) !important;
}
.stTextInput input:focus { border-color: var(--cyan) !important; }
.stTextInput label p, .stTextArea label p { font-size: 15px !important; color: var(--muted); }

/* buttons */
[data-testid="stBaseButton-primary"], button[kind="primary"] {
  background: var(--cyan) !important; color: #06222b !important; border: 0 !important;
  font-weight: 600; letter-spacing: .04em; border-radius: 4px;
}
[data-testid="stBaseButton-secondary"], button[kind="secondary"] {
  background: transparent !important; border: 1px solid var(--line) !important;
  color: var(--muted) !important; border-radius: 4px; letter-spacing: .04em;
}
button:focus-visible { outline: 2px solid var(--cyan) !important; outline-offset: 2px; }

/* tabs / expanders */
.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--line); }
.stTabs [data-baseweb="tab"] { font-family: var(--mono); font-size: 15px !important; color: var(--muted); }
.stTabs [aria-selected="true"] { color: var(--cyan) !important; }
[data-testid="stExpander"] { border: 1px solid var(--line); border-radius: 4px; background: var(--panel); }

/* masthead */
.mast { display:flex; align-items:center; justify-content:space-between; gap:24px;
  padding-bottom:12px; border-bottom:1px solid var(--line); margin-bottom:18px; flex-wrap:wrap; }
.brand { display:flex; align-items:center; gap:12px; }
.brand img { width:38px; height:38px; }
.brand-name { font-weight:600; font-size: 22px !important; letter-spacing:.14em; line-height:1.1; }
.brand-sub { color:var(--muted); font-size: 14px !important; margin-top:2px; }
.chips { display:flex; gap:8px; flex-wrap:wrap; }
.chip { font-family:var(--mono); font-size: 13px !important; padding:4px 9px; border:1px solid var(--line);
  border-radius:3px; color:var(--muted); background:var(--panel); white-space:nowrap; }
.chip.ok { color:var(--green); } .chip.bad { color:var(--red); border-color:#4a2329; }
.chip .dot { margin-right:6px; }

/* section titles */
.sec { margin:26px 0 10px; display:flex; align-items:baseline; gap:12px;
  border-bottom:1px solid var(--line); padding-bottom:6px; }
.sec h3 { margin:0; font-size: 18px !important; font-weight:600; letter-spacing:.12em; color:var(--text); }
.sec span { color:var(--muted); font-size: 14px !important; }
.lbl { font-size: 13px !important; letter-spacing:.1em; color:var(--muted); margin-bottom:4px; font-weight:500; }

/* incident header */
.inc-title { display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
.inc-id { font-family:var(--mono); font-size: 38px !important; font-weight:600; letter-spacing:.02em; }
.badge { font-family:var(--mono); font-size: 13px !important; padding:3px 8px; border-radius:3px;
  border:1px solid var(--line); color:var(--cyan); letter-spacing:.06em; }
.badge.ok { color:var(--green); border-color:#22503b; } .badge.bad { color:var(--red); border-color:#4a2329; }
.inc-line { font-family:var(--mono); font-size: 16px !important; color:var(--text); margin-top:6px; }
.inc-line .m { color:var(--muted); }
.meta { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:1px;
  background:var(--line); border:1px solid var(--line); border-radius:4px; margin-top:14px; overflow:hidden; }
.meta div { background:var(--panel); padding:8px 12px; min-width:0; }
.meta b { display:block; font-weight:500; font-size: 13px !important; letter-spacing:.1em; color:var(--muted); }
.meta span { font-family:var(--mono); font-size: 15px !important; word-break:break-word; }

/* pipeline */
.pipe { display:grid; grid-template-columns:repeat(5,1fr); gap:0; border:1px solid var(--line);
  border-radius:4px; overflow:hidden; background:var(--panel); }
.stage { padding:12px 14px; border-right:1px solid var(--line); min-width:0; position:relative; }
.stage:last-child { border-right:0; }
.stage .top { display:flex; justify-content:space-between; align-items:center; }
.stage .num { font-family:var(--mono); font-size: 13px !important; color:var(--muted); }
.stage .ico { font-family:var(--mono); font-size: 20px !important; color:var(--muted); }
.stage .name { font-weight:600; font-size: 15px !important; letter-spacing:.1em; margin-top:6px; }
.stage .desc { font-size: 14px !important; color:var(--muted); margin-top:3px; min-height:2.2em; }
.stage .st { font-family:var(--mono); font-size: 13px !important; margin-top:8px; letter-spacing:.05em; }
.stage.done { box-shadow: inset 0 3px 0 var(--cyan); } .stage.done .ico, .stage.done .st { color:var(--cyan); }
.stage.empty { box-shadow: inset 0 3px 0 var(--amber); } .stage.empty .ico, .stage.empty .st { color:var(--amber); }
.stage.missing { box-shadow: inset 0 3px 0 var(--line); }
@media (max-width: 900px) { .pipe { grid-template-columns:1fr; } .stage { border-right:0; border-bottom:1px solid var(--line);} }

/* panels */
.panel { background:var(--panel); border:1px solid var(--line); border-radius:4px; padding:14px 16px; height:100%; }
.panel.hyp { border-left:3px solid var(--amber); }
.panel.obs { border-left:3px solid var(--cyan); }
.panel p, .panel li { font-size: 16px !important; line-height:1.55; margin:0 0 6px; }
.panel ul { padding-left:18px; margin:0; }
.muted { color:var(--muted); }
.note { font-size: 13px !important; color:var(--muted); border-left:2px solid var(--line); padding:2px 10px; margin-top:8px; }
.nodata { border:1px dashed var(--line); border-radius:4px; padding:14px 16px; color:var(--muted);
  font-size: 15px !important; background:var(--panel); }
.nodata b { color:var(--text); font-weight:500; }

/* confidence */
.conf { display:flex; align-items:center; gap:12px; }
.conf .bars { display:flex; gap:3px; align-items:flex-end; }
.conf .bars i { width:8px; background:var(--line); display:block; border-radius:1px; }
.conf .bars i:nth-child(1){height:10px} .conf .bars i:nth-child(2){height:16px} .conf .bars i:nth-child(3){height:22px}
.conf .txt { font-family:var(--mono); font-weight:600; letter-spacing:.06em; font-size: 18px !important; }

/* citations */
.cite { display:inline-block; font-family:var(--mono); font-size: 13px !important; padding:1px 6px; margin:1px 2px;
  border:1px solid var(--line); border-radius:3px; background:var(--bg); color:var(--cyan); }
.cite.log { color:var(--cite-log); } .cite.deploy { color:var(--cite-dep); }
.evrow { display:flex; gap:10px; padding:6px 0; border-bottom:1px solid var(--line); align-items:baseline; }
.evrow:last-child { border-bottom:0; }
.evrow .k { font-family:var(--mono); font-size: 13px !important; min-width:96px; color:var(--cyan); }
.evrow .k.log { color:var(--cite-log); } .evrow .k.deploy { color:var(--cite-dep); }
.evrow .v { font-family:var(--mono); font-size: 15px !important; word-break:break-word; }

/* logs */
details.log { background:var(--panel); border:1px solid var(--line); border-radius:4px; margin-bottom:6px; }
details.log summary { cursor:pointer; padding:8px 12px; display:flex; gap:12px; align-items:baseline;
  list-style:none; font-family:var(--mono); font-size: 15px !important; }
details.log summary::-webkit-details-marker { display:none; }
details.log summary:focus-visible { outline:2px solid var(--cyan); }
details.log .t { color:var(--muted); min-width:96px; }
details.log .lv { min-width:76px; font-weight:600; color:var(--muted); }
details.log .svc { color:var(--muted); min-width:250px; }
details.log .msg { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-family:var(--sans); font-size: 15px !important; }
details.log .sc { color:var(--cyan); }
details.log.error { border-left:3px solid var(--red); background:#1a1216; }
details.log.error .lv { color:var(--red); }
details.log.warn { border-left:3px solid var(--amber); } details.log.warn .lv { color:var(--amber); }
details.log .body { padding:6px 14px 12px; border-top:1px solid var(--line); }
details.log .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:8px; margin:8px 0; }
details.log .grid b { display:block; font-size: 13px !important; letter-spacing:.1em; color:var(--muted); font-weight:500; }
details.log .grid span { font-family:var(--mono); font-size: 14px !important; word-break:break-all; }
details.log pre { background:var(--bg); border:1px solid var(--line); border-radius:3px; padding:8px 10px;
  font-size: 13px !important; color:var(--muted); overflow-x:auto; margin:6px 0 0; }
.logmsg { font-family:var(--sans); font-size: 16px !important; margin:6px 0; }

/* timeline */
.tl { border:1px solid var(--line); border-radius:4px; background:var(--panel); padding:8px 16px 10px; }
.tl-item { display:grid; grid-template-columns:116px 22px 1fr; min-height:52px; }
.tl-time { font-family:var(--mono); font-size: 14px !important; color:var(--muted); padding-top:10px; }
.tl-rail { position:relative; }
.tl-rail::before { content:''; position:absolute; left:10px; top:0; bottom:0; width:1px; background:var(--line); }
.tl-item:first-child .tl-rail::before { top:18px; } .tl-item:last-child .tl-rail::before { bottom:calc(100% - 18px); }
.tl-rail i { position:absolute; left:5px; top:14px; width:11px; height:11px; border-radius:50%;
  background:var(--bg); border:2px solid var(--cyan); }
.tl-item.log .tl-rail i { border-color:var(--cite-log); border-radius:2px; }
.tl-item.err .tl-rail i { border-color:var(--red); background:var(--red); border-radius:2px; }
.tl-item.deploy .tl-rail i { border-color:var(--cite-dep); transform:rotate(45deg); border-radius:1px; }
.tl-item.hyp .tl-rail i { border-color:var(--amber); background:var(--amber); }
.tl-body { padding:8px 0 10px 8px; min-width:0; }
.tl-kind { font-family:var(--mono); font-size: 13px !important; letter-spacing:.08em; color:var(--cyan); }
.tl-item.log .tl-kind { color:var(--cite-log); } .tl-item.err .tl-kind { color:var(--red); }
.tl-item.deploy .tl-kind { color:var(--cite-dep); } .tl-item.hyp .tl-kind { color:var(--amber); }
.tl-text { font-size: 16px !important; word-break:break-word; margin-top:1px; }
.tl-text .mono { font-size: 15px !important; }

/* empty state */
.empty-wrap { max-width:100%; margin:6vh 0 0; }
.empty-wrap .flow div { flex:1; text-align:center; }
.empty-wrap h2 { font-size: 32px !important; font-weight:600; margin:0; }
.empty-wrap .q { color:var(--cyan); font-family:var(--mono); margin:6px 0 22px; font-size: 19px !important; }
.flow { display:flex; align-items:stretch; gap:0; margin:8px 0 18px; flex-wrap:wrap; }
.flow div { border:1px solid var(--line); background:var(--panel); padding:10px 16px; font-family:var(--mono);
  font-size: 15px !important; margin-right:-1px; }
.flow div.ai { color:var(--amber); }
.empty-wrap p { color:var(--muted); font-size: 17px !important; line-height:1.6; max-width:880px; }

/* error */
.err { border:1px solid #4a2329; border-left:3px solid var(--red); background:#1a1216; border-radius:4px; padding:14px 16px; }
.err h4 { margin:0 0 6px; font-family:var(--mono); letter-spacing:.08em; font-size: 17px !important; color:var(--red); }
.err p { margin:4px 0; font-size: 16px !important; }
/* readability: native Streamlit elements (each is larger than Streamlit's default) */
.stApp { font-size: 15px !important; }
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li { font-size: 16px !important; line-height: 1.55; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { font-size: 15px !important; }
[data-testid="stMetricLabel"] p { font-size: 15px !important; color: var(--muted); }
[data-testid="stMetricValue"] { font-family: var(--mono); font-size: 34px !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { font-size: 13px !important; }
[data-testid="stExpander"] summary p { font-size: 16px !important; }
[data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-secondary"] p, .stDownloadButton button p { font-size: 15px !important; }
[data-testid="stCode"] code, [data-testid="stCodeBlock"] code { font-size: 14px !important; }
</style>
"""

# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def esc(value: Any) -> str:
    """HTML-escape any value for safe injection into markup."""
    return html.escape("" if value is None else str(value), quote=True)


def render_html(markup: str) -> None:
    """Render raw HTML. Callers must escape all dynamic text with esc()."""
    st.markdown(markup, unsafe_allow_html=True)


def section_title(title: str, hint: str = "") -> None:
    hint_html = f"<span>{esc(hint)}</span>" if hint else ""
    render_html(f'<div class="sec"><h3>{esc(title)}</h3>{hint_html}</div>')


def nodata(headline: str, detail: str = "") -> None:
    detail_html = f"<br>{esc(detail)}" if detail else ""
    render_html(f'<div class="nodata"><b>{esc(headline)}</b>{detail_html}</div>')


def fmt_num(value: Optional[float]) -> str:
    if value is None:
        return "-"
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def parse_ts(value: Any) -> Optional[datetime]:
    """Best-effort timestamp parsing (ISO strings, epoch seconds/millis)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / 1000.0 if float(value) > 1e12 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                return parse_ts(float(text))
            except ValueError:
                return None
    return None


def fmt_dt(dt: Optional[datetime], with_date: bool = True) -> str:
    if dt is None:
        return "-"
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S" if with_date else "%H:%M:%S")


def fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}m {rest:02d}s"


def walk_dicts(obj: Any) -> Iterator[dict]:
    """Yield every dict nested anywhere inside obj (including obj itself)."""
    if isinstance(obj, dict):
        yield obj
        for child in obj.values():
            yield from walk_dicts(child)
    elif isinstance(obj, list):
        for child in obj:
            yield from walk_dicts(child)


def walk_lists(obj: Any) -> Iterator[list]:
    if isinstance(obj, list):
        yield obj
        for child in obj:
            yield from walk_lists(child)
    elif isinstance(obj, dict):
        for child in obj.values():
            yield from walk_lists(child)


def pick(entry: dict, *names: str) -> Any:
    """Read the first present field from entry, entry['payload'] or similar."""
    scopes = [entry] + [entry[k] for k in ("payload", "metadata", "fields", "labels") if isinstance(entry.get(k), dict)]
    for scope in scopes:
        for name in names:
            if scope.get(name) not in (None, ""):
                return scope[name]
    return None


def svg_data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


BRAND_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
    '<rect x="1" y="1" width="38" height="38" rx="5" fill="#121922" stroke="#4cc9f0" stroke-width="1.5"/>'
    '<path d="M7 26 L13 20 L7 14" fill="none" stroke="#4cc9f0" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
    '<path d="M17 27 L21 27 L24 13 L28 29 L31 22 L34 22" fill="none" stroke="#d5dde6" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
    "</svg>"
)

# --------------------------------------------------------------------------- #
# API layer (the ONLY place that talks to the backend)
# --------------------------------------------------------------------------- #


@st.cache_data(ttl=10, show_spinner=False)
def check_health(base_url: str) -> dict[str, Any]:
    """GET /health. Result is cached for 10 s so reruns stay cheap."""
    try:
        response = requests.get(f"{base_url}/health", timeout=HEALTH_TIMEOUT_S)
        try:
            body = response.json()
        except ValueError:
            body = {}
        return {"reachable": response.ok, "http": response.status_code, "body": body, "error": None}
    except requests.RequestException as exc:
        return {"reachable": False, "http": None, "body": {}, "error": f"{type(exc).__name__}: {exc}"}


_OK_WORDS = {"ok", "up", "healthy", "connected", "ready", "available", "running", "success", "true"}
_BAD_WORDS = {"down", "error", "unhealthy", "unavailable", "disconnected", "failed", "false", "degraded"}


def service_state(body: Any, keywords: tuple[str, ...]) -> Optional[bool]:
    """
    Look for a dependency in the /health payload. Returns True/False when the
    payload explicitly reports it, or None when it does not (never guessed).
    """
    for node in walk_dicts(body):
        for key, value in node.items():
            if not any(word in str(key).lower() for word in keywords):
                continue
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in _OK_WORDS:
                    return True
                if lowered in _BAD_WORDS:
                    return False
            if isinstance(value, dict):
                for inner in ("status", "ok", "connected", "healthy", "state"):
                    if inner in value:
                        return service_state({key: value[inner]}, keywords)
    return None


def call_investigate(base_url: str, payload: dict[str, Any]) -> requests.Response:
    return requests.post(f"{base_url}/v1/investigate", json=payload, timeout=REQUEST_TIMEOUT_S)


def error_from_response(response: requests.Response) -> dict[str, str]:
    """Translate an HTTP error into a user-facing message + technical detail."""
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    detail = body.get("detail") if isinstance(body, dict) else None
    code = response.status_code
    if code == 422 and isinstance(detail, list):
        parts = []
        for item in detail:
            loc = ".".join(str(p) for p in item.get("loc", [])[1:]) or "request"
            parts.append(f"{loc}: {item.get('msg', 'invalid value')}")
        return {
            "title": "VALIDATION ERROR (422)",
            "message": "The API rejected the request: " + "; ".join(parts),
            "hint": "Correct the highlighted fields in the sidebar and run the investigation again.",
            "details": json.dumps(body, indent=2, default=str),
        }
    if code == 400:
        return {
            "title": "INVALID REQUEST (400)",
            "message": str(detail) if detail else "The API rejected the investigation request.",
            "hint": "Check the incident window, metric name and log query.",
            "details": json.dumps(body, indent=2, default=str)[:4000],
        }
    if code >= 500:
        return {
            "title": f"BACKEND ERROR ({code})",
            "message": "The investigation service failed while processing the request.",
            "hint": "Check the FastAPI logs, then confirm Prometheus, Qdrant and Ollama are running.",
            "details": (json.dumps(body, indent=2, default=str) if not isinstance(body, str) else body)[:4000],
        }
    return {
        "title": f"REQUEST FAILED ({code})",
        "message": str(detail) if detail else "The API returned an unexpected status.",
        "hint": "Open the API docs to inspect the endpoint contract.",
        "details": (json.dumps(body, indent=2, default=str) if not isinstance(body, str) else body)[:4000],
    }


def error_from_exception(exc: BaseException, base_url: str) -> dict[str, str]:
    if isinstance(exc, requests.ConnectionError):
        return {
            "title": "BACKEND UNAVAILABLE",
            "message": "OpsCopilot could not reach the FastAPI investigation service.",
            "hint": f"Start the API (for example: uvicorn on port 8000) and confirm {base_url}/health responds.",
            "details": f"{type(exc).__name__}: {exc}",
        }
    if isinstance(exc, requests.Timeout):
        return {
            "title": "INVESTIGATION TIMED OUT",
            "message": f"No response within {int(REQUEST_TIMEOUT_S)} s. The LLM step may still be running or Ollama may be overloaded.",
            "hint": "Check that Ollama has the model loaded, or raise OPSCOPILOT_TIMEOUT.",
            "details": f"{type(exc).__name__}: {exc}",
        }
    return {
        "title": "UNEXPECTED CLIENT ERROR",
        "message": "The console failed while calling the investigation API.",
        "hint": "Retry. If it persists, inspect the technical details.",
        "details": f"{type(exc).__name__}: {exc}",
    }


# --------------------------------------------------------------------------- #
# Response model (defensive parsing of the API payload)
# --------------------------------------------------------------------------- #

TIME_KEYS = ("timestamp", "time", "ts", "t", "datetime", "@timestamp")
VALUE_KEYS = ("value", "val", "v")
ANOMALY_KEYS = ("anomaly", "anomalies", "anomaly_detected", "is_anomaly", "anomalous", "anomaly_score")


@dataclass
class MetricData:
    name: str
    df: pd.DataFrame
    anomaly: dict[str, Any]
    error: Optional[str]
    raw: Any


@dataclass
class LogEntry:
    timestamp: Optional[datetime]
    service: str
    level: str
    entity_id: str
    message: str
    score: Optional[float]
    incident_id: str
    raw: dict


@dataclass
class Deployment:
    deployment_id: str
    service: str
    version: str
    timestamp: Optional[datetime]
    status: str
    raw: dict


@dataclass
class Citation:
    kind: str
    content: str
    token: str


@dataclass
class Model:
    raw: dict
    inv: dict
    incident_id: str
    api_status: str
    processing_time: Optional[float]
    source: str
    start: Optional[datetime]
    end: Optional[datetime]
    entity: str
    metric_name: str
    log_query: str
    metric: MetricData
    logs: list[LogEntry]
    logs_error: Optional[str]
    deploys: list[Deployment]
    deploy_count: int
    deploy_error: Optional[str]
    evidence_context: str
    hypothesis: str
    final_report: str
    sections: dict[str, str] = field(default_factory=dict)
    confidence: Optional[str] = None
    citations: list[Citation] = field(default_factory=list)


def _extract_metric_rows(metric_result: Any) -> list[tuple[Any, Any, Any]]:
    """Return (timestamp, value, labels) rows from Prometheus-style or flat payloads."""
    rows: list[tuple[Any, Any, Any]] = []
    # 1) Prometheus matrix/vector: {"metric": {...}, "values": [[ts, "v"], ...]}
    for node in walk_dicts(metric_result):
        values = node.get("values")
        if isinstance(values, list) and values and all(isinstance(v, (list, tuple)) and len(v) == 2 for v in values):
            labels = node.get("metric") or node.get("labels") or {}
            rows.extend((ts, val, labels) for ts, val in values)
        elif isinstance(node.get("value"), (list, tuple)) and len(node["value"]) == 2 and "metric" in node:
            rows.append((node["value"][0], node["value"][1], node.get("metric") or {}))
    if rows:
        return rows
    # 2) Flat list of dicts with a time key and a value key.
    for candidate in walk_lists(metric_result):
        dicts = [c for c in candidate if isinstance(c, dict)]
        if not dicts or len(dicts) != len(candidate):
            continue
        if any(pick(d, *TIME_KEYS) is not None and pick(d, *VALUE_KEYS) is not None for d in dicts):
            for d in dicts:
                ts, val = pick(d, *TIME_KEYS), pick(d, *VALUE_KEYS)
                if ts is None or val is None:
                    continue
                labels = d.get("labels") or d.get("metric") or {k: v for k, v in d.items() if k not in TIME_KEYS + VALUE_KEYS}
                rows.append((ts, val, labels))
            if rows:
                return rows
    # 3) List of [ts, value] pairs.
    for candidate in walk_lists(metric_result):
        if candidate and all(isinstance(v, (list, tuple)) and len(v) == 2 and not isinstance(v[0], (list, dict)) for v in candidate):
            return [(ts, val, {}) for ts, val in candidate]
    return rows


def parse_metric(inv: dict) -> MetricData:
    raw = inv.get("metric_result")
    name = str(inv.get("metric_name") or "")
    error = None
    if isinstance(raw, dict):
        name = str(raw.get("metric_name") or name)
        if raw.get("error"):
            error = str(raw["error"])
    records = []
    for ts, val, labels in _extract_metric_rows(raw) if raw else []:
        parsed_ts, number = parse_ts(ts), None
        try:
            number = float(val)
        except (TypeError, ValueError):
            pass
        if parsed_ts is None or number is None:
            continue
        label_text = json.dumps(labels, sort_keys=True, default=str) if labels else ""
        records.append({"timestamp": parsed_ts, "value": number, "labels": label_text})
    df = pd.DataFrame(records, columns=["timestamp", "value", "labels"])
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
    anomaly: dict[str, Any] = {}
    for node in walk_dicts(raw):
        for key in ANOMALY_KEYS:
            if key in node and key not in anomaly:
                anomaly[key] = node[key]
    return MetricData(name=name, df=df, anomaly=anomaly, error=error, raw=raw)


def _first_dict_list(obj: Any, preferred: tuple[str, ...]) -> list[dict]:
    if isinstance(obj, dict):
        for key in preferred:
            candidate = obj.get(key)
            if isinstance(candidate, list) and all(isinstance(c, dict) for c in candidate):
                return candidate
    for candidate in walk_lists(obj):
        if candidate and all(isinstance(c, dict) for c in candidate):
            return candidate
    return []


def parse_logs(inv: dict) -> tuple[list[LogEntry], Optional[str]]:
    raw = inv.get("log_result")
    if not raw:
        return [], None
    error = str(raw["error"]) if isinstance(raw, dict) and raw.get("error") else None
    entries = []
    for item in _first_dict_list(raw, ("logs", "results", "hits", "matches", "points", "data")):
        score = item.get("score", pick(item, "similarity", "similarity_score"))
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            score = None
        entries.append(
            LogEntry(
                timestamp=parse_ts(pick(item, *TIME_KEYS)),
                service=str(pick(item, "service", "service_name", "component") or "-"),
                level=str(pick(item, "level", "severity", "log_level") or "-").upper(),
                entity_id=str(pick(item, "entity_id", "entity", "vm_id", "host") or "-"),
                message=str(pick(item, "message", "msg", "text", "log", "content") or ""),
                score=score,
                incident_id=str(pick(item, "incident_id") or "-"),
                raw=item,
            )
        )
    return entries, error


def parse_deployments(inv: dict) -> tuple[list[Deployment], int, Optional[str]]:
    raw = inv.get("deployment_result")
    if raw is None:
        return [], 0, None
    error = str(raw["error"]) if isinstance(raw, dict) and raw.get("error") else None
    items = _first_dict_list(raw, ("deployments", "results", "data", "items"))
    # A lone dict such as {"deployment_count": 0} is not a deployment record.
    items = [i for i in items if pick(i, "deployment_id", "id", "version", "service") is not None]
    deploys = [
        Deployment(
            deployment_id=str(pick(i, "deployment_id", "id") or "-"),
            service=str(pick(i, "service", "service_name") or "-"),
            version=str(pick(i, "version", "release") or "-"),
            timestamp=parse_ts(pick(i, "timestamp", "deployed_at", "time", "ts")),
            status=str(pick(i, "status", "state", "result") or "-"),
            raw=i,
        )
        for i in items
    ]
    count = len(deploys)
    if isinstance(raw, dict):
        for key in ("deployment_count", "count", "total"):
            if isinstance(raw.get(key), int) and not isinstance(raw.get(key), bool):
                count = raw[key]
                break
    return deploys, count, error


_SECTION_KEYS: dict[str, str] = {
    "observed evidence": "observed",
    "observed": "observed",
    "root-cause hypothesis": "hypothesis",
    "root cause hypothesis": "hypothesis",
    "root cause": "hypothesis",
    "root-cause": "hypothesis",
    "hypothesis": "hypothesis",
    "confidence": "confidence",
    "reasoning": "reasoning",
    "supporting evidence": "evidence",
    "evidence": "evidence",
    "limitations": "limitations",
    "limitation": "limitations",
}
_HEADING_RE = re.compile(
    r"^\s*(?P<hash>#{1,6}\s*)?(?P<bold>\*\*)?\s*(?P<key>" + "|".join(sorted(map(re.escape, _SECTION_KEYS), key=len, reverse=True)) + r")\s*(?P<endbold>\*\*)?\s*(?P<colon>:)?\s*(?P<endbold2>\*\*)?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)


def parse_sections(text: str) -> dict[str, str]:
    """Split LLM text into canonical sections when it uses explicit headings."""
    sections: dict[str, list[str]] = {}
    current: Optional[str] = None
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        is_heading = bool(match and (match.group("hash") or match.group("bold") or match.group("colon")))
        if is_heading and match:
            current = _SECTION_KEYS[match.group("key").lower()]
            sections.setdefault(current, [])
            if match.group("rest").strip():
                sections[current].append(match.group("rest").strip())
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip()}


def extract_citations(*texts: str) -> list[Citation]:
    seen: dict[str, Citation] = {}
    for text in texts:
        for match in CITE_RE.finditer(text or ""):
            token = match.group(0)
            if token in seen:
                continue
            kind = match.group(1).upper()
            kind = "DEPLOY" if kind.startswith("DEPLOY") else kind
            content = re.split(r"[:|]", token[1:-1], maxsplit=1)[1].strip()
            seen[token] = Citation(kind=kind, content=content, token=token)
    return list(seen.values())


def build_model(response: dict) -> Model:
    inv = response.get("investigation") or {}
    metric = parse_metric(inv)
    logs, logs_error = parse_logs(inv)
    deploys, deploy_count, deploy_error = parse_deployments(inv)
    hypothesis = str(inv.get("hypothesis") or "")
    final_report = str(inv.get("final_report") or "")

    sections = parse_sections(hypothesis)
    report_sections = parse_sections(final_report)
    for key in ("limitations", "reasoning", "confidence"):
        if key not in sections and key in report_sections:
            sections[key] = report_sections[key]

    confidence = None
    section_text = sections.get("confidence", "")
    found = re.match(r"\s*(high|medium|low)\b", section_text, re.IGNORECASE)
    for text in (hypothesis, final_report):
        found = found or re.search(r"confidence\W{0,6}(high|medium|low)", text, re.IGNORECASE)
    if found:
        confidence = found.group(1).upper()

    processing = response.get("processing_time_seconds")
    return Model(
        raw=response,
        inv=inv,
        incident_id=str(response.get("incident_id") or inv.get("incident_id") or "-"),
        api_status=str(response.get("status") or "unknown"),
        processing_time=float(processing) if isinstance(processing, (int, float)) else None,
        source=str(inv.get("source") or "-"),
        start=parse_ts(inv.get("start_time")),
        end=parse_ts(inv.get("end_time")),
        entity=str(inv.get("affected_entity") or ""),
        metric_name=metric.name or str(inv.get("metric_name") or ""),
        log_query=str(inv.get("log_query") or ""),
        metric=metric,
        logs=logs,
        logs_error=logs_error,
        deploys=deploys,
        deploy_count=deploy_count,
        deploy_error=deploy_error,
        evidence_context=str(inv.get("evidence_context") or ""),
        hypothesis=hypothesis,
        final_report=final_report,
        sections=sections,
        confidence=confidence,
        citations=extract_citations(hypothesis, final_report),
    )


def metric_unit(name: str) -> str:
    return "%" if "percent" in name.lower() else ""


def is_error_level(level: str) -> bool:
    return level.upper() in {"ERROR", "FATAL", "CRITICAL", "SEVERE"}


def observed_lines(m: Model) -> list[str]:
    """Plain-language facts computed directly from the returned evidence."""
    lines: list[str] = []
    df, unit = m.metric.df, metric_unit(m.metric.name)
    if not df.empty:
        first, last, peak = df["value"].iloc[0], df["value"].iloc[-1], df["value"].max()
        verb = "rose" if last > first else "fell" if last < first else "stayed"
        move = f"from {fmt_num(first)}{unit} to {fmt_num(last)}{unit}" if last != first else f"at {fmt_num(first)}{unit}"
        lines.append(f"{m.metric.name} {verb} {move} across {len(df)} samples (peak {fmt_num(peak)}{unit}).")
    else:
        lines.append("No metric samples were returned for the incident window.")
    if m.logs:
        errors = sum(is_error_level(log.level) for log in m.logs)
        lines.append(f"{len(m.logs)} relevant log entries were retrieved, {errors} at ERROR level.")
    else:
        lines.append("No relevant log entries were retrieved.")
    if m.deploy_count:
        lines.append(f"{m.deploy_count} deployment(s) found in the incident window.")
    else:
        lines.append("No deployments found in the incident window.")
    return lines


# --------------------------------------------------------------------------- #
# Rendering: masthead, sidebar, empty / loading / error states
# --------------------------------------------------------------------------- #


def chip(label: str, state: Optional[bool], detail: str = "") -> str:
    cls = "ok" if state is True else "bad" if state is False else ""
    text = detail or ("Connected" if state else "Unavailable" if state is False else "Not reported")
    return f'<span class="chip {cls}"><span class="dot">&#9679;</span>{esc(label)} {esc(text)}</span>'


def render_masthead(base_url: str) -> dict[str, Any]:
    health = check_health(base_url)
    body = health["body"]
    api_up = bool(health["reachable"])
    if api_up:
        prom = service_state(body, ("prometheus",))
        qdrant = service_state(body, ("qdrant",))
        agent = service_state(body, ("agent", "llm", "ollama", "langgraph"))
        api_chip = chip("API", True)
        others = (
            chip("Prometheus", prom)
            + chip("Qdrant", qdrant)
            + chip("Agent", agent, "Ready" if agent else "")
        )
    else:
        api_chip = chip("API", False, "Unreachable")
        others = "".join(chip(name, None, "Unknown") for name in ("Prometheus", "Qdrant", "Agent"))
    render_html(
        '<div class="mast"><div class="brand">'
        f'<img alt="" src="{svg_data_uri(BRAND_SVG)}"/>'
        '<div><div class="brand-name">OPS COPILOT</div>'
        '<div class="brand-sub">AI SRE Copilot &middot; Observability &amp; Root-Cause Analysis</div></div></div>'
        f'<div class="chips">{api_chip}{others}</div></div>'
    )
    return health


def apply_incident_preset() -> None:
    """Synchronize all request fields whenever the benchmark incident changes."""
    incident_id = st.session_state.get("incident_selector", "INC001")
    preset = INCIDENT_PRESETS[incident_id]
    st.session_state["f_incident"] = incident_id
    for key, value in preset.items():
        st.session_state[key] = value
    st.session_state.pop("result", None)
    st.session_state.pop("error", None)


def clear_form() -> None:
    st.session_state["incident_selector"] = "INC001"
    for key, value in FORM_DEFAULTS.items():
        st.session_state[key] = value
    st.session_state.pop("result", None)
    st.session_state.pop("error", None)


def render_sidebar() -> tuple[str, dict[str, str], bool]:
    """Render the incident form. Returns (api_url, form values, investigate_clicked)."""
    with st.sidebar:
        render_html('<div class="lbl" style="font-size:15px;letter-spacing:.14em;color:#d5dde6;font-weight:600">INCIDENT INVESTIGATION</div>')
        st.markdown("**Incident**")
        st.selectbox(
            "Incident ID",
            options=list(INCIDENT_PRESETS.keys()),
            key="incident_selector",
            on_change=apply_incident_preset,
        )
        st.text_input("Start time (ISO 8601, UTC)", key="f_start")
        st.text_input("End time (ISO 8601, UTC)", key="f_end")
        st.text_input("Affected entity", key="f_entity", placeholder="optional")
        st.text_input("Source", key="f_source")
        st.markdown("**Observability query**")
        st.text_input("Metric", key="f_metric")
        st.text_input("Log search query", key="f_query")
        go = st.button("INVESTIGATE INCIDENT", type="primary", **WIDE)
        st.button("CLEAR", on_click=clear_form, **WIDE)
        with st.expander("Connection"):
            st.text_input("FastAPI URL", key="api_url")
    form = {key: str(st.session_state.get(key, "")).strip() for key in FORM_DEFAULTS}
    return str(st.session_state["api_url"]).rstrip("/"), form, go


def render_empty_state() -> None:
    render_html(
        '<div class="empty-wrap"><h2>Ready to investigate</h2>'
        '<div class="q">What broke and why?</div>'
        '<div class="flow"><div>Metrics</div><div>Logs</div><div>Deployments</div><div class="ai">AI Reasoning</div></div>'
        "<p>OpsCopilot correlates Prometheus metrics, Qdrant log search and deployment history for the incident window, "
        "then asks an LLM agent for a root-cause hypothesis grounded in that evidence.</p>"
        '<p>Set the incident window in the sidebar and choose <b style="color:#d5dde6">INVESTIGATE INCIDENT</b>.</p></div>'
    )


def render_error(error: dict[str, str], base_url: str) -> None:
    render_html(
        f'<div class="err"><h4>{esc(error["title"])}</h4><p>{esc(error["message"])}</p>'
        f'<p class="muted mono" style="font-size:14px">API: {esc(base_url)}</p>'
        f'<p><b>Next step:</b> {esc(error["hint"])}</p></div>'
    )
    if error.get("details"):
        with st.expander("Technical error details"):
            st.code(error["details"], language="text")


WORKFLOW_STEPS = [
    "Incident received",
    "Query metrics (Prometheus)",
    "Search relevant logs (Qdrant)",
    "Check deployments",
    "Prepare evidence context",
    "AI reasoning (Llama 3 via Ollama)",
    "Final report",
]


def run_with_progress(base_url: str, payload: dict[str, Any], slot: Any) -> tuple[Optional[dict], Optional[dict]]:
    """
    Call the API in a worker thread while showing an elapsed-time panel.
    The API exposes no stage-level progress, so the step list is a description
    of the backend workflow, not live telemetry, and the UI says so.
    """
    with slot.container():
        status = st.status("INVESTIGATION IN PROGRESS", expanded=True)
        with status:
            st.caption("Workflow run by the backend. The API does not stream stage progress, so these steps are not live status.")
            render_html(
                "".join(
                    f'<div class="mono" style="font-size:15px;color:#7d8896;padding:1px 0">{i:02d}&nbsp;&nbsp;{esc(step)}</div>'
                    for i, step in enumerate(WORKFLOW_STEPS, 1)
                )
            )
            timer = st.empty()
        started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(call_investigate, base_url, payload)
            while not future.done():
                timer.markdown(f"`Waiting for investigation response... {time.monotonic() - started:5.1f} s`")
                time.sleep(0.4)
            try:
                response = future.result()
            except requests.RequestException as exc:
                status.update(label="INVESTIGATION FAILED", state="error", expanded=False)
                return None, error_from_exception(exc, base_url)
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI, never a stack trace
                status.update(label="INVESTIGATION FAILED", state="error", expanded=False)
                return None, error_from_exception(exc, base_url)
        if response.status_code >= 400:
            status.update(label="INVESTIGATION FAILED", state="error", expanded=False)
            return None, error_from_response(response)
        try:
            data = response.json()
        except ValueError:
            status.update(label="INVESTIGATION FAILED", state="error", expanded=False)
            return None, {
                "title": "UNEXPECTED RESPONSE",
                "message": "The API answered with a body that is not valid JSON.",
                "hint": "Confirm the URL points at the OpsCopilot FastAPI service.",
                "details": response.text[:4000],
            }
        if not isinstance(data, dict) or "investigation" not in data:
            status.update(label="INVESTIGATION FAILED", state="error", expanded=False)
            return None, {
                "title": "UNEXPECTED RESPONSE",
                "message": "The response does not contain an 'investigation' object.",
                "hint": "Confirm the backend version matches the documented contract.",
                "details": json.dumps(data, indent=2, default=str)[:4000],
            }
        status.update(label=f"INVESTIGATION RETURNED IN {time.monotonic() - started:.1f} s", state="complete", expanded=False)
        return data, None


def validate_form(form: dict[str, str]) -> tuple[Optional[dict[str, Any]], Optional[dict[str, str]]]:
    """Client-side sanity checks; the API remains the source of truth."""
    problems = []
    if not form["f_incident"]:
        problems.append("Incident ID is required.")
    start, end = parse_ts(form["f_start"]), parse_ts(form["f_end"])
    if start is None:
        problems.append("Start time is not a valid ISO 8601 timestamp.")
    if end is None:
        problems.append("End time is not a valid ISO 8601 timestamp.")
    if start and end and end <= start:
        problems.append("End time must be later than start time.")
    if not form["f_metric"]:
        problems.append("Metric is required.")
    if problems:
        return None, {
            "title": "INVALID TIME RANGE OR INPUT" if any("time" in p.lower() for p in problems) else "INVALID INPUT",
            "message": " ".join(problems),
            "hint": "Use timestamps such as 2026-09-29T13:20:20+00:00 and make sure the window is not empty.",
            "details": "",
        }
    payload = {
        "incident_id": form["f_incident"],
        "start_time": start.isoformat(),  # type: ignore[union-attr]
        "end_time": end.isoformat(),  # type: ignore[union-attr]
        "affected_entity": form["f_entity"],
        "source": form["f_source"],
        "metric_name": form["f_metric"],
        "log_query": form["f_query"],
    }
    return payload, None


# --------------------------------------------------------------------------- #
# Rendering: investigation workspace
# --------------------------------------------------------------------------- #


def render_incident_header(m: Model) -> None:
    ok = m.api_status.lower() == "success"
    badge_cls = "ok" if ok else "bad"
    badge = "INVESTIGATED &middot; SUCCESS" if ok else f"INVESTIGATED &middot; {esc(m.api_status.upper())}"
    same_day = m.start and m.end and m.start.date() == m.end.date()
    window = (
        f"{fmt_dt(m.start)} <span class='m'>&rarr;</span> {fmt_dt(m.end, with_date=not same_day)} UTC"
        if m.start and m.end
        else "Time window not returned"
    )
    entity = esc(m.entity) if m.entity else "Not specified"
    duration = fmt_duration((m.end - m.start).total_seconds()) if m.start and m.end else "-"
    cells = [
        ("INCIDENT ID", m.incident_id),
        ("SOURCE", m.source),
        ("DURATION", duration),
        ("PROCESSING TIME", fmt_duration(m.processing_time)),
        ("METRIC", m.metric_name or "-"),
        ("LOG QUERY", m.log_query or "-"),
    ]
    meta = "".join(f"<div><b>{esc(k)}</b><span>{esc(v)}</span></div>" for k, v in cells)
    render_html(
        f'<div class="inc-title"><span class="inc-id">{esc(m.incident_id)}</span>'
        f'<span class="badge {badge_cls}">{badge}</span></div>'
        f'<div class="inc-line">{esc(m.source.title() if m.source.islower() else m.source)} &nbsp;&middot;&nbsp; {window}</div>'
        f'<div class="inc-line"><span class="m">Affected entity:</span> {entity}</div>'
        f'<div class="meta">{meta}</div>'
    )


def pipeline_stages(m: Model) -> list[dict[str, str]]:
    n_metric, n_logs = len(m.metric.df), len(m.logs)
    if n_metric == 0:
        detect = ("empty", "NO METRIC DATA")
    elif m.metric.anomaly and any(bool(v) for v in m.metric.anomaly.values()):
        detect = ("done", "ANOMALY FLAGGED")
    elif m.metric.anomaly:
        detect = ("done", "NO ANOMALY FLAGGED")
    else:
        detect = ("done", "METRIC RETRIEVED")
    collect_empty = n_metric == 0 or n_logs == 0
    collect = ("empty" if collect_empty else "done", f"{n_metric} SAMPLES / {n_logs} LOGS / {m.deploy_count} DEPLOYS")
    correlate = ("done", f"{len(m.evidence_context)} CHARS CONTEXT") if m.evidence_context else ("missing", "NO EVIDENCE CONTEXT")
    reason = ("done", "HYPOTHESIS RETURNED") if m.hypothesis else ("missing", "NO HYPOTHESIS")
    report = ("done", "REPORT RETURNED") if m.final_report else ("missing", "NO REPORT")
    specs = [
        ("01", "DETECT", "&#8767;", "Metric anomaly identified", detect),
        ("02", "COLLECT", "&#8801;", "Metrics + logs + deployments retrieved", collect),
        ("03", "CORRELATE", "&#8646;", "Evidence aligned to incident window", correlate),
        ("04", "REASON", "&#9672;", "Llama 3 evaluates grounded evidence", reason),
        ("05", "REPORT", "&#9636;", "Root-cause hypothesis generated", report),
    ]
    return [
        {"num": n, "name": name, "icon": icon, "desc": desc, "state": st_[0], "label": st_[1]}
        for n, name, icon, desc, st_ in specs
    ]


def render_pipeline(m: Model) -> None:
    section_title("INVESTIGATION PIPELINE", "Each stage reflects what the API response actually contains")
    cells = "".join(
        f'<div class="stage {s["state"]}"><div class="top"><span class="num">{s["num"]}</span><span class="ico">{s["icon"]}</span></div>'
        f'<div class="name">{s["name"]}</div><div class="desc">{s["desc"]}</div><div class="st">{esc(s["label"])}</div></div>'
        for s in pipeline_stages(m)
    )
    render_html(f'<div class="pipe">{cells}</div>')


def confidence_html(level: Optional[str]) -> str:
    if not level:
        return '<div class="muted mono" style="font-size:16px">Confidence not stated by the backend</div>'
    filled = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}[level]
    color = {"LOW": "#7d8896", "MEDIUM": C_AMBER, "HIGH": C_GREEN}[level]
    bars = "".join(f'<i style="background:{color if i < filled else "#222c38"}"></i>' for i in range(3))
    return f'<div class="conf"><div class="bars">{bars}</div><div class="txt" style="color:{color}">{level} CONFIDENCE</div></div>'


def highlight_citations(text: str) -> str:
    """Escape text, then wrap citation tokens in styled chips."""
    escaped = esc(text)

    def repl(match: re.Match) -> str:
        kind = match.group(1).upper()
        cls = "deploy" if kind.startswith("DEPLOY") else kind.lower()
        return f'<span class="cite {cls}">{match.group(0)}</span>'

    return CITE_RE.sub(repl, escaped).replace("\n", "<br>")


def render_summary(m: Model) -> None:
    section_title("INCIDENT SUMMARY", "Observed evidence and hypothesis are kept separate")
    col_obs, col_hyp = st.columns(2)
    obs_items = "".join(f"<li>{esc(line)}</li>" for line in observed_lines(m))
    with col_obs:
        render_html(
            '<div class="panel obs"><div class="lbl">OBSERVED EVIDENCE &middot; what happened</div>'
            f"<ul>{obs_items}</ul>"
            '<div class="note">Computed from the metric, log and deployment data returned by the API.</div></div>'
        )
    with col_hyp:
        hypothesis = m.sections.get("hypothesis") or m.hypothesis
        body = highlight_citations(hypothesis) if hypothesis else '<span class="muted">The backend returned no hypothesis.</span>'
        render_html(
            '<div class="panel hyp"><div class="lbl">ROOT-CAUSE HYPOTHESIS &middot; model interpretation</div>'
            f"<p>{body}</p>{confidence_html(m.confidence)}"
            '<div class="note">A hypothesis from correlated evidence. It is not confirmed causation.</div></div>'
        )
    errors = sum(is_error_level(log.level) for log in m.logs)
    render_html(
        f'<div class="note" style="margin-top:10px"><b style="color:#d5dde6">Why it matters:</b> '
        f"{errors} error-level log entr{'y' if errors == 1 else 'ies'} and "
        f"{m.deploy_count} deployment{'s' if m.deploy_count != 1 else ''} in the incident window"
        f"{' (' + esc(m.entity) + ')' if m.entity else ''}. "
        "Impact beyond the retrieved evidence is not reported by the API.</div>"
    )


def metric_chart(m: Model) -> alt.Chart:
    df = m.metric.df
    unit = metric_unit(m.metric.name)
    axis = alt.Axis(labelColor=C_MUTED, titleColor=C_MUTED, gridColor=C_GRID, domainColor=C_GRID, tickColor=C_GRID, labelFont="JetBrains Mono, monospace")
    base = alt.Chart(df).encode(
        x=alt.X("timestamp:T", title=None, scale=alt.Scale(type="utc"), axis=alt.Axis(format="%H:%M:%S", labelColor=C_MUTED, gridColor=C_GRID, domainColor=C_GRID, tickColor=C_GRID)),
        y=alt.Y("value:Q", title=m.metric.name + (f" ({unit})" if unit else ""), scale=alt.Scale(zero=False), axis=axis),
        tooltip=[alt.Tooltip("timestamp:T", title="Time (UTC)", format="%H:%M:%S"), alt.Tooltip("value:Q", title="Value")],
    )
    layers: list[alt.Chart] = []
    if m.start and m.end:
        window = pd.DataFrame({"s": [pd.Timestamp(m.start)], "e": [pd.Timestamp(m.end)]})
        layers.append(alt.Chart(window).mark_rect(color=C_AMBER, opacity=0.09).encode(x=alt.X("s:T", scale=alt.Scale(type="utc")), x2="e:T"))
    layers.append(base.mark_line(color=C_CYAN, strokeWidth=2))
    layers.append(base.mark_point(color=C_CYAN, filled=True, size=46))
    peak = df.loc[[df["value"].idxmax()]]
    layers.append(
        alt.Chart(peak)
        .mark_point(color=C_AMBER, filled=True, size=120, shape="diamond")
        .encode(x=alt.X("timestamp:T", scale=alt.Scale(type="utc")), y="value:Q", tooltip=[alt.Tooltip("value:Q", title="Peak")])
    )
    return alt.layer(*layers).properties(height=280).configure(background="transparent").configure_view(strokeWidth=0).configure_axis(labelFontSize=15, titleFontSize=15)


def render_metrics(m: Model) -> None:
    df = m.metric.df
    if m.metric.error:
        nodata("Metric query returned an error", m.metric.error)
    if df.empty:
        nodata("No metric samples returned.", f"Prometheus returned no data for {m.metric_name or 'the requested metric'} in this window.")
        return
    unit = metric_unit(m.metric.name)
    first, peak, last = df["value"].iloc[0], df["value"].max(), df["value"].iloc[-1]
    cols = st.columns(6)
    cols[0].metric("Samples", len(df))
    cols[1].metric("Baseline (first)", f"{fmt_num(first)}{unit}")
    cols[2].metric("Peak", f"{fmt_num(peak)}{unit}")
    cols[3].metric("Minimum", f"{fmt_num(df['value'].min())}{unit}")
    cols[4].metric("Maximum", f"{fmt_num(df['value'].max())}{unit}")
    cols[5].metric("Last", f"{fmt_num(last)}{unit}")
    render_html(
        f'<div class="inc-line" style="margin:6px 0 4px"><span class="m">Metric</span> {esc(m.metric.name)} '
        f'&nbsp;<span class="m">Range</span> {fmt_dt(df["timestamp"].iloc[0].to_pydatetime(), False)} '
        f'&rarr; {fmt_dt(df["timestamp"].iloc[-1].to_pydatetime(), False)} UTC</div>'
    )
    anomaly = m.metric.anomaly
    if anomaly and any(bool(v) for v in anomaly.values()):
        render_html(f'<span class="badge bad">ANOMALY DETECTED</span> <span class="muted mono" style="font-size:14px">{esc(json.dumps(anomaly, default=str))}</span>')
    elif anomaly:
        render_html(f'<span class="badge">NO ANOMALY FLAGGED BY BACKEND</span> <span class="muted mono" style="font-size:14px">{esc(json.dumps(anomaly, default=str))}</span>')
    else:
        render_html('<span class="muted" style="font-size:14px">Anomaly status is not included in the API response, so none is shown.</span>')
    st.altair_chart(metric_chart(m), **WIDE)
    st.caption("Shaded band: requested incident window. Diamond: peak sample.")
    table = pd.DataFrame(
        {
            "Timestamp": df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S"),
            "Value": df["value"],
            "Labels": df["labels"],
        }
    )
    with st.expander(f"Raw samples ({len(table)})"):
        st.dataframe(table, hide_index=True, **WIDE)


def render_log_row(log: LogEntry) -> str:
    cls = "error" if is_error_level(log.level) else "warn" if log.level.startswith("WARN") else ""
    time_text = fmt_dt(log.timestamp, False) if log.timestamp else "-"
    score = f"{log.score:.4f}" if log.score is not None else "-"
    raw = esc(json.dumps(log.raw, indent=2, default=str)).replace("\n", "&#10;")
    fields = [
        ("TIMESTAMP", fmt_dt(log.timestamp)),
        ("SERVICE", log.service),
        ("LEVEL", log.level),
        ("ENTITY ID", log.entity_id),
        ("SIMILARITY", score),
        ("INCIDENT ID", log.incident_id),
    ]
    grid = "".join(f"<div><b>{k}</b><span>{esc(v)}</span></div>" for k, v in fields)
    return (
        f'<details class="log {cls}"><summary><span class="t">{esc(time_text)}</span><span class="lv">{esc(log.level)}</span>'
        f'<span class="svc">{esc(log.service)}</span><span class="msg">{esc(log.message)}</span>'
        f'<span class="sc">sim {esc(score)}</span></summary>'
        f'<div class="body"><div class="logmsg">{esc(log.message)}</div><div class="grid">{grid}</div>'
        f"<pre>{raw}</pre></div></details>"
    )


def render_logs(m: Model) -> None:
    if m.logs_error:
        nodata("Log search returned an error", m.logs_error)
    if not m.logs:
        nodata("No relevant logs retrieved.", f'Qdrant returned no matches for "{m.log_query}".')
        return
    errors = sum(is_error_level(log.level) for log in m.logs)
    render_html(
        f'<div class="inc-line" style="margin-bottom:8px">Retrieved logs: <b>{len(m.logs)}</b> '
        f'&nbsp;<span class="m">ERROR level:</span> {errors} &nbsp;<span class="m">Query:</span> {esc(m.log_query)}</div>'
    )
    render_html("".join(render_log_row(log) for log in m.logs))
    st.caption("Ordered as returned by the vector search (similarity rank). Open a row for the raw payload.")


def render_deployments(m: Model) -> None:
    if m.deploy_error:
        nodata("Deployment lookup returned an error", m.deploy_error)
    render_html(f'<div class="inc-line" style="margin-bottom:8px">Deployment count: <b>{m.deploy_count}</b></div>')
    if not m.deploys:
        if m.deploy_count == 0:
            nodata("No deployments found in the incident window.", "This is a valid result: no change event overlaps the window.")
        else:
            nodata(f"{m.deploy_count} deployment(s) reported but no records were included.", "See Technical details for the raw payload.")
        return
    table = pd.DataFrame(
        {
            "Deployment ID": [d.deployment_id for d in m.deploys],
            "Service": [d.service for d in m.deploys],
            "Version": [d.version for d in m.deploys],
            "Timestamp": [fmt_dt(d.timestamp) for d in m.deploys],
            "Status": [d.status for d in m.deploys],
        }
    )
    st.dataframe(table, hide_index=True, **WIDE)


@dataclass
class TimelineEvent:
    ts: Optional[datetime]
    kind: str  # metric | log | err | deploy | hyp
    label: str
    text: str


def build_timeline(m: Model) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    df, unit = m.metric.df, metric_unit(m.metric.name)
    if not df.empty:
        if len(df) <= 12:
            picks = {i: "" for i in range(len(df))}
        else:
            picks = {0: "first sample", int(df["value"].idxmax()): "peak", len(df) - 1: "last sample"}
        picks.setdefault(0, "first sample")
        picks.setdefault(len(df) - 1, "last sample")
        peak_idx = int(df["value"].idxmax())
        picks[peak_idx] = "peak" if len(df) > 1 else picks.get(peak_idx, "")
        for idx, note in sorted(picks.items()):
            row = df.iloc[idx]
            suffix = f" &nbsp;<span class='muted'>({note})</span>" if note else ""
            events.append(
                TimelineEvent(
                    row["timestamp"].to_pydatetime(),
                    "metric",
                    "METRIC",
                    f"<span class='mono'>{esc(m.metric.name)} = {fmt_num(row['value'])}{unit}</span>{suffix}",
                )
            )
    for log in m.logs:
        is_err = is_error_level(log.level)
        events.append(
            TimelineEvent(
                log.timestamp,
                "err" if is_err else "log",
                f"LOG &middot; {esc(log.level)} &middot; {esc(log.service)}",
                esc(log.message),
            )
        )
    for dep in m.deploys:
        events.append(
            TimelineEvent(dep.timestamp, "deploy", "DEPLOYMENT", f"<span class='mono'>{esc(dep.service)} {esc(dep.version)}</span> ({esc(dep.status)})")
        )
    far_future = datetime.max.replace(tzinfo=timezone.utc)
    events.sort(key=lambda e: e.ts or far_future)
    return events


def render_correlation(m: Model) -> None:
    section_title("EVIDENCE CORRELATION", "Metric samples, logs and deployments on one timeline (UTC)")
    events = build_timeline(m)
    if not events:
        nodata("No evidence to correlate.", "The API returned no metric samples, logs or deployments.")
        return
    items = []
    for ev in events:
        time_text = fmt_dt(ev.ts, False) if ev.ts else "--:--:--"
        items.append(
            f'<div class="tl-item {ev.kind}"><div class="tl-time">{esc(time_text)}</div><div class="tl-rail"><i></i></div>'
            f'<div class="tl-body"><div class="tl-kind">{ev.label}</div><div class="tl-text">{ev.text}</div></div></div>'
        )
    if m.deploy_count == 0:
        items.append(
            '<div class="tl-item deploy"><div class="tl-time">window</div><div class="tl-rail"><i></i></div>'
            '<div class="tl-body"><div class="tl-kind">DEPLOYMENT</div><div class="tl-text">No deployments found in the incident window.</div></div></div>'
        )
    hypothesis = m.sections.get("hypothesis") or m.hypothesis
    if hypothesis:
        shown = hypothesis if len(hypothesis) <= 320 else hypothesis[:317] + "..."
        items.append(
            '<div class="tl-item hyp"><div class="tl-time">agent</div><div class="tl-rail"><i></i></div>'
            f'<div class="tl-body"><div class="tl-kind">ROOT-CAUSE HYPOTHESIS &middot; CORRELATION, NOT CONFIRMED CAUSATION</div>'
            f'<div class="tl-text">{highlight_citations(shown)}</div></div></div>'
        )
    render_html(f'<div class="tl">{"".join(items)}</div>')
    st.caption("Every row is taken from the API response. Metric samples are condensed to first, peak and last when there are more than 12.")


def render_rca(m: Model) -> None:
    section_title("AI ROOT-CAUSE ANALYSIS", "Llama 3 via Ollama, grounded in the evidence above")
    if not m.hypothesis:
        nodata("The backend returned no hypothesis.", "Inspect Technical details for the raw response.")
        return
    left, right = st.columns([3, 2])
    with left:
        hypothesis = m.sections.get("hypothesis") or m.hypothesis
        render_html(f'<div class="panel hyp"><div class="lbl">ROOT-CAUSE HYPOTHESIS</div><p>{highlight_citations(hypothesis)}</p></div>')
        if m.sections.get("reasoning"):
            render_html(f'<div class="panel" style="margin-top:10px"><div class="lbl">REASONING</div><p>{highlight_citations(m.sections["reasoning"])}</p></div>')
        if m.sections.get("observed"):
            render_html(f'<div class="panel obs" style="margin-top:10px"><div class="lbl">OBSERVED (AS STATED BY THE AGENT)</div><p>{highlight_citations(m.sections["observed"])}</p></div>')
        else:
            items = "".join(f"<li>{esc(line)}</li>" for line in observed_lines(m))
            render_html(f'<div class="panel obs" style="margin-top:10px"><div class="lbl">OBSERVED (COMPUTED FROM RETURNED DATA)</div><ul>{items}</ul></div>')
    with right:
        render_html(f'<div class="panel"><div class="lbl">CONFIDENCE</div>{confidence_html(m.confidence)}</div>')
        limitations = m.sections.get("limitations")
        limits_body = (
            f"<p>{highlight_citations(limitations)}</p>"
            if limitations
            else '<p class="muted">No limitations were stated by the backend.</p>'
        )
        render_html(
            f'<div class="panel" style="margin-top:10px"><div class="lbl">LIMITATIONS</div>{limits_body}'
            '<div class="note">UI note: this view shows correlation between retrieved signals. It does not establish causation.</div></div>'
        )
    render_citations(m)
    with st.expander("Evidence context provided to the agent"):
        if m.evidence_context:
            st.code(m.evidence_context, language="text")
        else:
            st.write("The backend returned no evidence_context.")


def render_citations(m: Model) -> None:
    section_title("CITATIONS", "Evidence references used by the hypothesis and report")
    if not m.citations:
        nodata("No citations found in the hypothesis or report.", "Expected formats: [METRIC:...], [LOG|...], [DEPLOY:...].")
        return
    rows = "".join(
        f'<div class="evrow"><span class="k {"deploy" if c.kind == "DEPLOY" else c.kind.lower()}">[{esc(c.kind)}]</span>'
        f'<span class="v">{esc(c.content)}</span></div>'
        for c in m.citations
    )
    render_html(f'<div class="panel">{rows}</div>')


def render_tool_trace(m: Model) -> None:
    section_title("AGENT TOOL TRACE", "MCP tools behind the investigation")
    with st.expander("Show tool calls", expanded=False):
        window = f"{fmt_dt(m.start)} to {fmt_dt(m.end)} UTC"
        specs = [
            (
                "query_metrics()",
                m.metric.error,
                len(m.metric.df),
                f"metric={m.metric_name}; window={window}",
                f"{len(m.metric.df)} samples retrieved",
            ),
            (
                "search_logs()",
                m.logs_error,
                len(m.logs),
                f'query="{m.log_query}"; source={m.source}; window={window}',
                f"{len(m.logs)} relevant logs retrieved",
            ),
            (
                "get_recent_deploys()",
                m.deploy_error,
                m.deploy_count,
                f"entity={m.entity or 'not specified'}; window={window}",
                f"{m.deploy_count} deployments found",
            ),
        ]
        for i, (name, err, count, inputs, result) in enumerate(specs, 1):
            if err:
                status, color = "ERROR", C_RED
            elif count == 0:
                status, color = "EMPTY RESULT", C_AMBER
            else:
                status, color = "RESULT RETURNED", C_GREEN
            render_html(
                f'<div class="panel" style="margin-bottom:8px"><div class="mono" style="font-size:16px"><b>{i}. {esc(name)}</b> '
                f'<span style="color:{color};margin-left:8px">{esc(status)}</span></div>'
                f'<div class="mono muted" style="font-size:14px;margin-top:6px">input: {esc(inputs)}</div>'
                f'<div class="mono" style="font-size:15px;margin-top:2px">result: {esc(result)}{" (" + esc(err) + ")" if err else ""}</div></div>'
            )
        explicit = m.inv.get("tool_trace") or m.inv.get("tool_calls")
        if explicit:
            st.markdown("**Trace reported by the backend**")
            st.json(explicit, expanded=False)
        else:
            st.caption(
                "The API does not return a tool-call log. This trace is reconstructed from the evidence fields of the response "
                "(counts and request parameters); it is not a recording of the agent's actual calls."
            )


def copy_button(text: str) -> None:
    # "<" is escaped so report text (LLM output) can never close the script tag.
    payload = json.dumps(text).replace("<", "\\u003c")
    markup = (
        f"""
        <button id="c" style="width:100%;height:38px;background:transparent;color:#d5dde6;border:1px solid #222c38;
          border-radius:4px;font:600 16px 'JetBrains Mono',monospace;letter-spacing:.06em;cursor:pointer">COPY REPORT</button>
        <script>
        const text = {payload};
        const btn = document.getElementById('c');
        btn.onclick = async () => {{
          try {{ await navigator.clipboard.writeText(text); }}
          catch (e) {{
            const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta);
            ta.select(); document.execCommand('copy'); ta.remove();
          }}
          btn.textContent = 'COPIED'; setTimeout(() => btn.textContent = 'COPY REPORT', 1500);
        }};
        </script>"""
    )
    if hasattr(st, "iframe"):
        st.iframe(markup, height=44)
    else:
        components.html(markup, height=44)


def render_report(m: Model) -> None:
    section_title("FINAL INCIDENT REPORT", "Rendered from the backend's final_report")
    if not m.final_report:
        nodata("The backend returned no final report.")
        return
    c_copy, c_dl, _ = st.columns([1, 1, 4])
    with c_copy:
        copy_button(m.final_report)
    with c_dl:
        st.download_button(
            "DOWNLOAD REPORT",
            data=m.final_report,
            file_name=f"{m.incident_id}_incident_report.md",
            mime="text/markdown",
            **WIDE,
        )
    with st.container(border=True):
        # Citations become inline code so they stay visually distinct without raw HTML.
        st.markdown(CITE_RE.sub(lambda mt: f"`{mt.group(0)}`", m.final_report))


def render_technical(m: Model) -> None:
    section_title("TECHNICAL DETAILS")
    with st.expander("Raw API response, metric, log and deployment data"):
        tabs = st.tabs(["API response", "Metric data", "Log data", "Deployment data"])
        with tabs[0]:
            st.json(m.raw, expanded=False)
        with tabs[1]:
            st.json(m.inv.get("metric_result"), expanded=False)
        with tabs[2]:
            st.json(m.inv.get("log_result"), expanded=False)
        with tabs[3]:
            st.json(m.inv.get("deployment_result"), expanded=False)


def _time_domain(m: Model) -> Optional[list[int]]:
    """Shared x-domain (epoch ms) so every swimlane lines up exactly."""
    stamps = [pd.Timestamp(t) for t in (m.start, m.end) if t]
    if not m.metric.df.empty:
        stamps += [m.metric.df["timestamp"].min(), m.metric.df["timestamp"].max()]
    stamps += [pd.Timestamp(log.timestamp) for log in m.logs if log.timestamp]
    stamps += [pd.Timestamp(d.timestamp) for d in m.deploys if d.timestamp]
    if not stamps:
        return None
    low, high = min(stamps), max(stamps)
    pad = max((high - low) * 0.03, pd.Timedelta(seconds=1))
    return [int((low - pad).timestamp() * 1000), int((high + pad).timestamp() * 1000)]


def _lane_title(text: str) -> alt.TitleParams:
    return alt.TitleParams(text, anchor="start", color=C_MUTED, fontSize=15, font="JetBrains Mono, monospace")


def situation_charts(m: Model) -> list[alt.Chart]:
    """Three aligned swimlanes: metric, logs, deployments. All data comes from the API response."""
    domain = _time_domain(m)
    if domain is None:
        return []

    def x_enc(show_labels: bool) -> alt.X:
        return alt.X(
            "timestamp:T",
            title=None,
            scale=alt.Scale(type="utc", domain=domain),
            axis=alt.Axis(format="%H:%M:%S", labels=show_labels, ticks=show_labels, labelColor=C_MUTED, gridColor=C_GRID, domainColor=C_GRID, tickColor=C_GRID),
        )

    lane_axis = alt.Axis(title=None, labelColor=C_MUTED, ticks=False, domain=False, grid=False, labelFont="JetBrains Mono, monospace")

    def window_layer() -> list[alt.Chart]:
        if not (m.start and m.end):
            return []
        frame = pd.DataFrame({"s": [pd.Timestamp(m.start)], "e": [pd.Timestamp(m.end)]})
        return [alt.Chart(frame).mark_rect(color=C_AMBER, opacity=0.09).encode(x=alt.X("s:T", scale=alt.Scale(type="utc", domain=domain)), x2="e:T")]

    def note_layer(text: str, lane: str) -> alt.Chart:
        mid = pd.Timestamp((domain[0] + domain[1]) // 2, unit="ms", tz="UTC")
        frame = pd.DataFrame({"timestamp": [mid], "lane": [lane], "text": [text]})
        return alt.Chart(frame).mark_text(color=C_MUTED, font="IBM Plex Sans, sans-serif", fontSize=15).encode(
            x=alt.X("timestamp:T", scale=alt.Scale(type="utc", domain=domain)), y=alt.Y("lane:N", axis=lane_axis), text="text:N"
        )

    charts: list[alt.Chart] = []

    # Lane 1: metric
    df, unit = m.metric.df, metric_unit(m.metric.name)
    if df.empty:
        layers = window_layer() + [note_layer("No metric samples returned", "METRIC")]
        metric_lane = alt.layer(*layers).properties(height=70, title=_lane_title(f"METRIC \u00b7 {m.metric_name}"))
    else:
        base = alt.Chart(df).encode(
            x=x_enc(False),
            y=alt.Y("value:Q", scale=alt.Scale(zero=False), axis=alt.Axis(title=None, labelColor=C_MUTED, gridColor=C_GRID, domainColor=C_GRID, tickColor=C_GRID, format=".4~g")),
            tooltip=[alt.Tooltip("timestamp:T", title="Time (UTC)", format="%H:%M:%S"), alt.Tooltip("value:Q", title=f"Value{' (' + unit + ')' if unit else ''}")],
        )
        peak = df.loc[[df["value"].idxmax()]]
        layers = window_layer() + [
            base.mark_area(color=C_CYAN, opacity=0.10, line=False),
            base.mark_line(color=C_CYAN, strokeWidth=2),
            base.mark_point(color=C_CYAN, filled=True, size=40),
            alt.Chart(peak).mark_point(color=C_AMBER, filled=True, size=120, shape="diamond").encode(x=x_enc(False), y="value:Q"),
        ]
        metric_lane = alt.layer(*layers).properties(height=190, title=_lane_title(f"METRIC \u00b7 {m.metric_name}{' (' + unit + ')' if unit else ''} \u00b7 diamond = peak"))
    charts.append(metric_lane)

    # Lane 2: logs
    log_rows = [
        {
            "timestamp": pd.Timestamp(log.timestamp),
            "lane": "LOGS",
            "kind": "error" if is_error_level(log.level) else "warn" if log.level.startswith("WARN") else "other",
            "level": log.level,
            "service": log.service,
            "message": log.message,
        }
        for log in m.logs
        if log.timestamp
    ]
    layers = window_layer()
    if log_rows:
        logs_df = pd.DataFrame(log_rows)
        layers.append(
            alt.Chart(logs_df).mark_point(filled=True, size=150, shape="square", opacity=0.95).encode(
                x=x_enc(False),
                y=alt.Y("lane:N", axis=lane_axis),
                color=alt.Color("kind:N", legend=None, scale=alt.Scale(domain=["error", "warn", "other"], range=[C_RED, C_AMBER, "#8fa3ff"])),
                tooltip=[alt.Tooltip("timestamp:T", title="Time (UTC)", format="%H:%M:%S"), "level:N", "service:N", "message:N"],
            )
        )
    else:
        layers.append(note_layer("No logs retrieved for this window", "LOGS"))
    charts.append(alt.layer(*layers).properties(height=70, title=_lane_title(f"LOGS \u00b7 {len(m.logs)} retrieved \u00b7 red = ERROR")))

    # Lane 3: deployments
    layers = window_layer()
    dep_rows = [{"timestamp": pd.Timestamp(d.timestamp), "lane": "DEPLOYS", "service": d.service, "version": d.version, "status": d.status} for d in m.deploys if d.timestamp]
    if dep_rows:
        layers.append(
            alt.Chart(pd.DataFrame(dep_rows)).mark_point(filled=True, color="#c39bff", size=170, shape="diamond").encode(
                x=x_enc(True), y=alt.Y("lane:N", axis=lane_axis), tooltip=["service:N", "version:N", "status:N"]
            )
        )
        layers.append(note_layer("", "DEPLOYS").encode(x=x_enc(True)))
    else:
        layers.append(note_layer("No deployments found in the incident window", "DEPLOYS").encode(x=x_enc(True)))
    charts.append(alt.layer(*layers).properties(height=70, title=_lane_title(f"DEPLOYMENTS \u00b7 {m.deploy_count} found")))
    return charts


def render_situation(m: Model) -> None:
    section_title("CURRENT SITUATION", "All signals on one shared time axis (UTC). Shaded band = incident window")
    left, right = st.columns([1, 4])
    df, unit = m.metric.df, metric_unit(m.metric.name)
    errors = sum(is_error_level(log.level) for log in m.logs)
    state_cls, state_txt = ("bad", "ERROR LOGS IN WINDOW") if errors else ("", "NO ERROR LOGS RETRIEVED")
    if df.empty:
        metric_row = "No samples returned"
    else:
        metric_row = f"{fmt_num(df['value'].iloc[0])}{unit} &rarr; {fmt_num(df['value'].iloc[-1])}{unit} (peak {fmt_num(df['value'].max())}{unit})"
    rows = [
        ("METRIC", metric_row),
        ("LOGS", f"{len(m.logs)} retrieved &middot; {errors} ERROR"),
        ("DEPLOYS", f"{m.deploy_count} in window"),
        ("HYPOTHESIS", "Returned" if m.hypothesis else "Not returned"),
    ]
    row_html = "".join(f'<div class="evrow"><span class="k">{k}</span><span class="v">{v}</span></div>' for k, v in rows)
    with left:
        render_html(
            f'<div class="panel"><span class="badge {state_cls}">{state_txt}</span>'
            f'<div style="margin-top:10px">{row_html}</div>'
            f'<div style="margin-top:12px"><div class="lbl">CONFIDENCE</div>{confidence_html(m.confidence)}</div></div>'
        )
    with right:
        charts = situation_charts(m)
        if not charts:
            nodata("No evidence to plot.", "The API returned no timestamped metrics, logs or deployments.")
        for chart in charts:
            st.altair_chart(
                chart.configure(background="transparent").configure_view(strokeWidth=0).configure_axis(labelFontSize=15, titleFontSize=15).configure_axisY(minExtent=80, maxExtent=80),
                **WIDE,
            )


def render_workspace(m: Model) -> None:
    render_incident_header(m)
    render_situation(m)
    render_pipeline(m)
    render_summary(m)
    render_correlation(m)
    section_title("EVIDENCE", "Raw evidence returned by each source")
    tab_metrics, tab_logs, tab_deploys = st.tabs(
        [f"METRICS EVIDENCE · {len(m.metric.df)}", f"LOG EVIDENCE · {len(m.logs)}", f"DEPLOYMENT EVIDENCE · {m.deploy_count}"]
    )
    with tab_metrics:
        render_metrics(m)
    with tab_logs:
        render_logs(m)
    with tab_deploys:
        render_deployments(m)
    render_rca(m)
    render_tool_trace(m)
    render_report(m)
    render_technical(m)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def init_state() -> None:
    for key, value in FORM_DEFAULTS.items():
        st.session_state.setdefault(key, value)
    st.session_state.setdefault("incident_selector", "INC001")
    st.session_state.setdefault("api_url", DEFAULT_API_URL)


def main() -> None:
    st.set_page_config(page_title="OpsCopilot", page_icon="📡", layout="wide", initial_sidebar_state="expanded")
    render_html(CSS)
    init_state()
    base_url, form, investigate = render_sidebar()
    render_masthead(base_url)

    if investigate:
        st.session_state.pop("result", None)
        st.session_state.pop("error", None)
        payload, invalid = validate_form(form)
        if invalid:
            st.session_state["error"] = invalid
        else:
            slot = st.empty()
            data, error = run_with_progress(base_url, payload or {}, slot)
            slot.empty()
            if error:
                st.session_state["error"] = error
            elif data is not None and str(data.get("status", "")).lower() != "success":
                st.session_state["error"] = {
                    "title": "INVESTIGATION FAILED",
                    "message": f"The API reported status '{data.get('status')}'.",
                    "hint": "Inspect the technical details and the FastAPI logs.",
                    "details": json.dumps(data, indent=2, default=str)[:4000],
                }
            else:
                st.session_state["result"] = data

    if st.session_state.get("error"):
        render_error(st.session_state["error"], base_url)
    elif st.session_state.get("result"):
        render_workspace(build_model(st.session_state["result"]))
    else:
        render_empty_state()


main()
