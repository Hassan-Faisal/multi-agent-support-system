"""Evaluation runner.

    python -m support.evals.runner                 # agent cases + retrieval, real models
    python -m support.evals.runner --only retrieval
    python -m support.evals.runner --judge         # add LLM-graded quality scores
    python -m support.evals.runner --case large-refund-needs-approval

Writes a Markdown + JSON report to evals/reports/ and exits non-zero if the pass
rate falls below --min-pass (so CI can gate prompt or model changes).

Uses the database in SUPPORT_DATABASE_URL and RESETS ITS BUSINESS DATA per case:
point it at a dedicated eval database, never production.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field
from sqlalchemy import select

from support.agents.graph import text_of
from support.api.container import Container, build_container
from support.db.models import Refund, Return, Ticket
from support.db.seed import reset, seed
from support.db.session import SessionFactory, create_engine, create_session_factory, unit_of_work
from support.evals.checks import Case, CaseResult, RunRecord, category_scores, evaluate
from support.rag.documents import load_directory
from support.rag.embeddings import Embedder, build_embedder
from support.rag.ingest import ingest
from support.rag.retriever import HybridRetriever
from support.settings import Settings, get_settings

EVALS_DIR = Path(__file__).resolve().parents[3] / "evals"


# ---------------------------------------------------------------- agent cases
async def run_case(c: Container, case: Case) -> RunRecord:
    async with unit_of_work(c.sessions) as s:
        await reset(s)
        await seed(s)
    conv = uuid.uuid4()
    config: Any = {
        "configurable": {"thread_id": str(conv), "conversation_id": str(conv), "customer_id": case.customer}
    }
    route: str | None = None
    try:
        for i, text in enumerate(case.turns):
            state = await c.graph.ainvoke({"messages": [HumanMessage(text, id=str(uuid.uuid4()))]}, config)
            if i == 0:
                route = next((e["agent"] for e in state.get("events", []) if e["type"] == "route"), None)
    except Exception as e:  # recorded as a failed case, not a crashed run
        return RunRecord(route, set(), None, [], "", {}, set(), 0, error=f"{type(e).__name__}: {e}")

    msgs = state["messages"]
    agents = {
        m.name for m in msgs if isinstance(m, AIMessage) and m.name not in (None, "triage", "guardrail")
    }
    tools = [m.name for m in msgs if isinstance(m, ToolMessage) and m.name]
    final = next(m for m in reversed(msgs) if isinstance(m, AIMessage) and not m.tool_calls)
    async with unit_of_work(c.sessions) as s:
        refunds = {r.invoice_id: r.status.value for r in (await s.scalars(select(Refund))).all()}
        returns = {r.order_id for r in (await s.scalars(select(Return))).all()}
        tickets = len((await s.scalars(select(Ticket).where(Ticket.customer_id == case.customer))).all())
    return RunRecord(
        route, {a for a in agents if a}, final.name, tools, text_of(final), refunds, returns, tickets
    )


class JudgeScore(BaseModel):
    """Grades one support reply."""

    helpfulness: int = Field(ge=1, le=5, description="Does it resolve or clearly move the issue forward?")
    groundedness: int = Field(
        ge=1, le=5, description="Are all facts supported by the transcript/tool results?"
    )
    tone: int = Field(ge=1, le=5, description="Warm, concise, professional.")
    notes: str = Field(description="One sentence on the biggest weakness, or 'none'.")


async def judge(model: BaseChatModel, case: Case, record: RunRecord) -> dict[str, Any]:
    grader = model.with_structured_output(JudgeScore, method="json_schema")
    prompt = (
        "You are grading a customer-support AI reply. Be strict; 5 means you would ship it as is.\n\n"
        f"Customer messages: {json.dumps(case.turns)}\n"
        f"Tools the assistant used: {record.tools}\n"
        f"Final reply:\n{record.final_reply}"
    )
    result = JudgeScore.model_validate(await grader.ainvoke(prompt))
    return result.model_dump()


# ---------------------------------------------------------------- retrieval
async def run_retrieval(sessions: SessionFactory, embedder: Embedder, k: int = 3) -> dict[str, Any]:
    cases = yaml.safe_load((EVALS_DIR / "retrieval_cases.yaml").read_text())
    retriever = HybridRetriever(sessions, embedder, max_chunks_per_doc=1)  # score at document level
    hits, rr, misses = 0, 0.0, []
    for case in cases:
        got = [r.slug for r in await retriever.search(case["query"], top_k=k)]
        rank = next((i + 1 for i, slug in enumerate(got) if slug in case["expected"]), None)
        hits += rank is not None
        rr += 1 / rank if rank else 0
        if rank is None:
            misses.append({"query": case["query"], "expected": case["expected"], "got": got})
    n = len(cases)
    return {
        "k": k,
        "cases": n,
        "recall": hits / n,
        "mrr": rr / n,
        "misses": misses,
        "embedder": embedder.model_name,
    }


async def run_agent_cases(c: Container, settings: Settings, args: argparse.Namespace) -> list[CaseResult]:
    raw = yaml.safe_load((EVALS_DIR / "agent_cases.yaml").read_text())
    cases = [Case.model_validate(x) for x in raw if not args.case or x["id"] in args.case]
    judge_model = None
    if args.judge:
        from support.agents.llm import build_chat_models

        judge_model = build_chat_models(settings)[0]
    results = []
    for case in cases:
        t0 = time.perf_counter()
        record = await run_case(c, case)
        res = CaseResult(case, record, evaluate(case, record))
        if judge_model and not record.error:
            res.judge = await judge(judge_model, case, record)
        results.append(res)
        print(f"{'pass' if res.passed else 'FAIL'}  {case.id}  ({time.perf_counter() - t0:.1f}s)")
    return results


# ---------------------------------------------------------------- report
def render(results: list[CaseResult], retrieval: dict[str, Any] | None, meta: dict[str, Any]) -> str:
    lines = [
        f"# Eval report, {meta['started']}",
        "",
        f"Model `{meta['model']}`, triage `{meta['triage_model']}`, prompts `{meta['prompt_version']}`.",
        "",
    ]
    if results:
        passed = sum(r.passed for r in results)
        lines += [
            f"**Agent cases: {passed}/{len(results)} passed** ({passed / len(results):.0%})",
            "",
            "| Area | Checks passed |",
            "|---|---|",
        ]
        for cat, (ok, total) in category_scores(results).items():
            lines.append(f"| {cat.replace('_', ' ')} | {ok}/{total} |")
        judged = [r.judge for r in results if r.judge]
        if judged:
            avg = {
                k: sum(float(str(j[k])) for j in judged) / len(judged)
                for k in ("helpfulness", "groundedness", "tone")
            }
            lines += ["", "LLM judge (1-5): " + ", ".join(f"{k} {v:.2f}" for k, v in avg.items())]
        lines += ["", "| Case | Result | Failed checks |", "|---|---|---|"]
        for r in results:
            failed = "; ".join(f"{c.name} ({c.detail})" for c in r.checks if not c.passed) or (
                r.record.error or ""
            )
            lines.append(f"| {r.case.id} | {'pass' if r.passed else 'FAIL'} | {failed} |")
    if retrieval:
        lines += [
            "",
            f"**Retrieval ({retrieval['embedder']}):** recall@{retrieval['k']} "
            f"{retrieval['recall']:.0%}, MRR {retrieval['mrr']:.2f} over {retrieval['cases']} queries",
        ]
        for m in retrieval["misses"]:
            lines.append(f"- missed: “{m['query']}” expected {m['expected']}, got {m['got']}")
    return "\n".join(lines) + "\n"


async def main_async(args: argparse.Namespace) -> int:
    settings: Settings = get_settings()
    embedder = build_embedder(settings)
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    started = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    results: list[CaseResult] = []
    retrieval = None
    try:
        await ingest(sessions, embedder, load_directory(settings.kb_dir), settings)
        if args.only in (None, "agents"):
            c = await build_container(settings, embedder=embedder)  # real LLMs; needs API keys
            try:
                results = await run_agent_cases(c, settings, args)
            finally:
                await c.aclose()
        if args.only in (None, "retrieval"):
            retrieval = await run_retrieval(sessions, embedder)
    finally:
        await engine.dispose()

    from support.agents.prompts import PROMPT_VERSION

    meta = {
        "started": started,
        "model": settings.llm_model,
        "triage_model": settings.triage_model,
        "prompt_version": PROMPT_VERSION,
    }
    report = render(results, retrieval, meta)
    out = EVALS_DIR / "reports"
    out.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (out / f"{stamp}.md").write_text(report)
    (out / f"{stamp}.json").write_text(
        json.dumps(
            {
                "meta": meta,
                "retrieval": retrieval,
                "cases": [
                    {
                        "id": r.case.id,
                        "passed": r.passed,
                        "judge": r.judge,
                        "error": r.record.error,
                        "checks": [c.__dict__ for c in r.checks],
                        "reply": r.record.final_reply,
                    }
                    for r in results
                ],
            },
            indent=2,
            default=str,
        )
    )
    print("\n" + report)

    rate = sum(r.passed for r in results) / len(results) if results else 1.0
    if rate < args.min_pass or (retrieval and retrieval["recall"] < args.min_recall):
        return 1
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", choices=["agents", "retrieval"])
    p.add_argument("--case", action="append", help="run only this case id (repeatable)")
    p.add_argument("--judge", action="store_true", help="add LLM-as-judge quality scores")
    p.add_argument("--min-pass", type=float, default=0.85, help="minimum agent case pass rate")
    p.add_argument("--min-recall", type=float, default=0.85, help="minimum retrieval recall@3")
    raise SystemExit(asyncio.run(main_async(p.parse_args())))


if __name__ == "__main__":
    main()
