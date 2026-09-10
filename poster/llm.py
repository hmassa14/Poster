"""Thin, opinionated wrapper around the Anthropic SDK for pipeline stages.

Every call goes through `Claude.complete()`:
- streaming always (long outputs, no HTTP timeouts)
- adaptive thinking with a configurable effort level
- prompt caching on the stable system prefix
- optional structured output via a pydantic model
- optional server-side web search / web fetch with pause_turn continuation
- server-side refusal fallbacks (beta) on by default
- every call traced with usage and estimated cost
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from .config import Settings
from .trace import Trace

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class RefusalError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    parsed: Any
    stop_reason: str | None
    usage: dict[str, int]
    model: str


class LLMClient(Protocol):
    """What a pipeline stage needs. `Claude` is the real one; tests use a fake."""

    def complete(self, *, stage: str, system: str, user: str, output_format: type[T] | None = None,
                 tools: list[dict[str, Any]] | None = None, model: str | None = None,
                 effort: str | None = None, max_tokens: int | None = None) -> LLMResult: ...


def web_tools(max_searches: int, max_fetches: int) -> list[dict[str, Any]]:
    return [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_fetches},
    ]


def _usage_dict(usage: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        val = getattr(usage, key, None)
        out[key] = int(val or 0)
    return out


def _merge_usage(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    return {k: a.get(k, 0) + b.get(k, 0) for k in set(a) | set(b)}


class Claude:
    def __init__(self, settings: Settings, trace: Trace, client: Any | None = None) -> None:
        import anthropic

        self.settings = settings
        self.trace = trace
        self.client = client or anthropic.Anthropic()
        self._anthropic = anthropic
        # Full record of the most recent calls (system, user, output, usage) so
        # evals can save complete transcripts; bounded to keep memory flat.
        self.calls: list[dict[str, Any]] = []
        self.max_calls_kept = 50

    def complete(self, *, stage: str, system: str, user: str, output_format: type[T] | None = None,
                 tools: list[dict[str, Any]] | None = None, model: str | None = None,
                 effort: str | None = None, max_tokens: int | None = None) -> LLMResult:
        model = model or self.settings.models.main
        effort = effort or self.settings.models.effort
        max_tokens = max_tokens or self.settings.models.max_tokens

        # Stable prefix cached; the volatile user turn follows the breakpoint.
        system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]

        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
        )
        if tools:
            kwargs["tools"] = tools
        if output_format is not None:
            kwargs["output_format"] = output_format
        if self.settings.models.fallbacks:
            kwargs["fallbacks"] = "default"
            kwargs["betas"] = [FALLBACK_BETA]

        usage_total: dict[str, int] = {}
        continuations = 0
        started = time.time()
        while True:
            with self.client.beta.messages.stream(**kwargs) as stream:
                message = stream.get_final_message()
            usage_total = _merge_usage(usage_total, _usage_dict(message.usage))

            if message.stop_reason == "pause_turn" and continuations < self.settings.research.max_continuations:
                # Server-side tool loop hit its iteration cap; resend to resume.
                continuations += 1
                kwargs["messages"] = [
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": message.content},
                ]
                continue
            break

        served_by = getattr(message, "model", model)
        self.trace.record(stage=stage, model=model, usage=usage_total, seconds=time.time() - started,
                          stop_reason=message.stop_reason, continuations=continuations, served_by=served_by)

        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise RefusalError(f"{stage}: model refused (category={category})")
        if message.stop_reason == "max_tokens":
            raise RuntimeError(f"{stage}: output truncated at max_tokens={max_tokens}; raise models.max_tokens")

        text_parts: list[str] = []
        parsed = None
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
                if output_format is not None and getattr(block, "parsed_output", None) is not None:
                    parsed = block.parsed_output
        text = "".join(text_parts)

        if output_format is not None and parsed is None:
            # Structured output guarantees JSON in the text; parse defensively.
            parsed = output_format.model_validate_json(_extract_json(text))

        self.calls.append({"stage": stage, "model": model, "served_by": served_by, "system": system, "user": user,
                           "output": text, "usage": usage_total, "stop_reason": message.stop_reason,
                           "tools": [t.get("name") for t in tools] if tools else [], "continuations": continuations,
                           "seconds": round(time.time() - started, 2)})
        del self.calls[:-self.max_calls_kept]
        return LLMResult(text=text, parsed=parsed, stop_reason=message.stop_reason,
                         usage=usage_total, model=served_by)


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in model output")
    return text[start:end + 1]
