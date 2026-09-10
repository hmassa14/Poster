"""Resend: https://resend.com/docs/api-reference/broadcasts/create-broadcast

Creates a broadcast to an audience and sends it. Requires RESEND_API_KEY,
RESEND_FROM, and RESEND_AUDIENCE_ID. Resend substitutes {{{RESEND_UNSUBSCRIBE_URL}}}.
"""

from __future__ import annotations

import os

from ..config import Settings
from .base import PublishResult, http_json


class ResendPublisher:
    name = "resend"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = os.environ.get("RESEND_API_KEY", "")
        self.sender = os.environ.get("RESEND_FROM", "")
        self.audience = os.environ.get("RESEND_AUDIENCE_ID", "")
        self.base = "https://api.resend.com"

    def send(self, *, subject: str, preheader: str, html: str, text: str, markdown: str,
             canonical_url: str) -> PublishResult:
        missing = [k for k, v in {"RESEND_API_KEY": self.api_key, "RESEND_FROM": self.sender,
                                  "RESEND_AUDIENCE_ID": self.audience}.items() if not v]
        if missing:
            return PublishResult(provider=self.name, ok=False, detail=f"missing env: {', '.join(missing)}")
        html = html.replace("{{ unsubscribe_url }}", "{{{RESEND_UNSUBSCRIBE_URL}}}")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        status, data = http_json("POST", f"{self.base}/broadcasts", headers=headers, body={
            "audience_id": self.audience, "from": self.sender, "subject": subject,
            "html": html, "text": text, "name": subject,
        })
        if status not in (200, 201):
            return PublishResult(provider=self.name, ok=False, detail=f"create broadcast HTTP {status}: {data}")
        bid = str(data.get("id", ""))
        status, data = http_json("POST", f"{self.base}/broadcasts/{bid}/send", headers=headers, body={})
        if status in (200, 201):
            return PublishResult(provider=self.name, ok=True, detail="broadcast sent", remote_id=bid)
        return PublishResult(provider=self.name, ok=False, detail=f"send broadcast HTTP {status}: {data}", remote_id=bid)
