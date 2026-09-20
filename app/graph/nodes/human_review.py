"""human_review 节点：人工中断点 #2（等待运营人员通过 / 驳回）。

============================================================================
这个节点是整个流程的质量闸门
============================================================================
它保证两件事：

1. **没有人工 approve，绝不进入生图链路**（``extract_visuals`` 只有一个入口：
   本节点返回 action=approve 之后的条件路由）；
2. **驳回次数受控**：``revision_count`` 达到 ``max_revisions`` 后只允许 approve，
   此时若仍收到 revise，直接抛 ``RevisionLimitReachedError``，
   **不做自循环、不做自动放行**。

关于「超限」的处理为什么放在节点里而不是路由里？
    路由函数必须是纯函数（只决定去向，不写状态、不抛业务规则）。
    而「超限的 revise 是非法的」属于业务规则判断，必须发生在节点中：
    要么修改状态、要么抛错，二者都只有节点能做。
============================================================================
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.core.exceptions import (
    ActionNotAllowedError,
    ContentValidationError,
    RevisionLimitReachedError,
)
from app.graph.nodes import NodeFunc, NodeResult
from app.graph.routing import APPROVE_ACTION, REVISE_ACTION
from app.graph.state import MediaWorkflowState, WorkflowStatus

# 驳回意见的最小长度：太短的意见（例如「不行」）无法指导重写
MIN_FEEDBACK_LENGTH = 5


def build_human_review_node(max_revisions: int) -> NodeFunc:
    """创建 human_review 节点。

    参数:
        max_revisions: 允许的最大重写次数（来自配置，默认 3）

    返回:
        NodeFunc: 可注册到 StateGraph 的异步节点函数

    """

    async def human_review(state: MediaWorkflowState) -> NodeResult:
        """暂停工作流，等待人工审核当前文章。"""
        revision_count = state["revision_count"]
        limit_reached = revision_count >= max_revisions

        # 达到上限后只允许通过——前端/接口层据此隐藏「驳回」入口
        allowed_actions = [APPROVE_ACTION] if limit_reached else [APPROVE_ACTION, REVISE_ACTION]

        # ↓ 中断载荷里带上文章与计数，人工才能基于完整信息决策
        resume_value: Any = interrupt(
            {
                "type": "article_review",
                "article": state["article_content"],
                "revision_count": revision_count,
                "max_revisions": max_revisions,
                "revision_limit_reached": limit_reached,
                "allowed_actions": allowed_actions,
            }
        )

        if not isinstance(resume_value, dict):
            raise ActionNotAllowedError(f"审稿中断点需要字典形式的恢复值，收到：{resume_value!r}")

        action = resume_value.get("action")

        if action == APPROVE_ACTION:
            return {
                "review_action": APPROVE_ACTION,
                # 通过时清空修改意见，避免它被误当成下一轮的重写输入
                "review_feedback": None,
                "status": WorkflowStatus.EXTRACTING_VISUALS.value,
            }

        if action == REVISE_ACTION:
            # 超限驳回：直接拒绝，状态停在 awaiting_review，不允许进入生图
            if limit_reached:
                raise RevisionLimitReachedError(
                    f"文章已重写 {revision_count} 次，达到上限 {max_revisions}，"
                    f"此时只允许 {APPROVE_ACTION}"
                )

            feedback = (resume_value.get("feedback") or "").strip()
            if len(feedback) < MIN_FEEDBACK_LENGTH:
                raise ContentValidationError(
                    f"驳回时必须提供至少 {MIN_FEEDBACK_LENGTH} 个字符的修改意见，收到：{feedback!r}"
                )

            return {
                "review_action": REVISE_ACTION,
                "review_feedback": feedback,
                "status": WorkflowStatus.REVISING.value,
            }

        raise ActionNotAllowedError(
            f"审稿中断点只接受 {allowed_actions}，收到：{action!r}"
        )

    return human_review
