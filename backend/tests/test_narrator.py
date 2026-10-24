"""The LLM layer, exercised with a stub model so it runs without Azure credentials."""
import asyncio
import json

from footie.pipeline.explain import Narrator
from footie.pipeline.personalize import Profile
from footie.pipeline.runner import MatchSession
from footie.sim.scenarios import load_match


class StubLLM:
    def __init__(self, fail: bool = False):
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail

    async def complete_json(self, system: str, user: str, max_tokens: int = 300) -> dict:
        if self.fail:
            raise RuntimeError("service down")
        payload = json.loads(user)
        self.calls.append((system, payload))
        if "question" in payload:
            return {"answer": "Stub answer", "cites": ["i1"]}
        return {"headline": f"Stub {payload['moment']}", "body": "Grounded body"}


def _goal_session():
    s = MatchSession(load_match("comeback"))
    s.advance_to(1200)
    goal = next(i for i in s.insights.values() if i["kind"] == "goal")
    return s, goal


def test_rewrite_uses_only_facts_and_caches():
    s, goal = _goal_session()
    stub = StubLLM()
    narrator = Narrator(llm=stub)
    prof = Profile(mode="casual", language="sw", club="RVA")
    draft = s.personalize([o for o in s.overlays if o["insight_id"] == goal["id"]][0], prof)["text"]
    out = asyncio.run(narrator.rewrite(goal, prof, s.ctx, draft))
    assert out["headline"] == "Stub goal" and out["source"] == "llm"
    system, payload = stub.calls[0]
    assert "Kiswahili" in system and "Riverside Athletic" in system
    assert payload["why_it_matters"] and payload["facts"]["scorer"]
    asyncio.run(narrator.rewrite(goal, prof, s.ctx, draft))
    assert len(stub.calls) == 1  # cached


def test_rewrite_failure_falls_back_to_template():
    s, goal = _goal_session()
    narrator = Narrator(llm=StubLLM(fail=True))
    assert asyncio.run(narrator.rewrite(goal, Profile(), s.ctx, {"headline": "x"})) is None


def test_answer_with_and_without_llm():
    s, _ = _goal_session()
    ctx = s.ask_context(Profile())
    assert asyncio.run(Narrator(llm=StubLLM()).answer("why?", ctx, Profile(), s.ctx))["answer"] == "Stub answer"
    offline = Narrator(llm=False)
    ans = asyncio.run(offline.answer("What's the score?", ctx, Profile(), s.ctx))
    assert ans["source"] == "rules" and "Northbridge" in ans["answer"]
