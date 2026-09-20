"""extract_visuals 节点：把终稿提炼成小红书知识卡片要点。

这个节点**只有一条入口**：``human_review`` 返回 approve 之后的条件路由。
图结构本身就是「未通过人工审核不得生图」这条业务约束的硬保证。
"""

from __future__ import annotations

from app.core.exceptions import ContentValidationError
from app.graph.nodes import NodeFunc, NodeResult
from app.graph.state import MediaWorkflowState, WorkflowStatus
from app.services.llm.base import LLMService


def build_extract_visuals_node(llm_service: LLMService) -> NodeFunc:
    """创建 extract_visuals 节点。

    参数:
        llm_service: 文本模型服务（构图时注入）

    返回:
        NodeFunc: 可注册到 StateGraph 的异步节点函数

    """

    async def extract_visuals(state: MediaWorkflowState) -> NodeResult:
        """读取终稿 → 提炼视觉要点 → 写入状态。"""
        article = state["article_content"]
        if not article:
            # article_content 的类型是 str | None，这里既做类型收窄也做业务校验
            raise ContentValidationError("文章内容为空，无法提炼视觉要点")

        points = await llm_service.extract_visual_points(article)

        return {
            "visual_points": [point.model_dump(mode="json") for point in points],
            "status": WorkflowStatus.GENERATING_IMAGES.value,
        }

    return extract_visuals
