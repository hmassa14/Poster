from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class PublishResult:
    provider: str
    ok: bool
    detail: str
    remote_id: str = ""


class EmailPublisher(Protocol):
    name: str

    def send(self, *, subject: str, preheader: str, html: str, text: str, markdown: str,
             canonical_url: str) -> PublishResult: ...


def http_json(method: str, url: str, *, headers: dict[str, str], body: dict[str, Any] | None = None,
              timeout: float = 30.0) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw}
