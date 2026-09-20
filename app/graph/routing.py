"""节点名常量与审核后的条件路由。

============================================================================
为什么节点名要抽成常量？
============================================================================
LangGraph 用「字符串」把节点、边、条件路由串联起来。字符串写错不会有任何编译期
报错，只会表现为「流程莫名走不到某个节点」。把它们定义成常量后：

- 注册节点（builder）与条件路由（routing）引用的是同一个常量，不可能不一致；
- IDE 能改名、能跳转。

============================================================================
为什么路由必须是纯函数？
============================================================================
条件路由的职责只有一个：**根据当前状态决定下一个节点是谁**。
它不能写状态、不能调用服务、不能有副作用，原因有三：

1. 路由函数可能被多次调用（框架需要决定走向），有副作用就会重复执行；
2. 状态的所有变化都应发生在节点里，这样检查点里的因果是清晰的；
3. 纯函数好测试——给输入、断言输出即可（见 tests/unit/test_routing.py）。
"""

from __future__ import annotations

from typing import Final

from app.core.exceptions import ActionNotAllowedError
from app.graph.state import MediaWorkflowState

# ---------------------------------------------------------------------------
# 节点名常量（与 builder.py 注册的节点名一一对应）
# ---------------------------------------------------------------------------

PLAN_TOPICS_NODE: Final = "plan_topics"
HUMAN_SELECT_TOPIC_NODE: Final = "human_select_topic"
WRITE_DRAFT_NODE: Final = "write_draft"
HUMAN_REVIEW_NODE: Final = "human_review"
EXTRACT_VISUALS_NODE: Final = "extract_visuals"
GENERATE_IMAGES_NODE: Final = "generate_images"

# ---------------------------------------------------------------------------
# 人工动作常量（中断载荷与恢复值共用同一套字面量）
# ---------------------------------------------------------------------------

SELECT_TOPIC_ACTION: Final = "select_topic"
APPROVE_ACTION: Final = "approve"
REVISE_ACTION: Final = "revise"


def route_after_review(state: MediaWorkflowState) -> str:
    """审稿之后的分支决策。

    参数:
        state: 当前工作流状态（只读取 review_action）

    返回:
        str: 下一个节点名——"extract_visuals"（通过）或 "write_draft"（驳回）

    异常:
        ActionNotAllowedError: review_action 不是 approve / revise 时抛出。
            这里刻意**不设置默认分支**：未知动作意味着流程状态异常，
            静默放行会让「未审核就生图」的风险变成现实。

    说明:
        达到驳回上限时，本函数不需要特殊处理：超限的 revise 已经在
        human_review 节点内被 RevisionLimitReachedError 拒绝，
        根本走不到这里，因此这里也就不会出现「隐式放行」的死角。
    """
    action = state["review_action"]

    if action == APPROVE_ACTION:
        return EXTRACT_VISUALS_NODE

    if action == REVISE_ACTION:
        return WRITE_DRAFT_NODE

    raise ActionNotAllowedError(f"未知的审核动作：{action!r}，只允许 {APPROVE_ACTION} 或 {REVISE_ACTION}")
