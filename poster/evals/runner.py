"""Eval runner: runs real stage entry points on fixtures, grades, and reports.

Output layout follows the hillclimb contract so `/claude-api hillclimb` can
build on it later:

    <out>/<flow>/<variant>/results.jsonl     one row per (case, rep)
    <out>/<flow>/<variant>/traces/<id>_rep<k>.json
    <out>/<flow>/<variant>/errors.jsonl      infra failures, never scored
    <out>/<flow>/_state.json                 metric declarations
    <out>/summary.json, <out>/report.md
"""

from __future__ import annotations

import json
import statistics
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..config import Settings
from ..lint import lint_draft, load_banned
from ..llm import LLMClient, RefusalError
from ..memory import Memory
from ..policy import Policy, classify_escalation
from ..schemas import (Brief, Candidate, Critique, Draft, EscalationDecision, EscalationHit, FeedItem, Issue,
                       ResearchPack, SEOPackage, SocialPosts, TriageResult)
from ..stages import critic, research, seo, writer
from . import graders
from .mutations import Mutation, all_mutations

FLOWS = ["critic", "writer", "triage", "escalation", "seo"]


@dataclass
class EvalOptions:
    flows: list[str] = field(default_factory=lambda: list(FLOWS))
    reps: int = 1
    variant: str = "baseline"
    model: str | None = None
    judge_model: str | None = None
    limit: int | None = None
    out_dir: Path | None = None
    enforce: bool = False
    case_timeout_s: float = 900.0


@dataclass
class Case:
    id: str
    tags: list[str]
    prompt: str          # human-readable description of the input
    run: Callable[[], Any]
    grade: Callable[[Any], dict[str, Any]]
    kind: str = "positive"


class EvalRunner:
    def __init__(self, settings: Settings, client: LLMClient, policy: Policy, log: Callable[[str], None] = print) -> None:
        self.settings = settings
        self.client = client
        self.policy = policy
        self.log = log
        self.memory = Memory(settings)
        self.cases_dir = settings.root / "evals" / "cases"
        self.banned = load_banned(settings.publication_dir / "banned_phrases.txt")
        # Synthetic fixtures use .example URLs; never hit the network for them.
        self.settings.editorial.verify_links = False

    # ---- fixtures ----------------------------------------------------------
    def pack(self) -> ResearchPack:
        return ResearchPack.model_validate_json((self.cases_dir / "research_pack.json").read_text(encoding="utf-8"))

    def brief(self) -> Brief:
        return Brief.model_validate_json((self.cases_dir / "brief.json").read_text(encoding="utf-8"))

    def clean_draft(self) -> str:
        return (self.cases_dir / "clean_draft.md").read_text(encoding="utf-8")

    def _lint_text(self, md: str) -> str:
        e = self.settings.editorial
        return lint_draft(md, banned=self.banned, min_words=e.target_words_min, max_words=e.target_words_max).as_text()

    # ---- flows -------------------------------------------------------------
    def cases_critic(self) -> list[Case]:
        pack, clean = self.pack(), self.clean_draft()
        min_score = self.settings.editorial.min_critic_score

        def make(md: str, mutation: Mutation | None) -> Case:
            draft = Draft(title="The Price Cut That Reads Like a Confession", dek="", body_markdown=md, stories_covered=[])
            lint_text = self._lint_text(md)
            links = critic.verify_links(md, pack, enabled=False)

            def run() -> Critique:
                return critic.critique_draft(self.client, self.settings, self.memory, pack, draft, lint_text, links, 1)

            if mutation is None:
                def grade(c: Critique) -> dict[str, Any]:
                    fa = graders.critic_false_alarm(c, min_score)
                    return {"grade": {"no_false_alarm": 0.0 if fa else 1.0, "score": c.score / 10},
                            "explanation": {"no_false_alarm": c.summary}}
                return Case("clean", ["negative", "clean"], "clean, fully grounded draft", run, grade, kind="negative")

            def grade_m(c: Critique, m: Mutation = mutation) -> dict[str, Any]:
                caught = graders.critic_caught(c, m)
                return {"grade": {"caught": 1.0 if caught else 0.0, "score": c.score / 10, "failed_draft": 1.0 if c.score < min_score else 0.0},
                        "explanation": {"caught": f"expected at '{m.location}'; critic: {c.summary}"}}
            return Case(mutation.id, ["positive", mutation.kind], f"seeded error: {mutation.description}", run, grade_m)

        return [make(clean, None)] + [make(m.markdown, m) for m in all_mutations(clean)]

    def cases_writer(self) -> list[Case]:
        pack, brief = self.pack(), self.brief()
        alt = brief.model_copy(deep=True)
        alt.working_title = "A Fine With a Number On It"
        alt.lead_story_id = "s3"
        alt.lead_angle = "Lead with the first fine under the 2025 automated-decision rules; what it means for anyone screening people with models."
        alt.also_this_week = [i for i in brief.also_this_week if i.story_id != "s3"] + [brief.also_this_week[0].model_copy(update={"story_id": "s1", "angle": "The price cut and the latency page"})]
        alt.research_corner = []
        judge_model = self._judge_model()
        e = self.settings.editorial

        def make(cid: str, b: Brief) -> Case:
            def run() -> Draft:
                return writer.write_draft(self.client, self.settings, self.memory, pack, b)

            def grade(d: Draft) -> dict[str, Any]:
                g = graders.grounding(d.body_markdown, pack)
                lint = lint_draft(d.body_markdown, banned=self.banned, min_words=e.target_words_min, max_words=e.target_words_max)
                met, reasons, _ = graders.judge_rubric(self.client, judge_model, prompt=_prompt(self.settings, "judge"),
                                                       input_text=f"BRIEF:\n{b.model_dump_json(indent=1)}\n\nRESEARCH PACK:\n{pack.model_dump_json(indent=1)}",
                                                       output_text=d.body_markdown, rubric=graders.WRITER_RUBRIC)
                rubric = sum(met.values()) / len(met) if met else 0.0
                return {"grade": {"grounded": 1.0 if g.grounded else 0.0, "lint_ok": 1.0 if lint.ok else 0.0, "rubric": round(rubric, 3)},
                        "explanation": {"grounded": f"numbers={g.ungrounded_numbers} links={g.ungrounded_links}",
                                        "lint_ok": "; ".join(lint.errors) or "clean",
                                        "rubric": "; ".join(f"{k}: {'met' if v else 'NOT met'} ({reasons.get(k, '')})" for k, v in met.items())},
                        "words": lint.word_count, "judge_model": judge_model}
            return Case(cid, ["writer"], f"write issue from brief '{b.working_title}'", run, grade)

        return [make("lead-s1", brief), make("lead-s3", alt)]

    def cases_triage(self) -> list[Case]:
        data = json.loads((self.cases_dir / "triage_items.json").read_text(encoding="utf-8"))
        items = data["items"]
        feed = [FeedItem(id=i["id"], title=i["title"], link=i["link"], source=i["source"], kind=i["kind"],
                         published=i["published"], summary=i["summary"]) for i in items]

        def run() -> TriageResult:
            return research.triage(self.client, self.settings, feed)

        def grade(r: TriageResult) -> dict[str, Any]:
            m = graders.triage_metrics(r, items)
            return {"grade": {"recall": m["recall"], "precision": m["precision"], "merge_accuracy": m["merge_accuracy"]},
                    "explanation": {"recall": f"tp={m['tp']} fp={m['fp']} fn={m['fn']} candidates={m['candidates']}"}}
        return [Case("labeled-week", ["triage"], f"{len(items)} labeled feed items", run, grade)]

    def cases_escalation(self) -> list[Case]:
        data = json.loads((self.cases_dir / "escalation.json").read_text(encoding="utf-8"))
        out = []
        for c in data["cases"]:
            def run(text: str = c["text"]) -> EscalationDecision:
                return classify_escalation(self.client, self.settings, self.policy, text)

            def grade(d: EscalationDecision, exp: list[str] = c["expected"]) -> dict[str, Any]:
                g = graders.escalation_grade(d, exp)
                return {"grade": {"correct": 1.0 if g["correct"] else 0.0}, "explanation": {"correct": json.dumps(g)}}
            kind = "positive" if c["expected"] else "negative"
            out.append(Case(c["id"], [kind] + c["expected"], c["text"][:120], run, grade, kind=kind))
        return out

    def cases_seo(self) -> list[Case]:
        md = self.clean_draft()
        draft = Draft(title="The Price Cut That Reads Like a Confession",
                      dek="This week the cost of running models fell faster than the models improved.", body_markdown=md, stories_covered=[])
        existing = {"the-price-cut-that-reads-like-a-confession"}

        def run() -> SEOPackage:
            return seo.make_seo(self.client, self.settings, self.memory, draft)

        def grade(p: SEOPackage) -> dict[str, Any]:
            g = graders.seo_constraints(p, md, existing)
            return {"grade": {"constraints": 1.0 if g["pass"] else 0.0}, "explanation": {"constraints": "; ".join(g["failures"]) or "all constraints met"}}
        return [Case("clean-draft", ["seo"], "SEO package for the clean draft", run, grade)]

    def _judge_model(self) -> str:
        return self.policy.judge_model

    # ---- execution ---------------------------------------------------------
    def run(self, opts: EvalOptions) -> dict[str, Any]:
        out = opts.out_dir or (self.settings.root / "evals" / "results")
        out.mkdir(parents=True, exist_ok=True)
        if opts.model:
            self.settings.models.main = opts.model
            self.settings.models.fast = opts.model
        if opts.judge_model:
            self.policy.raw.setdefault("evals", {})["judge_model"] = opts.judge_model
        requested_model = self.settings.models.main

        summary: dict[str, Any] = {"at": _now(), "variant": opts.variant, "model": requested_model,
                                   "judge_model": self._judge_model(), "reps": opts.reps, "flows": {}}
        for flow in opts.flows:
            cases = getattr(self, f"cases_{flow}")()
            if opts.limit:
                cases = cases[: opts.limit]
            fdir = out / flow / opts.variant
            (fdir / "traces").mkdir(parents=True, exist_ok=True)
            results_path, errors_path = fdir / "results.jsonl", fdir / "errors.jsonl"
            done = _done_keys(results_path)
            self.log(f"[eval:{flow}] {len(cases)} cases x {opts.reps} reps ({len(done)} already done)")
            for case in cases:
                for rep in range(opts.reps):
                    key = f"{case.id}#{rep}"
                    if key in done:
                        continue
                    row = self._run_one(flow, case, rep, requested_model, opts)
                    if row.get("status") == "error":
                        with errors_path.open("a", encoding="utf-8") as fh:
                            fh.write(json.dumps(row) + "\n")
                        continue
                    with results_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(row) + "\n")
                    self._save_trace(fdir / "traces" / f"{case.id}_rep{rep}.json")
                    g = row.get("grade", {})
                    self.log(f"  {case.id:28s} rep{rep} {row['status']:9s} " + " ".join(f"{k}={v}" for k, v in g.items()))
            summary["flows"][flow] = self.summarize_flow(flow, results_path, errors_path)
            _write_state(out / flow, flow)

        summary["thresholds"] = self.check_thresholds(summary)
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        (out / "report.md").write_text(render_report(summary), encoding="utf-8")
        return summary

    def _run_one(self, flow: str, case: Case, rep: int, requested_model: str, opts: EvalOptions) -> dict[str, Any]:
        started = time.time()
        if hasattr(self.client, "calls"):
            self.client.calls.clear()
        base = {"prompt_id": case.id, "prompt": case.prompt, "tags": [flow, case.kind] + case.tags, "rep": rep, "flow": flow}
        try:
            output = case.run()
        except RefusalError as exc:
            return {**base, "status": "refused", "grade": None, "error": str(exc), "latency_s": round(time.time() - started, 1)}
        except Exception as exc:  # infra / parse / timeout: never a score
            return {**base, "status": "error", "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:],
                    "latency_s": round(time.time() - started, 1)}
        latency = time.time() - started
        if latency > opts.case_timeout_s:
            return {**base, "status": "error", "error": f"timeout: {latency:.0f}s > {opts.case_timeout_s:.0f}s"}
        calls = list(getattr(self.client, "calls", []))
        stage_calls = [c for c in calls if c.get("stage") != "judge"]
        served = sorted({c.get("served_by") for c in stage_calls if c.get("served_by")})
        # Each call must be served by the model it requested (alias -> snapshot resolution allowed).
        model_ok = all(str(c.get("served_by") or c.get("model") or "").startswith(str(c.get("model") or requested_model))
                       for c in stage_calls)
        try:
            graded = case.grade(output)
        except Exception as exc:
            return {**base, "status": "error", "error": f"grader failed: {type(exc).__name__}: {exc}"}
        judge_calls = [c for c in getattr(self.client, "calls", []) if c.get("stage") == "judge"]
        usage = _sum_usage(stage_calls)
        row = {**base, "status": "ok" if model_ok else "served_model_mismatch", **graded,
               "model": served[0] if len(served) == 1 else (served or requested_model), "usage": usage,
               "latency_s": round(latency, 1), "stop_reason": stage_calls[-1].get("stop_reason") if stage_calls else None}
        if judge_calls:
            row["judge_model"] = judge_calls[-1].get("served_by")
            row["judge_usage"] = _sum_usage(judge_calls)
        if any(c.get("stop_reason") == "max_tokens" for c in stage_calls):
            row["status"] = "truncated"
        return row

    def _save_trace(self, path: Path) -> None:
        turns = []
        for c in getattr(self.client, "calls", []):
            turns.append({"role": "system", "content": c.get("system", ""), "name": c.get("stage")})
            turns.append({"role": "user", "content": c.get("user", "")})
            turns.append({"role": "assistant", "content": c.get("output", ""),
                          "meta": {"model": c.get("served_by"), "usage": c.get("usage"), "stop_reason": c.get("stop_reason"),
                                   "tools": c.get("tools"), "seconds": c.get("seconds")}})
        path.write_text(json.dumps(turns, indent=1) + "\n", encoding="utf-8")

    # ---- summaries ---------------------------------------------------------
    def summarize_flow(self, flow: str, results_path: Path, errors_path: Path) -> dict[str, Any]:
        rows = [json.loads(l) for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()] if results_path.exists() else []
        errors = len(errors_path.read_text(encoding="utf-8").splitlines()) if errors_path.exists() else 0
        ok = [r for r in rows if r.get("status") == "ok" and r.get("grade")]
        out: dict[str, Any] = {"cases": len({r["prompt_id"] for r in rows}), "rows": len(rows), "scored": len(ok), "errors": errors,
                               "refused": sum(1 for r in rows if r.get("status") == "refused"),
                               "truncated": sum(1 for r in rows if r.get("status") == "truncated"),
                               "served_model_mismatch": sum(1 for r in rows if r.get("status") == "served_model_mismatch"),
                               "metrics": {}, "cost_usd": _cost(rows)}
        if flow == "critic":
            pos = [r for r in ok if "positive" in r["tags"]]
            neg = [r for r in ok if "negative" in r["tags"]]
            out["metrics"]["critic_recall"] = _mean([r["grade"]["caught"] for r in pos])
            out["metrics"]["critic_specificity"] = _mean([r["grade"]["no_false_alarm"] for r in neg])
            out["metrics"]["critic_failed_mutated"] = _mean([r["grade"]["failed_draft"] for r in pos])
            out["by_kind"] = {k: _mean([r["grade"]["caught"] for r in pos if k in r["tags"]]) for k in ("fact", "source", "style", "format", "judgement")}
            out["missed"] = sorted({r["prompt_id"] for r in pos if r["grade"]["caught"] < 1})
        elif flow == "writer":
            out["metrics"]["writer_grounded_rate"] = _mean([r["grade"]["grounded"] for r in ok])
            out["metrics"]["writer_lint_pass_rate"] = _mean([r["grade"]["lint_ok"] for r in ok])
            out["metrics"]["writer_rubric_mean"] = _mean([r["grade"]["rubric"] for r in ok])
            out["words"] = _mean([r.get("words", 0) for r in ok])
        elif flow == "triage":
            out["metrics"]["triage_recall"] = _mean([r["grade"]["recall"] for r in ok])
            out["metrics"]["triage_precision"] = _mean([r["grade"]["precision"] for r in ok])
            out["metrics"]["triage_merge_accuracy"] = _mean([r["grade"]["merge_accuracy"] for r in ok])
        elif flow == "escalation":
            pos = [r for r in ok if "positive" in r["tags"]]
            neg = [r for r in ok if "negative" in r["tags"]]
            out["metrics"]["escalation_recall"] = _mean([r["grade"]["correct"] for r in pos])
            out["metrics"]["escalation_specificity"] = _mean([r["grade"]["correct"] for r in neg])
            out["missed"] = sorted({r["prompt_id"] for r in ok if r["grade"]["correct"] < 1})
        elif flow == "seo":
            out["metrics"]["seo_constraint_pass_rate"] = _mean([r["grade"]["constraints"] for r in ok])
        # spread across reps for the headline metric
        for mid, val in list(out["metrics"].items()):
            out["metrics"][mid] = {"mean": val["mean"], "stdev": val["stdev"], "n": val["n"]}
        return out

    def check_thresholds(self, summary: dict[str, Any]) -> dict[str, Any]:
        th = self.policy.thresholds
        results: dict[str, Any] = {}
        for flow, data in summary["flows"].items():
            for mid, m in data["metrics"].items():
                if mid in th and m["n"]:
                    results[mid] = {"value": m["mean"], "threshold": th[mid], "pass": m["mean"] >= th[mid]}
        results["_all_pass"] = all(v["pass"] for k, v in results.items() if k != "_all_pass")
        return results


# ---------------------------------------------------------------- harness smoke (oracle / null)

def harness_smoke(settings: Settings, policy: Policy) -> dict[str, Any]:
    """Push known-good and known-bad outputs through every programmatic grader. No API calls."""
    cases_dir = settings.root / "evals" / "cases"
    pack = ResearchPack.model_validate_json((cases_dir / "research_pack.json").read_text(encoding="utf-8"))
    clean = (cases_dir / "clean_draft.md").read_text(encoding="utf-8")
    min_score = settings.editorial.min_critic_score
    checks: dict[str, dict[str, float]] = {}

    muts = all_mutations(clean)
    oracle = [graders.critic_caught(Critique(score=4, summary="", issues=[Issue(severity="blocker", kind="fact", location=m.location, problem="x", fix="y")], required_edits=[]), m) for m in muts]
    null = [graders.critic_caught(Critique(score=9, summary="fine", issues=[], required_edits=[]), m) for m in muts]
    checks["critic_recall"] = {"oracle": _frac(oracle), "null": _frac(null)}
    checks["critic_specificity"] = {"oracle": 1.0 - float(graders.critic_false_alarm(Critique(score=9, summary="", issues=[], required_edits=[]), min_score)),
                                    "null": 1.0 - float(graders.critic_false_alarm(Critique(score=3, summary="", issues=[Issue(severity="blocker", kind="fact", location="x", problem="x", fix="y")], required_edits=[]), min_score))}

    g_clean = graders.grounding(clean, pack).grounded
    g_bad = graders.grounding(next(m.markdown for m in muts if m.id == "number_invented"), pack).grounded
    checks["writer_grounded_rate"] = {"oracle": float(g_clean), "null": float(g_bad)}

    items = json.loads((cases_dir / "triage_items.json").read_text(encoding="utf-8"))["items"]
    by_group: dict[str, list[dict]] = {}
    for it in items:
        if it["keep"]:
            by_group.setdefault(it["group"], []).append(it)
    oracle_tr = TriageResult(candidates=[Candidate(id=g, headline=v[0]["title"], main_url=v[0]["link"], other_urls=[x["link"] for x in v[1:]], sources=[],
                                                   event_date=v[0]["published"], summary="", category="other", significance=3, why_candidate="")
                                         for g, v in by_group.items()], dropped_summary="")
    m_or = graders.triage_metrics(oracle_tr, items)
    m_nu = graders.triage_metrics(TriageResult(candidates=[], dropped_summary=""), items)
    checks["triage_recall"] = {"oracle": m_or["recall"], "null": m_nu["recall"]}
    checks["triage_precision"] = {"oracle": m_or["precision"], "null": m_nu["precision"]}

    esc = json.loads((cases_dir / "escalation.json").read_text(encoding="utf-8"))["cases"]
    or_pos = [graders.escalation_grade(EscalationDecision(requires_human_review=True, hits=[EscalationHit(category=c["expected"][0], passage="", reason="")], summary=""), c["expected"])["correct"] for c in esc if c["expected"]]
    nu_pos = [graders.escalation_grade(EscalationDecision(requires_human_review=False, hits=[], summary=""), c["expected"])["correct"] for c in esc if c["expected"]]
    or_neg = [graders.escalation_grade(EscalationDecision(requires_human_review=False, hits=[], summary=""), [])["correct"] for c in esc if not c["expected"]]
    nu_neg = [graders.escalation_grade(EscalationDecision(requires_human_review=True, hits=[EscalationHit(category="minors", passage="", reason="")], summary=""), [])["correct"] for c in esc if not c["expected"]]
    checks["escalation_recall"] = {"oracle": _frac(or_pos), "null": _frac(nu_pos)}
    checks["escalation_specificity"] = {"oracle": _frac(or_neg), "null": _frac(nu_neg)}

    good = SEOPackage(slug="price-cut-latency-page", title_tag="Halcyon cuts Tern 3 pricing 60% and publishes latency",
                      meta_description="Halcyon cut Tern 3 input pricing from $2.50 to $1.00 per million tokens and published p50 and p99 latency by context tier for the first time.",
                      headline_h1="x", excerpt="x", keywords=["Halcyon Labs", "Tern 3", "Marlin-27B", "Nordic Digital Authority", "Cinder Compute"],
                      tags=["models"], social=SocialPosts(linkedin="l {url}", x="x {url}", threads="t"), email_subject="s", email_preheader="p",
                      og_title="o", og_description="d", image_alt="i")
    bad = good.model_copy(update={"slug": "!!", "keywords": ["AI news", "Zebra Corp"]})
    checks["seo_constraint_pass_rate"] = {"oracle": float(graders.seo_constraints(good, clean, set())["pass"]),
                                          "null": float(graders.seo_constraints(bad, clean, set())["pass"])}
    ok = all(v["oracle"] >= 0.99 and v["null"] <= 0.01 for v in checks.values())
    return {"ok": ok, "checks": checks}


# ---------------------------------------------------------------- helpers

def _prompt(settings: Settings, name: str) -> str:
    return (settings.prompts_dir / f"{name}.md").read_text(encoding="utf-8").strip()


def _done_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            keys.add(f"{r['prompt_id']}#{r.get('rep', 0)}")
    return keys


def _sum_usage(calls: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in calls:
        for k, v in (c.get("usage") or {}).items():
            out[k] = out.get(k, 0) + int(v)
    return out


def _cost(rows: list[dict[str, Any]]) -> float:
    from ..trace import estimate_cost

    total = 0.0
    for r in rows:
        if r.get("usage"):
            total += estimate_cost(str(r.get("model")), r["usage"])
        if r.get("judge_usage"):
            total += estimate_cost(str(r.get("judge_model")), r["judge_usage"])
    return round(total, 4)


def _mean(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {"mean": None, "stdev": None, "n": 0}
    return {"mean": round(statistics.fmean(vals), 3), "stdev": round(statistics.pstdev(vals), 3) if len(vals) > 1 else 0.0, "n": len(vals)}


def _frac(bools: list[bool]) -> float:
    return round(sum(1 for b in bools if b) / len(bools), 3) if bools else 0.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


METRIC_DECLS = {
    "critic": [("critic_recall", "Recall"), ("critic_specificity", "Specificity"), ("critic_failed_mutated", "Failed bad")],
    "writer": [("writer_grounded_rate", "Grounded"), ("writer_lint_pass_rate", "Lint ok"), ("writer_rubric_mean", "Rubric")],
    "triage": [("triage_recall", "Recall"), ("triage_precision", "Precision"), ("triage_merge_accuracy", "Merged")],
    "escalation": [("escalation_recall", "Recall"), ("escalation_specificity", "Specificity")],
    "seo": [("seo_constraint_pass_rate", "Constraints")],
}


def _write_state(flow_dir: Path, flow: str) -> None:
    state = {"flow": flow, "metrics": [{"id": mid, "label": label, "kind": "number"} for mid, label in METRIC_DECLS[flow]],
             "perf_fields": ["latency_s", "usage"]}
    (flow_dir / "_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def render_report(summary: dict[str, Any]) -> str:
    lines = [f"# Eval report — {summary['variant']}", "",
             f"Run at {summary['at']} on `{summary['model']}` (judge `{summary['judge_model']}`), {summary['reps']} rep(s).", "",
             "| Flow | Metric | Mean | Stdev | n | Threshold | Pass |", "|---|---|---|---|---|---|---|"]
    th = summary.get("thresholds", {})
    for flow, data in summary["flows"].items():
        for mid, m in data["metrics"].items():
            t = th.get(mid, {})
            lines.append(f"| {flow} | {mid} | {m['mean']} | {m['stdev']} | {m['n']} | {t.get('threshold', '')} | {'yes' if t.get('pass') else ('no' if t else '')} |")
    lines += ["", "| Flow | Cases | Scored | Errors | Refused | Truncated | Model mismatch | Cost USD |", "|---|---|---|---|---|---|---|---|"]
    for flow, d in summary["flows"].items():
        lines.append(f"| {flow} | {d['cases']} | {d['scored']} | {d['errors']} | {d['refused']} | {d['truncated']} | {d['served_model_mismatch']} | {d['cost_usd']} |")
    for flow, d in summary["flows"].items():
        if d.get("missed"):
            lines += ["", f"**{flow} missed:** " + ", ".join(d["missed"])]
        if d.get("by_kind"):
            lines += ["", f"**{flow} recall by kind:** " + ", ".join(f"{k}={v['mean']}" for k, v in d["by_kind"].items())]
    lines += ["", f"**All thresholds pass:** {'yes' if th.get('_all_pass') else 'no'}", ""]
    return "\n".join(lines)


def production_report(path: Path, last: int = 12) -> str:
    if not path.exists():
        return "No production runs recorded yet."
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()][-last:]
    lines = ["| Issue | Critic scores | Rounds | Lint errors | Bad links | Policy flags | Published | Cost USD | Models |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['issue_id']} | {r['critic_scores']} | {r['revision_rounds']} | {r['final_lint_errors']} | "
                     f"{r['links_unreachable'] + r['links_not_in_pack']} | {r['policy_violations']}/{r['policy_escalations']} | "
                     f"{'yes' if r['published'] else 'no'} | {r['est_cost_usd']} | {', '.join(r.get('served_models', []))} |")
    final_scores = [r["critic_scores"][-1] for r in rows if r["critic_scores"]]
    if final_scores:
        lines += ["", f"Mean final critic score over last {len(final_scores)} issues: {statistics.fmean(final_scores):.2f}; "
                      f"mean revision rounds: {statistics.fmean(r['revision_rounds'] for r in rows):.2f}; "
                      f"mean cost: ${statistics.fmean(r['est_cost_usd'] or 0 for r in rows):.2f}"]
    return "\n".join(lines)
