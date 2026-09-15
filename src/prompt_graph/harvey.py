"""Minimal Harvey Vault API client for document-set freshness (Addendum A.1).

Verified against developers.harvey.ai, 2026-09: bearer auth, regional base URLs
(api.harvey.ai, eu.api.harvey.ai, au.api.harvey.ai), cursor pagination on
GET /api/v1/vault/projects/{project_id}/files, processing_status in
{uploaded, processing, ready_to_query}, and a limit of 10 requests per minute per
organisation on Vault endpoints. Standard library only; the fetcher is injectable so tests
never touch the network. Fails loudly on an unexpected response shape rather than
assuming a stale capability model.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

ENV_KEY = "HARVEY_API_KEY"
ENV_BASE = "HARVEY_API_BASE"
DEFAULT_BASE = "https://api.harvey.ai"
PAGE_SIZE = 100

# Vault allows ten requests a minute per organisation, shared with everything else the firm
# is doing in Harvey. One poll never spends more than this, so a project too large to
# enumerate degrades into a reported finding instead of a 429 partway through, which would
# discard the pages already fetched and leave every retry restarting from the first cursor.
MAX_REQUESTS_PER_POLL = 8

Fetcher = Callable[[str, dict[str, str]], dict[str, Any]]


class HarveyUnavailable(Exception):
    """The API cannot be used: not configured, rejected, or answered in an unexpected shape.

    `rate_limited` marks the one cause that is organisation-wide rather than specific to this
    project, so a caller polling several projects knows to stop rather than fail each in turn.
    """

    def __init__(self, message: str, *, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited


def configured() -> bool:
    return bool(os.environ.get(ENV_KEY))


def _default_fetcher(url: str, headers: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (https, fixed host)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        if e.code == 429:
            raise HarveyUnavailable(
                "Harvey rate limit reached (Vault allows 10 requests a minute per organisation); try again shortly.",
                rate_limited=True,
            ) from e
        raise HarveyUnavailable(f"Harvey returned HTTP {e.code} for {url}: {body}") from e
    except urllib.error.URLError as e:
        raise HarveyUnavailable(f"Could not reach Harvey at {url}: {e.reason}") from e


def list_ready_files(
    project_id: str,
    fetcher: Fetcher | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    max_requests: int = MAX_REQUESTS_PER_POLL,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Every ready_to_query file in a Vault project.

    Returns (files, requests_used, complete). `complete` is False when the project has more
    pages than `max_requests` allowed: the file list is then a prefix, not the document set,
    and the caller must not record it as a snapshot.
    """
    key = api_key or os.environ.get(ENV_KEY)
    if not key:
        raise HarveyUnavailable(
            f"{ENV_KEY} is not set; supply the document count manually or configure the API key."
        )
    if max_requests < 1:
        raise HarveyUnavailable("No Vault request budget left for this poll.")
    base = (base_url or os.environ.get(ENV_BASE) or DEFAULT_BASE).rstrip("/")
    fetch = fetcher or _default_fetcher
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    files: list[dict[str, Any]] = []
    cursor: str | None = None
    requests = 0
    while True:
        params = {"processing_status": "ready_to_query", "page_size": str(PAGE_SIZE)}
        if cursor:
            params["cursor"] = cursor
        url = (
            f"{base}/api/v1/vault/projects/{urllib.parse.quote(project_id)}/files?"
            + urllib.parse.urlencode(params)
        )
        page = fetch(url, headers)
        requests += 1
        items = page.get("files", page.get("data"))
        if not isinstance(items, list):
            raise HarveyUnavailable(
                f"Unexpected response shape from Harvey (no 'files' list): keys={sorted(page)[:8]}"
            )
        for f in items:
            if not isinstance(f, dict) or "id" not in f:
                raise HarveyUnavailable("Unexpected file record shape from Harvey (no 'id').")
            if f.get("deleted_at"):
                continue
            if f.get("processing_status", "ready_to_query") != "ready_to_query":
                continue
            files.append(
                {
                    "id": str(f["id"]),
                    "uploaded_at": f.get("uploaded_at"),
                    "name": f.get("name"),
                }
            )
        if page.get("has_more") and page.get("next_cursor"):
            if requests >= max_requests:
                return files, requests, False
            cursor = str(page["next_cursor"])
            continue
        break
    return files, requests, True
