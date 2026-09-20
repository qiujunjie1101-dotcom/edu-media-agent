"""human_select_topic 节点：人工中断点 #1（等待运营人员选题）。

============================================================================
中断是怎么工作的？
============================================================================
节点第一行调用 ``interrupt(payload)``：

1. 首次执行时，它会抛出一个特殊异常，图立刻暂停并把 ``payload`` 交给调用方，
   同时把「当前停在哪个节点、状态是什么」写入检查点；
2. 调用方用 ``graph.ainvoke(Command(resume=值), config)`` 恢复时，
   该节点会**从头重新执行**，此时 ``interrupt(...)`` 不再暂停，
   而是直接返回调用方传入的 ``resume`` 值。

由此引出两条必须遵守的规则（本文件严格照做）：

- ``interrupt()`` 必须是节点里**第一条语句**，且**无条件执行**
  （不能放在 if 分支里，否则恢复时会因为逻辑分支不同而错位）；
- ``interrupt()`` 之前**不得有任何副作用**（写库、调外部 API 等），
  因为恢复时这段代码会再跑一遍。
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.core.exceptions import ActionNotAllowedError, TopicNotFoundError
from app.graph.nodes import NodeResult
from app.graph.routing import SELECT_TOPIC_ACTION
from app.graph.state import MediaWorkflowState, WorkflowStatus


async def human_select_topic(state: MediaWorkflowState) -> NodeResult:
    """暂停工作流，等待人工从候选选题中选一个。

    参数:
        state: 当前状态（读取 generated_topics 用于构造中断载荷）

    返回:
        NodeResult: 选中题目与状态推进

    异常:
        ActionNotAllowedError: 恢复动作不是 select_topic
        TopicNotFoundError: topic_id 不在候选选题中

    """
    # ↓ 必须是第一条语句：把候选选题和允许的动作交给调用方
    resume_value: Any = interrupt(
        {
            "type": "topic_selection",
            "topics": state["generated_topics"],
            "allowed_actions": [SELECT_TOPIC_ACTION],
        }
    )

    # ↓ 从这里开始，说明已经拿到人工输入（恢复值）
    if not isinstance(resume_value, dict) or resume_value.get("action") != SELECT_TOPIC_ACTION:
        raise ActionNotAllowedError(
            f"选题中断点只接受 action={SELECT_TOPIC_ACTION!r}，收到：{resume_value!r}"
        )

    topic_id = resume_value.get("topic_id")
    selected = next(
        (topic for topic in state["generated_topics"] if topic.get("id") == topic_id),
        None,
    )
    if selected is None:
        raise TopicNotFoundError(
            f"候选选题中不存在 id={topic_id!r}，可选："
            f"{[topic.get('id') for topic in state['generated_topics']]}"
        )

    return {
        "selected_topic": selected,
        "status": WorkflowStatus.DRAFTING.value,
    }
