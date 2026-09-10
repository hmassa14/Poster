"""Publishing adapters. `get_email_publisher` picks one by name."""

from __future__ import annotations

from ..config import Settings
from .base import EmailPublisher, PublishResult
from .buttondown import ButtondownPublisher
from .dryrun import DryRunPublisher
from .resend import ResendPublisher


def get_email_publisher(settings: Settings, *, dry_run: bool = False) -> EmailPublisher:
    name = settings.publishing.email_provider.lower()
    if dry_run or name in {"dryrun", "dry-run", "none", ""}:
        return DryRunPublisher(settings)
    if name == "buttondown":
        return ButtondownPublisher(settings)
    if name == "resend":
        return ResendPublisher(settings)
    raise ValueError(f"unknown email provider: {settings.publishing.email_provider}")


__all__ = ["EmailPublisher", "PublishResult", "get_email_publisher"]
