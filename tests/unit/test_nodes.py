"""不含中断的节点单元测试。

为什么这四个节点可以单独测试？
    它们内部没有调用 ``interrupt()``，只是「读状态 → 调服务 → 返回要更新的字段」，
    因此可以在图之外直接调用，测试更快、失败原因也更清楚。

注意：测试里调用的是「构图函数」返回的节点函数
（``build_xxx_node(service)``），这正是 builder 在构图时做的事，
所以单元测试和真实运行用的是同一份代码路径。
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ContentValidationError, ImageGenerationFailedError
from app.graph.nodes.extract_visuals import build_extract_visuals_node
from app.graph.nodes.generate_images import build_generate_images_node
from app.graph.nodes.plan_topics import build_plan_topics_node
from app.graph.nodes.write_draft import build_write_draft_node
from app.graph.state import MediaWorkflowState, WorkflowStatus
from app.schemas.domain import ImageAsset, ImageAssetStatus, TopicCandidate
from app.services.image.base import ImageService
from app.services.image.mock import MockImageService
from app.services.llm.mock import MockLLMService

DIRECTION = "面向零基础学员讲清楚 LangGraph 的检查点机制"
FEEDBACK = "请补充一个最小可运行示例，并压缩开头铺垫"


def _base_state(**overrides: object) -> MediaWorkflowState:
    """构造一份「字段齐全」的状态，再按需覆盖个别字段。"""
    state: MediaWorkflowState = {
        "topic_direction": DIRECTION,
        "generated_topics": [],
        "selected_topic": None,
        "article_content": None,
        "review_action": None,
        "review_feedback": None,
        "visual_points": [],
        "image_assets": [],
        "status": WorkflowStatus.PLANNING,
        "error_message": None,
        "revision_count": 0,
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


# ---------------------------------------------------------------------------
# plan_topics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_topics_writes_generated_topics_and_status() -> None:
    """节点把模型结果转成普通字典写入状态，并把状态推进到「等待选题」。"""
    node = build_plan_topics_node(MockLLMService())

    update = await node(_base_state())

    assert set(update) == {"generated_topics", "status"}
    assert 3 <= len(update["generated_topics"]) <= 5
    # 写入的必须是普通 dict，而不是 Pydantic 实例——否则检查点无法序列化
    assert all(isinstance(topic, dict) for topic in update["generated_topics"])
    assert update["status"] == WorkflowStatus.AWAITING_TOPIC_SELECTION


# ---------------------------------------------------------------------------
# write_draft
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_draft_first_round_keeps_revision_count_zero() -> None:
    """初稿（无修改意见）：revision_count 保持 0，且清空上一轮的审核结论。"""
    node = build_write_draft_node(MockLLMService())
    topic = (await MockLLMService().plan_topics(DIRECTION))[0]
    state = _base_state(
        selected_topic=topic.model_dump(mode="json"),
        review_action="approve",  # 上一轮遗留的审核结论，必须被清空
        review_feedback=None,  # 初稿没有修改意见
        revision_count=0,
    )

    update = await node(state)

    assert update["revision_count"] == 0
    assert update["review_action"] is None
    assert update["review_feedback"] is None
    assert update["status"] == WorkflowStatus.AWAITING_REVIEW
    assert topic.title in update["article_content"]


@pytest.mark.asyncio
async def test_write_draft_rewrite_increments_revision_count_and_uses_feedback() -> None:
    """重写：revision_count 加 1，并把本轮意见体现在新稿里。"""
    node = build_write_draft_node(MockLLMService())
    topic = (await MockLLMService().plan_topics(DIRECTION))[0]
    state = _base_state(
        selected_topic=topic.model_dump(mode="json"),
        review_action="revise",
        review_feedback=FEEDBACK,
        revision_count=1,
    )

    update = await node(state)

    assert update["revision_count"] == 2
    assert FEEDBACK in update["article_content"]
    assert update["review_action"] is None
    assert update["review_feedback"] is None


@pytest.mark.asyncio
async def test_write_draft_requires_selected_topic() -> None:
    """未选题就写作属于流程错误，必须显式报错而不是生成空文章。"""
    node = build_write_draft_node(MockLLMService())

    with pytest.raises(ContentValidationError):
        await node(_base_state())


# ---------------------------------------------------------------------------
# extract_visuals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_visuals_writes_ordered_points() -> None:
    """视觉要点写入状态，order 从 1 连续递增，状态推进到「生成图片」。"""
    node = build_extract_visuals_node(MockLLMService())
    article = await MockLLMService().write_article(
        TopicCandidate(id="t1", title="测试标题", angle="原理拆解", reason="测试理由")
    )

    update = await node(_base_state(article_content=article))

    points = update["visual_points"]
    assert 3 <= len(points) <= 5
    assert [point["order"] for point in points] == list(range(1, len(points) + 1))
    assert update["status"] == WorkflowStatus.GENERATING_IMAGES


@pytest.mark.asyncio
async def test_extract_visuals_rejects_empty_article() -> None:
    """文章为空说明流程被错误驱动，必须报错。"""
    node = build_extract_visuals_node(MockLLMService())

    with pytest.raises(ContentValidationError):
        await node(_base_state(article_content=None))


# ---------------------------------------------------------------------------
# generate_images
# ---------------------------------------------------------------------------


class _StubImageService(ImageService):
    """测试替身：可按需让指定的 visual_point_id 失败，或让全部失败。

    真实实现（S1 的 Mock 与将来的真实图床）永远返回 ImageAsset；
    这里额外演示「服务直接抛异常」的情况，验证节点也能兜住。
    """

    def __init__(self, fail_ids: set[str] | None = None, fail_all: bool = False) -> None:
        self._fail_ids = fail_ids or set()
        self._fail_all = fail_all
        self.calls: list[str] = []

    async def generate(self, prompt: str, size: str, visual_point_id: str) -> ImageAsset:
        self.calls.append(visual_point_id)
        if self._fail_all:
            raise RuntimeError("模拟图片服务不可用")

        if visual_point_id in self._fail_ids:
            return ImageAsset(
                visual_point_id=visual_point_id,
                status=ImageAssetStatus.FAILED,
                url=None,
                error="模拟失败：图片服务超时",
            )

        return ImageAsset(
            visual_point_id=visual_point_id,
            status=ImageAssetStatus.SUCCESS,
            url=f"https://mock.local/images/{visual_point_id}.png",
            error=None,
        )


def _visual_points(count: int = 3) -> list[dict]:
    """构造 count 个视觉要点（结构照抄 MockLLMService 的输出）。"""
    return [
        {
            "id": f"vp{index + 1}",
            "order": index + 1,
            "title": f"要点 {index + 1}",
            "point": f"第 {index + 1} 个要点内容",
            "prompt": f"知识卡片提示词 {index + 1}",
        }
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_generate_images_all_success() -> None:
    """全部成功：状态 completed，且结果与视觉要点一一对应。"""
    service = _StubImageService()
    node = build_generate_images_node(service)

    update = await node(_base_state(visual_points=_visual_points(4)))

    assets = update["image_assets"]
    assert update["status"] == WorkflowStatus.COMPLETED
    assert update["error_message"] is None
    assert [asset["visual_point_id"] for asset in assets] == ["vp1", "vp2", "vp3", "vp4"]
    assert all(asset["status"] == "success" for asset in assets)
    # 并发调用次数与要点数量一致
    assert sorted(service.calls) == ["vp1", "vp2", "vp3", "vp4"]


@pytest.mark.asyncio
async def test_generate_images_partial_failure_keeps_alignment() -> None:
    """部分失败：成功与失败结果都保留，且 visual_point_id 对应关系不乱。"""
    node = build_generate_images_node(_StubImageService(fail_ids={"vp2"}))

    update = await node(_base_state(visual_points=_visual_points(3)))

    assets = {asset["visual_point_id"]: asset for asset in update["image_assets"]}
    assert update["status"] == WorkflowStatus.COMPLETED_WITH_WARNINGS
    assert assets["vp1"]["status"] == "success"
    assert assets["vp2"]["status"] == "failed"
    assert assets["vp2"]["url"] is None
    assert "超时" in assets["vp2"]["error"]
    assert assets["vp3"]["status"] == "success"
    assert "vp2" in update["error_message"]


@pytest.mark.asyncio
async def test_generate_images_handles_service_exception_as_failure() -> None:
    """图片服务抛异常也属于单张失败（可降级），不应让整条流程失败。"""
    node = build_generate_images_node(_StubImageService(fail_all=True))

    with pytest.raises(ImageGenerationFailedError):
        await node(_base_state(visual_points=_visual_points(2)))


@pytest.mark.asyncio
async def test_generate_images_all_failed_raises() -> None:
    """全部失败必须抛 ImageGenerationFailedError，绝不返回假成功。"""
    node = build_generate_images_node(_StubImageService(fail_ids={"vp1", "vp2"}))

    with pytest.raises(ImageGenerationFailedError):
        await node(_base_state(visual_points=_visual_points(2)))


@pytest.mark.asyncio
async def test_generate_images_rejects_empty_visual_points() -> None:
    """没有视觉要点时不生成空结果，直接报错。"""
    node = build_generate_images_node(MockImageService())

    with pytest.raises(ContentValidationError):
        await node(_base_state(visual_points=[]))
