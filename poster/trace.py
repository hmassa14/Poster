"""Per-run tracing of every model call: tokens, cache hits, cost estimate."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# USD per million tokens (input, output). Cache writes ~1.25x input, cache reads ~0.1x.
PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def estimate_cost(model: str, usage: dict[str, int]) -> float:
    inp, out = PRICES.get(model, (5.0, 25.0))
    cost = usage.get("input_tokens", 0) * inp
    cost += usage.get("output_tokens", 0) * out
    cost += usage.get("cache_creation_input_tokens", 0) * inp * 1.25
    cost += usage.get("cache_read_input_tokens", 0) * inp * 0.1
    return cost / 1_000_000


@dataclass
class Trace:
    path: Path | None
    records: list[dict[str, Any]] = field(default_factory=list)

    def record(self, *, stage: str, model: str, usage: dict[str, int], seconds: float,
               stop_reason: str | None, continuations: int = 0, served_by: str | None = None) -> None:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "stage": stage,
            "model": model,
            "served_by": served_by or model,
            "seconds": round(seconds, 1),
            "stop_reason": stop_reason,
            "continuations": continuations,
            **usage,
            "est_cost_usd": round(estimate_cost(served_by or model, usage), 4),
        }
        self.records.append(rec)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")

    def summary(self) -> dict[str, Any]:
        total = sum(r["est_cost_usd"] for r in self.records)
        by_stage: dict[str, float] = {}
        for r in self.records:
            by_stage[r["stage"]] = round(by_stage.get(r["stage"], 0.0) + r["est_cost_usd"], 4)
        return {
            "calls": len(self.records),
            "est_cost_usd": round(total, 4),
            "by_stage": by_stage,
            "input_tokens": sum(r.get("input_tokens", 0) for r in self.records),
            "output_tokens": sum(r.get("output_tokens", 0) for r in self.records),
            "cache_read_input_tokens": sum(r.get("cache_read_input_tokens", 0) for r in self.records),
        }
