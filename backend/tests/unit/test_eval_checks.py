from pathlib import Path

import yaml

from support.evals.checks import Case, CaseResult, RunRecord, category_scores, evaluate

EVALS = Path(__file__).resolve().parents[2] / "evals"


def record(**kw: object) -> RunRecord:
    base: dict[str, object] = dict(
        route="billing",
        agents={"billing"},
        final_agent="billing",
        tools=["request_refund"],
        final_reply="Refunded $29.00.",
        refunds={"INV-2002": "approved"},
        returns=set(),
        tickets=0,
    )
    return RunRecord(**{**base, **kw})  # type: ignore[arg-type]


def test_all_eval_cases_are_valid_and_unique() -> None:
    cases = [Case.model_validate(c) for c in yaml.safe_load((EVALS / "agent_cases.yaml").read_text())]
    assert len(cases) >= 15
    assert len({c.id for c in cases}) == len(cases)


def test_checks_pass_and_fail_as_expected() -> None:
    case = Case.model_validate(
        {
            "id": "x",
            "customer": "C001",
            "turns": ["hi"],
            "expect": {
                "route": "billing",
                "tools": ["request_refund"],
                "no_tools": ["start_return"],
                "reply_any": ["29"],
                "reply_none": ["4242"],
                "refund": {"INV-2002": "approved", "INV-2005": "none"},
            },
        }
    )
    assert all(c.passed for c in evaluate(case, record()))
    failed = {c.name for c in evaluate(case, record(route="orders", final_reply="card 4242")) if not c.passed}
    assert failed == {"route", "reply_any", "reply_none:4242"}


def test_run_errors_fail_the_case() -> None:
    case = Case.model_validate({"id": "x", "customer": "C001", "turns": ["hi"], "expect": {}})
    res = CaseResult(case, record(error="boom"), evaluate(case, record(error="boom")))
    assert not res.passed


def test_category_scores_bucket_checks() -> None:
    case = Case.model_validate(
        {
            "id": "x",
            "customer": "C001",
            "turns": ["hi"],
            "expect": {"route": "billing", "tools": ["request_refund"]},
        }
    )
    res = CaseResult(case, record(), evaluate(case, record()))
    scores = category_scores([res])
    assert scores["routing"] == (1, 1) and scores["tool_use"] == (1, 1)
