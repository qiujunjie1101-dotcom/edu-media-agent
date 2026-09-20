"""route_after_review 的单元测试。

重点验证三件事：

1. 映射正确：approve → extract_visuals，revise → write_draft；
2. **纯函数**：不写状态、不产生副作用、多次调用结果一致；
3. 非法动作必须抛 ActionNotAllowedError，而不是悄悄放行。
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.core.exceptions import ActionNotAllowedError
from app.graph.routing import (
    APPROVE_ACTION,
    EXTRACT_VISUALS_NODE,
    REVISE_ACTION,
    WRITE_DRAFT_NODE,
    route_after_review,
)


def _state_with_action(action: str | None) -> dict[str, Any]:
    """构造一个只关心 review_action 的最小状态。"""
    return {
        "topic_direction": "测试方向",
        "review_action": action,
        "review_feedback": "请补充示例" if action == REVISE_ACTION else None,
        "revision_count": 1,
        "article_content": "# 测试文章",
    }


def test_approve_routes_to_extract_visuals() -> None:
    """approve 唯一通往生图链路的第一站 extract_visuals。"""
    assert route_after_review(_state_with_action(APPROVE_ACTION)) == EXTRACT_VISUALS_NODE


def test_revise_routes_back_to_write_draft() -> None:
    """revise 回到写作节点，形成可重复执行的审核循环。"""
    assert route_after_review(_state_with_action(REVISE_ACTION)) == WRITE_DRAFT_NODE


@pytest.mark.parametrize("invalid_action", [None, "publish", "", "APPROVE"])
def test_unknown_action_raises(invalid_action: str | None) -> None:
    """未知动作（含 None、大小写写错、空串）必须报错，绝不默认放行。"""
    with pytest.raises(ActionNotAllowedError):
        route_after_review(_state_with_action(invalid_action))


def test_router_does_not_mutate_state() -> None:
    """纯函数验证：调用前后状态对象完全一致（深比较）。"""
    state = _state_with_action(REVISE_ACTION)
    before = copy.deepcopy(state)

    route_after_review(state)

    assert state == before


def test_router_is_repeatable() -> None:
    """同一输入多次调用返回同一结果，说明没有隐藏状态。"""
    state = _state_with_action(APPROVE_ACTION)

    results = {route_after_review(state) for _ in range(5)}

    assert results == {EXTRACT_VISUALS_NODE}


def test_router_only_reads_review_action() -> None:
    """路由只依赖 review_action：其它字段变化不影响结果。"""
    base = _state_with_action(APPROVE_ACTION)
    noisy = {**base, "revision_count": 99, "error_message": "随便填点东西", "image_assets": [{"x": 1}]}

    assert route_after_review(base) == route_after_review(noisy)
