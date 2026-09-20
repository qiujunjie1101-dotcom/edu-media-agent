"""write_draft 节点：撰写初稿或按人工意见重写。

同一个节点承担两件事，靠「进入时有没有 review_feedback」区分：

- 初稿：没有修改意见，``revision_count`` 保持 0；
- 重写：带着上一轮的意见重新生成，``revision_count`` 加 1。

无论哪种情况，新稿都会**整体覆盖**旧稿，并清空上一轮的审核字段——
否则下游（或前端）可能把上一轮的结论误当成这一轮的。
"""

from __future__ import annotations

from app.core.exceptions import ContentValidationError
from app.graph.nodes import NodeFunc, NodeResult
from app.graph.state import MediaWorkflowState, WorkflowStatus
from app.schemas.domain import TopicCandidate
from app.services.llm.base import LLMService


def build_write_draft_node(llm_service: LLMService) -> NodeFunc:
    """创建 write_draft 节点。

    参数:
        llm_service: 文本模型服务（构图时注入）

    返回:
        NodeFunc: 可注册到 StateGraph 的异步节点函数

    """

    async def write_draft(state: MediaWorkflowState) -> NodeResult:
        """生成文章并写回状态。"""
        raw_topic = state["selected_topic"]
        if raw_topic is None:
            # 未选题就写作说明流程被错误驱动（例如绕过中断直接 UPDATE 状态）
            raise ContentValidationError("尚未选择选题，无法生成文章")

        # 状态里存的是普通字典，这里用领域模型「重新校验」一遍：
        # 既能拿到类型化的属性访问，又能在结构损坏时立刻失败。
        topic = TopicCandidate.model_validate(raw_topic)

        feedback = state["review_feedback"]
        article = await llm_service.write_article(topic, feedback=feedback)

        # 有意见 = 本次是重写，计数 +1；初稿不计数
        revision_count = state["revision_count"] + (1 if feedback else 0)

        return {
            "article_content": article,
            # 清空上一轮审核结论，避免污染下一轮判断
            "review_action": None,
            "review_feedback": None,
            "revision_count": revision_count,
            "status": WorkflowStatus.AWAITING_REVIEW.value,
        }

    return write_draft
