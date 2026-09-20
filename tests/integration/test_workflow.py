"""工作流集成测试：直接驱动编译后的 Graph，覆盖两个人工中断点与驳回循环。

本文件不使用任何 HTTP 接口（那是 S3 的事），而是直接调用：

    await workflow.graph.ainvoke(初始状态, config)        # 启动
    await workflow.graph.ainvoke(Command(resume=...), config)  # 恢复

覆盖技术方案 v2 里 S2 的全部必测场景。
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.core.exceptions import (
    ActionNotAllowedError,
    ContentValidationError,
    ImageGenerationFailedError,
    RevisionLimitReachedError,
    TopicNotFoundError,
)
from app.graph.builder import CompiledWorkflow, build_workflow
from app.graph.state import MediaWorkflowState, WorkflowStatus
from app.schemas.domain import ImageAsset, ImageAssetStatus
from app.services.image.base import ImageService
from app.services.llm.mock import MockLLMService

MAX_REVISIONS = 3

DIRECTION = "面向零基础学员讲清楚 LangGraph 的检查点机制"
OTHER_DIRECTION = "新手如何准备 AI 训练师面试"

FEEDBACK_A = "请补充一个最小可运行示例"
FEEDBACK_B = "第二段太啰嗦，请压缩到三句话以内"
FEEDBACK_C = "请把代码示例换成伪代码"


# ---------------------------------------------------------------------------
# 测试替身与工具函数
# ---------------------------------------------------------------------------


class _StubImageService(ImageService):
    """可按需失败的图片服务替身，用来验证部分失败与全部失败两条路径。"""

    def __init__(self, fail_ids: set[str] | None = None, fail_all: bool = False) -> None:
        self._fail_ids = fail_ids or set()
        self._fail_all = fail_all

    async def generate(self, prompt: str, size: str, visual_point_id: str) -> ImageAsset:
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


def _initial_state(direction: str = DIRECTION) -> MediaWorkflowState:
    """工作流启动时的初始状态。"""
    return {
        "topic_direction": direction,
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


def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any]:
    """从 ainvoke 返回值里取出中断载荷。

    LangGraph 在中断时会在返回值里带上 ``__interrupt__``：一个 Interrupt 元组，
    其 ``.value`` 就是节点调用 ``interrupt(payload)`` 时传入的内容。
    """
    interrupts = result.get("__interrupt__")
    assert interrupts, f"期望图停在中断点，但没有拿到 __interrupt__：{list(result)}"
    return interrupts[0].value


async def _start(workflow: CompiledWorkflow, thread_id: str, direction: str = DIRECTION) -> dict:
    return await workflow.graph.ainvoke(_initial_state(direction), workflow.build_config(thread_id))


async def _resume(workflow: CompiledWorkflow, thread_id: str, value: dict) -> dict:
    return await workflow.graph.ainvoke(
        Command(resume=value),  # 1.x 的恢复方式：把人工输入作为恢复值交给被中断的节点
        workflow.build_config(thread_id),
    )


async def _snapshot(workflow: CompiledWorkflow, thread_id: str) -> Any:
    return await workflow.graph.aget_state(workflow.build_config(thread_id))


async def _select_topic(workflow: CompiledWorkflow, thread_id: str, topic_id: str = "t1") -> dict:
    return await _resume(workflow, thread_id, {"action": "select_topic", "topic_id": topic_id})


async def _revise(workflow: CompiledWorkflow, thread_id: str, feedback: str = FEEDBACK_A) -> dict:
    return await _resume(workflow, thread_id, {"action": "revise", "feedback": feedback})


async def _approve(workflow: CompiledWorkflow, thread_id: str) -> dict:
    return await _resume(workflow, thread_id, {"action": "approve"})


async def _scheduled_nodes(workflow: CompiledWorkflow, thread_id: str) -> set[str]:
    """汇总历史检查点里出现过的「即将执行节点」，用来证明某个节点从未被调度过。"""
    scheduled: set[str] = set()
    async for snapshot in workflow.graph.aget_state_history(workflow.build_config(thread_id)):
        scheduled.update(snapshot.next or ())
    return scheduled


# ---------------------------------------------------------------------------
# 场景 1–3：启动、选题
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_pauses_at_topic_selection_without_article(workflow: CompiledWorkflow) -> None:
    """场景 1：启动后停在人工选题中断点，尚未生成文章。"""
    result = await _start(workflow, "t-start")

    payload = _interrupt_payload(result)
    assert payload["type"] == "topic_selection"
    assert payload["allowed_actions"] == ["select_topic"]
    assert 3 <= len(payload["topics"]) <= 5

    assert result["topic_direction"] == DIRECTION
    assert len(result["generated_topics"]) == len(payload["topics"])
    # 关键：还没到写作环节
    assert result["article_content"] is None
    assert result["selected_topic"] is None
    assert result["revision_count"] == 0
    assert result["status"] == WorkflowStatus.AWAITING_TOPIC_SELECTION

    snapshot = await _snapshot(workflow, "t-start")
    assert snapshot.next == ("human_select_topic",)


@pytest.mark.asyncio
async def test_selecting_topic_generates_first_draft_and_pauses_for_review(
    workflow: CompiledWorkflow,
) -> None:
    """场景 2：选择合法题目后生成初稿，停在审稿点，revision_count 仍为 0。"""
    await _start(workflow, "t-first")
    result = await _select_topic(workflow, "t-first", topic_id="t2")

    payload = _interrupt_payload(result)
    assert payload["type"] == "article_review"
    assert payload["allowed_actions"] == ["approve", "revise"]
    assert payload["revision_count"] == 0
    assert payload["revision_limit_reached"] is False
    assert payload["article"] == result["article_content"]

    assert result["selected_topic"]["id"] == "t2"
    assert result["article_content"]
    assert result["revision_count"] == 0
    assert result["review_action"] is None
    assert result["review_feedback"] is None
    assert result["status"] == WorkflowStatus.AWAITING_REVIEW

    snapshot = await _snapshot(workflow, "t-first")
    assert snapshot.next == ("human_review",)


@pytest.mark.asyncio
async def test_invalid_topic_id_is_rejected(workflow: CompiledWorkflow) -> None:
    """场景 3：非法 topic_id 被拒绝，且状态保持原样。"""
    await _start(workflow, "t-bad-topic")

    with pytest.raises(TopicNotFoundError):
        await _select_topic(workflow, "t-bad-topic", topic_id="t99")

    snapshot = await _snapshot(workflow, "t-bad-topic")
    assert snapshot.values["status"] == WorkflowStatus.AWAITING_TOPIC_SELECTION
    assert snapshot.values["selected_topic"] is None
    assert snapshot.values["article_content"] is None


@pytest.mark.asyncio
async def test_action_not_allowed_at_topic_selection(workflow: CompiledWorkflow) -> None:
    """场景 3（续）：在选题中断点提交 approve 必须被拒绝。"""
    await _start(workflow, "t-bad-action")

    with pytest.raises(ActionNotAllowedError):
        await _resume(workflow, "t-bad-action", {"action": "approve"})

    snapshot = await _snapshot(workflow, "t-bad-action")
    assert snapshot.values["status"] == WorkflowStatus.AWAITING_TOPIC_SELECTION


@pytest.mark.asyncio
async def test_revise_with_too_short_feedback_is_rejected(workflow: CompiledWorkflow) -> None:
    """修改意见过短（少于 5 个字符）时拒绝重写。"""
    await _start(workflow, "t-short-feedback")
    await _select_topic(workflow, "t-short-feedback")

    with pytest.raises(ContentValidationError):
        await _revise(workflow, "t-short-feedback", "不行")

    snapshot = await _snapshot(workflow, "t-short-feedback")
    assert snapshot.values["status"] == WorkflowStatus.AWAITING_REVIEW
    assert snapshot.values["revision_count"] == 0


@pytest.mark.asyncio
async def test_failed_resume_leaves_errored_task_and_keeps_last_valid_state(
    workflow: CompiledWorkflow,
) -> None:
    """节点抛异常后，检查点保留最后一个有效状态，但该次任务被标记为 error。

    这是 LangGraph 1.2.11 的真实行为（用探针脚本确认过）：

    - ``aget_state().values`` 仍是失败前的中断状态（不会写入半成品数据）；
    - ``aget_state().next`` 变成空元组，``tasks[0].error`` 记录了异常；
    - 之后再用**新的** ``Command(resume=...)`` 调用，会重放这次失败任务的旧恢复值，
      仍然抛出同一个异常——也就是说：**一次非法恢复会让该 thread 卡住**。

    这正是要在 S3 的接口层做前置校验（动作是否在 allowed_actions 内、驳回是否超限）
    的原因：把非法请求挡在图之外，别让它有机会把会话弄脏。
    """
    await _start(workflow, "t-errored")

    with pytest.raises(TopicNotFoundError):
        await _select_topic(workflow, "t-errored", topic_id="t99")

    snapshot = await _snapshot(workflow, "t-errored")

    assert snapshot.next == ()
    assert len(snapshot.tasks) == 1
    assert snapshot.tasks[0].error is not None
    assert "TopicNotFoundError" in snapshot.tasks[0].error
    # 状态本身没有被破坏：仍停在「等待选题」，没有半个选中题目
    assert snapshot.values["status"] == WorkflowStatus.AWAITING_TOPIC_SELECTION
    assert snapshot.values["selected_topic"] is None


# ---------------------------------------------------------------------------
# 场景 4–6：驳回循环
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revise_creates_new_draft_and_clears_review_fields(workflow: CompiledWorkflow) -> None:
    """场景 4：驳回一次后生成新稿，revision_count=1，旧审核字段已清空。"""
    await _start(workflow, "t-revise")
    first = await _select_topic(workflow, "t-revise")
    first_draft = first["article_content"]

    result = await _revise(workflow, "t-revise", FEEDBACK_A)

    assert result["revision_count"] == 1
    assert result["article_content"] != first_draft
    assert FEEDBACK_A in result["article_content"]
    # 旧审核字段必须被清空，避免下游把上一轮结论当成这一轮的
    assert result["review_action"] is None
    assert result["review_feedback"] is None
    assert result["status"] == WorkflowStatus.AWAITING_REVIEW
    assert _interrupt_payload(result)["revision_count"] == 1


@pytest.mark.asyncio
async def test_two_revisions_then_approve_ends_with_revision_count_two(
    workflow: CompiledWorkflow,
) -> None:
    """场景 5：连续驳回两次后通过，最终 revision_count=2。"""
    await _start(workflow, "t-two")
    await _select_topic(workflow, "t-two")
    await _revise(workflow, "t-two", FEEDBACK_A)
    second = await _revise(workflow, "t-two", FEEDBACK_B)

    assert second["revision_count"] == 2
    assert FEEDBACK_B in second["article_content"]

    final = await _approve(workflow, "t-two")

    assert final["revision_count"] == 2
    assert final["status"] == WorkflowStatus.COMPLETED
    assert FEEDBACK_B in final["article_content"]


@pytest.mark.asyncio
async def test_extract_visuals_is_unreachable_before_approve(workflow: CompiledWorkflow) -> None:
    """场景 6：未 approve 前绝不能执行 extract_visuals。"""
    await _start(workflow, "t-noapprove")
    after_select = await _select_topic(workflow, "t-noapprove")
    after_revise = await _revise(workflow, "t-noapprove", FEEDBACK_A)
    after_second = await _revise(workflow, "t-noapprove", FEEDBACK_B)

    for state in (after_select, after_revise, after_second):
        assert state["visual_points"] == []
        assert state["image_assets"] == []
        assert state["status"] == WorkflowStatus.AWAITING_REVIEW

    # 更强的证据：历史检查点里 extract_visuals 从未被调度过
    assert "extract_visuals" not in await _scheduled_nodes(workflow, "t-noapprove")

    # 通过之后才允许进入，此时历史里才会出现 extract_visuals
    await _approve(workflow, "t-noapprove")
    assert "extract_visuals" in await _scheduled_nodes(workflow, "t-noapprove")


@pytest.mark.asyncio
async def test_revision_limit_only_allows_approve(workflow: CompiledWorkflow) -> None:
    """场景 7：连续驳回三次后只允许 approve；再次 revise 抛 RevisionLimitReachedError。"""
    await _start(workflow, "t-limit")
    await _select_topic(workflow, "t-limit")
    await _revise(workflow, "t-limit", FEEDBACK_A)
    await _revise(workflow, "t-limit", FEEDBACK_B)
    at_limit = await _revise(workflow, "t-limit", FEEDBACK_C)

    payload = _interrupt_payload(at_limit)
    assert at_limit["revision_count"] == MAX_REVISIONS
    assert payload["allowed_actions"] == ["approve"]
    assert payload["revision_limit_reached"] is True

    # 第四次驳回必须被拒绝
    with pytest.raises(RevisionLimitReachedError):
        await _revise(workflow, "t-limit", FEEDBACK_A)

    # 被拒绝后，检查点保留的仍是最后一个有效状态
    snapshot = await _snapshot(workflow, "t-limit")
    assert snapshot.values["status"] == WorkflowStatus.AWAITING_REVIEW
    assert snapshot.values["revision_count"] == MAX_REVISIONS
    assert snapshot.values["visual_points"] == []


# ---------------------------------------------------------------------------
# 场景 8–10：视觉要点与图片
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_produces_visual_points_and_images(workflow: CompiledWorkflow) -> None:
    """场景 8：approve 后完成视觉要点与图片生成，状态 completed。"""
    await _start(workflow, "t-images")
    await _select_topic(workflow, "t-images")

    final = await _approve(workflow, "t-images")

    points = final["visual_points"]
    assets = final["image_assets"]
    assert 3 <= len(points) <= 5
    assert final["status"] == WorkflowStatus.COMPLETED
    assert final["error_message"] is None
    assert [point["order"] for point in points] == list(range(1, len(points) + 1))
    # 图片与要点按 visual_point_id 一一对应
    assert [asset["visual_point_id"] for asset in assets] == [point["id"] for point in points]
    assert all(asset["status"] == "success" for asset in assets)
    assert all(asset["url"].endswith(f"{asset['visual_point_id']}.png") for asset in assets)


@pytest.mark.asyncio
async def test_partial_image_failure_returns_completed_with_warnings() -> None:
    """场景 9：图片部分失败返回 completed_with_warnings，对应关系仍然正确。"""
    partial_workflow = build_workflow(
        llm_service=MockLLMService(),
        image_service=_StubImageService(fail_ids={"vp2"}),
        max_revisions=MAX_REVISIONS,
    )

    await _start(partial_workflow, "t-partial")
    await _select_topic(partial_workflow, "t-partial")
    final = await _approve(partial_workflow, "t-partial")

    points = final["visual_points"]
    assets = {asset["visual_point_id"]: asset for asset in final["image_assets"]}
    assert final["status"] == WorkflowStatus.COMPLETED_WITH_WARNINGS
    assert len(final["image_assets"]) == len(points)
    assert assets["vp2"]["status"] == "failed"
    assert assets["vp2"]["error"]
    assert all(assets[point["id"]]["status"] == "success" for point in points if point["id"] != "vp2")
    assert "vp2" in final["error_message"]


@pytest.mark.asyncio
async def test_all_images_failing_raises_and_keeps_last_valid_state() -> None:
    """场景 10：图片全部失败抛 ImageGenerationFailedError，不写入假成功状态。"""
    failing_workflow = build_workflow(
        llm_service=MockLLMService(),
        image_service=_StubImageService(fail_all=True),
        max_revisions=MAX_REVISIONS,
    )

    await _start(failing_workflow, "t-failed")
    await _select_topic(failing_workflow, "t-failed")

    with pytest.raises(ImageGenerationFailedError):
        await _approve(failing_workflow, "t-failed")

    snapshot = await _snapshot(failing_workflow, "t-failed")
    # 失败的那一步没有写入检查点：状态停在生图之前
    assert snapshot.values["status"] == WorkflowStatus.GENERATING_IMAGES
    assert snapshot.values["image_assets"] == []


# ---------------------------------------------------------------------------
# 场景 11：thread_id 隔离
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_threads_are_fully_isolated(workflow: CompiledWorkflow) -> None:
    """场景 11：两个不同 thread_id 交错运行，状态完全隔离。"""
    await _start(workflow, "thread-a", DIRECTION)
    await _start(workflow, "thread-b", OTHER_DIRECTION)

    a = await _select_topic(workflow, "thread-a", topic_id="t1")
    b = await _select_topic(workflow, "thread-b", topic_id="t3")

    assert a["selected_topic"]["id"] == "t1"
    assert b["selected_topic"]["id"] == "t3"
    assert a["topic_direction"] != b["topic_direction"]
    assert a["article_content"] != b["article_content"]

    a_after_revise = await _revise(workflow, "thread-a", FEEDBACK_A)
    b_untouched = (await _snapshot(workflow, "thread-b")).values

    # A 的驳回不影响 B
    assert a_after_revise["revision_count"] == 1
    assert b_untouched["revision_count"] == 0
    assert b_untouched["review_action"] is None

    b_final = await _approve(workflow, "thread-b")
    a_state = (await _snapshot(workflow, "thread-a")).values

    assert b_final["status"] == WorkflowStatus.COMPLETED
    # B 完成后 A 仍然停在审稿点，等待人工决策
    assert a_state["status"] == WorkflowStatus.AWAITING_REVIEW
    assert a_state["revision_count"] == 1
    assert a_state["image_assets"] == []


# ---------------------------------------------------------------------------
# 检查点生命周期
# ---------------------------------------------------------------------------


def test_compiled_workflow_owns_its_checkpointer(workflow: CompiledWorkflow) -> None:
    """InMemorySaver 与编译后的图绑定在同一对象上，生命周期一致。"""
    assert isinstance(workflow.checkpointer, InMemorySaver)
    assert workflow.graph.checkpointer is workflow.checkpointer
