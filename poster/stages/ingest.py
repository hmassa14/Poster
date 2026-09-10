"""Pull the seed feeds and keep items inside the issue window."""

from __future__ import annotations

import hashlib
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import feedparser
import yaml

UA = "Mozilla/5.0 (compatible; PosterBot/0.1; +https://github.com/hmassa14/poster)"


def fetch_feed(url: str, timeout: float = 20.0):
    """Fetch with an explicit user agent and timeout, then parse the bytes.

    feedparser's own fetcher has no timeout and uses a default agent that
    several publishers block.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return feedparser.parse(resp.read())

from ..config import Settings
from ..schemas import FeedItem


def _entry_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        val = entry.get(key)
        if val:
            return datetime.fromtimestamp(time.mktime(val), tz=timezone.utc)
    return None


def ingest(settings: Settings, *, window_end: datetime | None = None, log=print) -> list[FeedItem]:
    feeds_cfg = yaml.safe_load((settings.publication_dir / "feeds.yaml").read_text(encoding="utf-8")) or {}
    end = window_end or datetime.now(timezone.utc)
    start = end - timedelta(days=settings.research.lookback_days)
    items: dict[str, FeedItem] = {}

    for feed in feeds_cfg.get("feeds", []):
        try:
            parsed = fetch_feed(feed["url"])
        except Exception as exc:  # network or parse failure must not kill the run
            log(f"  feed failed: {feed['name']}: {type(exc).__name__}: {exc}")
            continue
        if not parsed.entries:
            reason = getattr(parsed, "bozo_exception", None)
            log(f"  feed empty/unreadable: {feed['name']}" + (f" ({reason})" if reason else ""))
            continue
        kept = 0
        for entry in parsed.entries:
            when = _entry_date(entry)
            if when is None or when < start or when > end + timedelta(hours=12):
                continue
            link = entry.get("link", "").strip()
            title = (entry.get("title") or "").strip()
            if not link or not title:
                continue
            key = hashlib.sha1(link.encode()).hexdigest()[:12]
            if key in items:
                continue
            summary = (entry.get("summary") or entry.get("description") or "").strip()
            summary = _strip_html(summary)[:800]
            items[key] = FeedItem(id=key, title=title, link=link, source=feed["name"], kind=feed.get("kind", "secondary"),
                                  published=when.isoformat(), summary=summary)
            kept += 1
        log(f"  {feed['name']}: {kept} items in window")

    rows = sorted(items.values(), key=lambda i: i.published, reverse=True)
    # Cap research feeds so arXiv does not drown everything else.
    research = [i for i in rows if i.kind == "research"][:60]
    other = [i for i in rows if i.kind != "research"]
    rows = (other + research)[: settings.research.max_feed_items]
    return rows


def _strip_html(text: str) -> str:
    import re

    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())
