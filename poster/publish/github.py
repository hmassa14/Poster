"""Read feedback from GitHub Issues with the REST API (no gh CLI needed)."""

from __future__ import annotations

import os
from typing import Any

from .base import http_json


def _headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "poster-feedback"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_feedback_issues(repo: str, label: str, *, state: str = "open") -> list[dict[str, Any]]:
    url = f"https://api.github.com/repos/{repo}/issues?labels={label}&state={state}&per_page=50"
    status, data = http_json("GET", url, headers=_headers())
    if status != 200:
        raise RuntimeError(f"GitHub issues fetch failed: HTTP {status}: {data}")
    out = []
    for iss in data:
        if "pull_request" in iss:
            continue
        comments: list[dict[str, str]] = []
        if iss.get("comments", 0):
            cstatus, cdata = http_json("GET", iss["comments_url"] + "?per_page=50", headers=_headers())
            if cstatus == 200:
                comments = [{"author": c["user"]["login"], "body": c.get("body") or ""} for c in cdata]
        out.append({"number": iss["number"], "title": iss["title"], "body": iss.get("body") or "",
                    "author": iss["user"]["login"], "comments": comments, "url": iss["html_url"]})
    return out


def close_issue(repo: str, number: int, comment: str) -> bool:
    headers = _headers()
    if "Authorization" not in headers:
        return False
    http_json("POST", f"https://api.github.com/repos/{repo}/issues/{number}/comments", headers=headers,
              body={"body": comment})
    status, _ = http_json("PATCH", f"https://api.github.com/repos/{repo}/issues/{number}", headers=headers,
                          body={"state": "closed", "state_reason": "completed"})
    return status == 200
