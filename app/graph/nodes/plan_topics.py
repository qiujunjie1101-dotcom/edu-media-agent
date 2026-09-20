"""plan_topics 节点：调用文本模型生成候选选题。

这是工作流的第一个节点，输入只有「内容方向」，输出是 3–5 个候选选题。
写完状态后立刻进入人工选题中断点（``human_select_topic``）。
"""

from __future__ import annotations

from app.graph.nodes import NodeFunc, NodeResult
from app.graph.state import MediaWorkflowState, WorkflowStatus
from app.services.llm.base import LLMService


def build_plan_topics_node(llm_service: LLMService) -> NodeFunc:
    """创建 plan_topics 节点。

    参数:
        llm_service: 文本模型服务（构图时注入，节点内不创建实例）

    返回:
        NodeFunc: 可注册到 StateGraph 的异步节点函数

    """

    async def plan_topics(state: MediaWorkflowState) -> NodeResult:
        """读取内容方向 → 生成候选选题 → 写入状态。"""
        topics = await llm_service.plan_topics(state["topic_direction"])

        return {
            # 每一步都把领域模型转成普通字典再放进状态：
            # 状态最终要序列化进检查点，不能有 Pydantic 实例。
            "generated_topics": [topic.model_dump(mode="json") for topic in topics],
            # 状态推进：告诉调用方「现在等你选题」
            # .value 取得纯字符串，避免检查点出现自定义类型（见 state.py 的说明）
            "status": WorkflowStatus.AWAITING_TOPIC_SELECTION.value,
        }

    return plan_topics
