from __future__ import annotations

from ..config import Settings
from .base import PublishResult


class DryRunPublisher:
    name = "dryrun"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, *, subject: str, preheader: str, html: str, text: str, markdown: str,
             canonical_url: str) -> PublishResult:
        return PublishResult(provider=self.name, ok=True,
                             detail=f"dry run: would send '{subject}' ({len(html)} bytes html) linking {canonical_url}")
