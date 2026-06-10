"""Generic connector extraction for cross-repo structural binding.

Language/framework-agnostic by design. A registry of patterns captures
inter-service coupling points from code text as ``(kind, role, key)``:

  - kind   : the channel mechanism — "http" (routes/calls) or "topic" (queues).
  - role   : "server" exposes/handles/consumes a channel; "client" calls/emits to it.
  - key    : the path / topic identifier, normalized for matching.

The binder (structural.py) then matches role=client to role=server on the same
(kind, normalized key) across artifacts/repos. Nothing here is specific to any
project — extend by adding patterns to PATTERNS (or a user connectors file).

Precision over recall: patterns are qualified (by framework idiom / known client
libs) and keys are validated per kind, so we'd rather miss a binding than assert a
false one (false cross-repo edges destroy trust).
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

# (kind, role, regex, flags) — each regex has ONE capture group = the raw key.
PATTERNS: list[tuple[str, str, str, int]] = [
    # ---- HTTP server: route/endpoint declarations ----
    ("http", "server", r"""@\w+\.(?:route|get|post|put|delete|patch|head|options)\(\s*['"]([^'"]+)['"]""", 0),   # Flask/FastAPI/Django/blueprint decorators
    ("http", "server", r"""\b(?:app|router|mux|srv|server|api)\.(?:get|post|put|delete|patch|head|use|handle|handlefunc|add_route|add_url_rule)\(\s*['"`]([^'"`]+)['"`]""", re.I),  # express/go/starlette
    ("http", "server", r"""\.route\(\s*['"]([^'"]+)['"]""", 0),                 # axum / generic .route("/x")
    ("http", "server", r"""web::resource\(\s*['"]([^'"]+)['"]""", 0),           # actix
    # ---- HTTP client: outbound calls ----
    ("http", "client", r"""\b(?:requests|httpx|aiohttp|urllib3|reqwest|axios|got)\.(?:get|post|put|delete|patch|request|head|fetch)\(\s*['"]([^'"]+)['"]""", re.I),
    ("http", "client", r"""\b(?:session|client|http|conn|self\.client)\.(?:get|post|put|delete|patch|request|head)\(\s*['"]([^'"]+)['"]""", re.I),
    ("http", "client", r"""\bfetch\(\s*['"`]([^'"`]+)['"`]""", 0),              # JS fetch
    # ---- Queue/topic server: consume / subscribe ----
    ("topic", "server", r"""(?:subscribe|consume|listen)\w*\(\s*\[?\s*['"]([^'"]+)['"]""", re.I),
    ("topic", "server", r"""['"]([A-Za-z][\w.\-]{2,})['"]\s*,?\s*#?\s*(?:topic|queue|channel|subject)""", re.I),
    # ---- Queue/topic client: produce / publish ----
    ("topic", "client", r"""(?:produce|publish|emit|enqueue)\w*\([^)]*?['"]([^'"]+)['"]""", re.I),
    ("topic", "client", r"""\.send\(\s*['"]([^'"]+)['"]""", re.I),
]

_COMPILED = [(kind, role, re.compile(rx, fl)) for (kind, role, rx, fl) in PATTERNS]

# Routes too generic to be a meaningful cross-service binding.
_HTTP_GENERIC = {"/", "", "/health", "/healthz", "/healthcheck", "/ping", "/status",
                 "/metrics", "/favicon.ico", "/robots.txt", "/_health", "/livez", "/readyz"}
_PARAM_RE = re.compile(r"\{[^}/]*\}|:[A-Za-z_]\w*|<[^>/]*>")


def _valid_key(kind: str, key: str) -> bool:
    key = key.strip()
    if kind == "http":
        return (key.startswith("/") or "://" in key) and len(key) > 1
    if kind == "topic":
        return bool(re.fullmatch(r"[A-Za-z][\w.\-]{2,}", key)) and "/" not in key
    return False


def _normalize(kind: str, key: str) -> str | None:
    key = key.strip()
    if kind == "http":
        if "://" in key:
            key = urlsplit(key).path or "/"
        key = _PARAM_RE.sub("{}", key)              # collapse path params
        if len(key) > 1:
            key = key.rstrip("/")
        if key.lower() in _HTTP_GENERIC:
            return None
        # require at least one real segment of length >= 2
        if not any(len(seg) >= 2 for seg in key.strip("/").split("/")):
            return None
        return key
    if kind == "topic":
        return key.lower()
    return None


def extract(text: str) -> list[tuple[str, str, str, str, int]]:
    """Return de-duplicated (kind, role, key_norm, key_raw, line) connectors in `text`.

    Operates on full source text (so it sees decorators and module-level routes that
    per-function chunks would miss)."""
    out: dict[tuple[str, str, str], tuple[str, int]] = {}
    for kind, role, rx in _COMPILED:
        for m in rx.finditer(text):
            raw = m.group(1)
            if not _valid_key(kind, raw):
                continue
            norm = _normalize(kind, raw)
            if norm is None:
                continue
            key = (kind, role, norm)
            if key not in out:
                line = text.count("\n", 0, m.start()) + 1
                out[key] = (raw, line)
    return [(k[0], k[1], k[2], v[0], v[1]) for k, v in out.items()]
