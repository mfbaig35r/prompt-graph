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

Fetcher = Callable[[str, dict[str, str]], dict[str, Any]]


class HarveyUnavailable(Exception):
    """The API cannot be used: not configured, rejected, or answered in an unexpected shape."""


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
                "Harvey rate limit reached (Vault allows 10 requests a minute per organisation); try again shortly."
            ) from e
        raise HarveyUnavailable(f"Harvey returned HTTP {e.code} for {url}: {body}") from e
    except urllib.error.URLError as e:
        raise HarveyUnavailable(f"Could not reach Harvey at {url}: {e.reason}") from e


def list_ready_files(
    project_id: str,
    fetcher: Fetcher | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Every ready_to_query file in a Vault project: [{id, uploaded_at, deleted_at}], and the
    number of requests it took (so callers can reason about the rate limit)."""
    key = api_key or os.environ.get(ENV_KEY)
    if not key:
        raise HarveyUnavailable(
            f"{ENV_KEY} is not set; supply the document count manually or configure the API key."
        )
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
            cursor = str(page["next_cursor"])
            if requests >= 50:
                raise HarveyUnavailable(
                    "Stopped after 50 pages; the project is larger than expected."
                )
            continue
        break
    return files, requests
