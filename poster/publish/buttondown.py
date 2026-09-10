"""Buttondown: https://docs.buttondown.com/api-emails-introduction

POST /v1/emails with {subject, body, status}. Body is Markdown by default;
Buttondown renders it with its own template and handles unsubscribe links.
"""

from __future__ import annotations

import os

from ..config import Settings
from .base import PublishResult, http_json


class ButtondownPublisher:
    name = "buttondown"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = os.environ.get("BUTTONDOWN_API_KEY", "")
        self.base = os.environ.get("BUTTONDOWN_API_BASE", "https://api.buttondown.com/v1")
        # "about_to_send" sends immediately; "draft" leaves it in the dashboard for a human.
        self.status = os.environ.get("BUTTONDOWN_STATUS", "about_to_send")

    def send(self, *, subject: str, preheader: str, html: str, text: str, markdown: str,
             canonical_url: str) -> PublishResult:
        if not self.api_key:
            return PublishResult(provider=self.name, ok=False, detail="BUTTONDOWN_API_KEY is not set")
        body = markdown.rstrip() + f"\n\n---\n\n*Read this issue on the web: {canonical_url}*\n\n{self.settings.publication.disclosure}\n"
        status, data = http_json(
            "POST", f"{self.base}/emails",
            headers={"Authorization": f"Token {self.api_key}"},
            body={"subject": subject, "body": body, "status": self.status,
                  "description": preheader, "canonical_url": canonical_url},
        )
        if status in (200, 201):
            return PublishResult(provider=self.name, ok=True, detail=f"created email with status {self.status}",
                                 remote_id=str(data.get("id", "")))
        return PublishResult(provider=self.name, ok=False, detail=f"HTTP {status}: {data}")
