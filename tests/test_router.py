from __future__ import annotations

from app.domain.models import Route
from app.infra.fakes import FakeChatModel
from app.skills.router import RouterSkill


async def test_router_routes_representative_intents() -> None:
    router = RouterSkill(chat_model=FakeChatModel())

    assert (await router.decide(query="销售总额口径是什么？")).route == Route.KNOWLEDGE
    assert (await router.decide(query="统计2026年7月销售额")).route == Route.DATA
    assert (
        await router.decide(query="结合库存制度分析当前库存并给出要求")
    ).route == Route.MIXED
    assert (await router.decide(query="这个")).route == Route.CLARIFY

