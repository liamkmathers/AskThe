"""Eval: automated checks per answer, costs, and a run over both retrieval modes."""

from pathlib import Path

import pytest

from askthe.config import ConfigError, load_questions
from askthe.core.evaluation import Expected, Price, TestQuestion, cost, mentions, recall, score
from askthe.core.interfaces import LLMTask
from askthe.core.models import Coverage
from askthe.core.retrieval import PassageScore, QueryPlan, RerankDraft
from askthe.pipeline.ask import RetrievalSettings
from askthe.pipeline.evaluate import run_eval
from tests import factories as f
from tests.test_retrieval import answer, build


def question(qid="q1", covered=Coverage.FULL, **expected):
    return TestQuestion(
        id=qid, question="What keeps his feet warm?", expected=Expected(covered=covered, **expected)
    )


def test_mentions_ignores_case_accents_punctuation_and_takes_alternatives():
    assert mentions("He loves the Arc’téryx Beta.", "arcteryx | arc teryx")
    assert mentions("Red Wing 875s", "red wing")
    assert not mentions("Redwings", "red wing")  # whole words only
    assert mentions("He loves Blundstones", "Blundstone")  # plurals count


def test_score_checks_coverage_citations_mentions_and_sources():
    q = question(must_mention=["Red Wing"], must_not_claim=["waterproof"], sources=["boots"])
    good = score(
        q, "He keeps warm in Red Wings, Red Wing boots.", Coverage.FULL, ["boots"], ["boots"], 0
    )
    assert good["passed"] and good["sources_cited"] == ["boots"] and good["coverage_exact"]
    partial = score(q, "Red Wing", Coverage.PARTIAL, ["boots"], ["boots"], 0)
    assert partial["coverage_right"] and not partial["coverage_exact"]
    bad = score(q, "The Red Wing is waterproof.", Coverage.FULL, [], ["other"], 1)
    assert not bad["passed"]
    assert not bad["cited"] and not bad["citations_hold"] and bad["must_not_claim_found"]
    assert bad["sources_read"] == []


def test_not_covered_questions_pass_only_when_the_answer_says_so():
    q = question(covered=Coverage.NONE)
    assert score(q, "Not covered.", Coverage.NONE, [], [], 0)["passed"]
    wrong = score(q, "He likes it.", Coverage.PARTIAL, ["x"], ["x"], 0)
    assert not wrong["coverage_right"] and not wrong["passed"]


def test_a_question_can_accept_more_than_one_coverage_level():
    q = question(covered=[Coverage.NONE, Coverage.PARTIAL])
    assert score(q, "Only in passing.", Coverage.PARTIAL, ["x"], ["x"], 0)["passed"]
    assert score(q, "Not covered.", Coverage.NONE, [], [], 0)["passed"]
    assert not score(q, "He loves it.", Coverage.FULL, ["x"], ["x"], 0)["passed"]


def test_rescore_rechecks_a_saved_run_and_drops_reworded_questions():
    from askthe.pipeline.evaluate import rescore

    def result(text, coverage):
        return {
            "answer": text,
            "coverage": coverage,
            "sources": [],
            "videos_read": [],
            "problems": [],
            "context_words": 0,
            "cost_usd": 0.0,
            "checks": {"passed": False, "recall_of_full": 0.5},
        }

    run = {
        "modes": ["hybrid"],
        "questions": [
            {
                "id": "q1",
                "question": "What keeps his feet warm?",
                "results": {"hybrid": result("Not covered.", "none")},
            },
            {"id": "q2", "question": "Old wording", "results": {"hybrid": result("x", "none")}},
        ],
    }
    test_set = [question("q1", covered=Coverage.NONE), question("q2", covered=Coverage.NONE)]
    new = rescore(run, test_set)
    assert [q["id"] for q in new["questions"]] == ["q1"]
    checks = new["questions"][0]["results"]["hybrid"]["checks"]
    assert checks["passed"] and checks["recall_of_full"] == 0.5
    assert new["summary"]["hybrid"]["passed_checks"] == 1


def test_cost_needs_a_price_for_every_model():
    prices = {"big": Price(input=4, output=20, cache_read=0.2, cache_write=5)}
    usage = {"big": {"input": 1_000_000, "output": 100_000, "cache_read": 1_000_000}}
    assert cost(usage, prices) == pytest.approx(4 + 2 + 0.2)
    assert cost(usage | {"unknown": {"input": 1}}, prices) is None


def test_recall_of_the_reference_citations():
    assert recall(["a", "b"], ["b", "c"]) == 0.5
    assert recall([], ["b"]) is None


def test_load_questions_validates_the_test_set(tmp_path: Path):
    path = tmp_path / "set.yaml"
    path.write_text(
        "- id: q1\n  question: Best boots?\n  expected: {covered: full, must_mention: [Red Wing]}\n"
    )
    assert load_questions(path)[0].expected.must_mention == ["Red Wing"]
    path.write_text(path.read_text() * 2)
    with pytest.raises(ConfigError, match="repeat"):
        load_questions(path)
    path.write_text("- id: q1\n  question: x\n  expected: {covered: maybe}\n")
    with pytest.raises(ConfigError):
        load_questions(path)


def test_run_scores_both_modes_and_hybrid_recall_of_full():
    store, search, llm, vectors, embedder = build()
    llm.script(LLMTask.PLAN, QueryPlan(queries=["warm winter boots"], names=[], broad=False))

    def rerank(context, prompt):
        parts = prompt.split("<passage n=")[1:]
        best = next(i for i, part in enumerate(parts) if "kept my feet warm" in part)
        return RerankDraft(scores=[PassageScore(n=best, score=3)])

    llm.script(LLMTask.RERANK, rerank)
    llm.script(LLMTask.ANSWER, answer("boots", 1, "kept my feet warm in the snow"))
    llm.script(LLMTask.ANSWER, answer("boots", 1, "kept my feet warm in the snow"))
    q = question(must_mention=["Red Wings"], sources=["boots"])

    run = run_eval(
        f.creator(),
        [q],
        ["hybrid", "full"],
        store,
        search,
        llm,
        vectors,
        embedder,
        RetrievalSettings(),
        prices={"memory": Price(input=1, output=1)},
        label="test",
    )
    hybrid, full = (run["questions"][0]["results"][m] for m in ("hybrid", "full"))
    assert hybrid["checks"]["passed"] and full["checks"]["passed"]
    assert hybrid["checks"]["recall_of_full"] == 1.0
    assert hybrid["context_words"] < full["context_words"]
    assert hybrid["correct"] is None and hybrid["cost_usd"] == 0.0
    assert run["summary"]["hybrid"]["passed_checks"] == 1
    assert run["summary"]["hybrid"]["mean_recall_of_full"] == 1.0
    assert [c[0] for c in llm.calls] == [
        LLMTask.PLAN,
        LLMTask.RERANK,
        LLMTask.ANSWER,
        LLMTask.ANSWER,
    ]  # every hybrid question, then every full one: full mode's context stays cached
