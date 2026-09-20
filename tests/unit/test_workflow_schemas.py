"""S3 接口层 Pydantic 模型的单元测试。

============================================================================
这些模型是「HTTP 世界」与「工作流世界」之间的闸门
============================================================================
它们的职责只有两件：

1. **把非法请求挡在门外**（长度、必填、动作取值），并且失败时给出 422；
2. **把内部状态塑形成对外契约**（响应字段固定、不泄露内部对象）。

本文件只测模型本身（纯函数、无需启动 FastAPI），属于最快的反馈层。
接口层的端到端行为在 tests/api/test_workflows.py。
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from app.graph.routing import APPROVE_ACTION, REVISE_ACTION, SELECT_TOPIC_ACTION
from app.schemas.workflow import (
    ArticleReviewPending,
    PendingAction,
    ResumeRequest,
    TopicSelectionPending,
    WorkflowResponse,
    WorkflowStartRequest,
)

# 判别联合类型本身不是模型类，需要用 TypeAdapter 才能校验。
# TypeAdapter 是 Pydantic v2 提供的「给任意类型套一层校验器」的工具。
_resume_adapter: TypeAdapter[ResumeRequest] = TypeAdapter(ResumeRequest)
_pending_adapter: TypeAdapter[PendingAction] = TypeAdapter(PendingAction)


# ---------------------------------------------------------------------------
# 启动请求：topic_direction 长度 2–200
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("direction", ["ab", "x" * 200, "LangGraph 人工审核教程"])
def test_start_request_accepts_valid_direction(direction: str) -> None:
    """边界值通过：恰好 2 个字符、恰好 200 个字符都合法。"""
    model = WorkflowStartRequest(topic_direction=direction)
    assert model.topic_direction == direction


@pytest.mark.parametrize("direction", ["", "a", "x" * 201])
def test_start_request_rejects_invalid_direction(direction: str) -> None:
    """边界值拒绝：过短（含空串）与过长都必须报错。"""
    with pytest.raises(ValidationError):
        WorkflowStartRequest(topic_direction=direction)


def test_start_request_rejects_missing_field() -> None:
    """缺少 topic_direction 直接报错，不会静默用默认值。"""
    with pytest.raises(ValidationError):
        WorkflowStartRequest.model_validate({})


def test_start_request_rejects_extra_field() -> None:
    """多余字段直接报错：S1–S3 明确不引入 idempotency_key 等字段。"""
    with pytest.raises(ValidationError):
        WorkflowStartRequest.model_validate(
            {"topic_direction": "合法方向", "idempotency_key": "abc"}
        )


# ---------------------------------------------------------------------------
# 恢复请求：Pydantic v2 判别联合
# ---------------------------------------------------------------------------


def test_resume_select_topic_variant() -> None:
    """select_topic 分支解析出 topic_id。"""
    parsed = _resume_adapter.validate_python({"action": SELECT_TOPIC_ACTION, "topic_id": "t1"})
    assert parsed.action == SELECT_TOPIC_ACTION
    assert parsed.topic_id == "t1"


def test_resume_select_topic_requires_topic_id() -> None:
    """select_topic 缺少 topic_id 必须报错。"""
    with pytest.raises(ValidationError):
        _resume_adapter.validate_python({"action": SELECT_TOPIC_ACTION})


def test_resume_approve_comment_is_optional() -> None:
    """approve 的 comment 是可选的：不传也能通过。"""
    parsed = _resume_adapter.validate_python({"action": APPROVE_ACTION})
    assert parsed.action == APPROVE_ACTION
    assert parsed.comment is None

    with_comment = _resume_adapter.validate_python({"action": APPROVE_ACTION, "comment": "可以发布"})
    assert with_comment.comment == "可以发布"


def test_resume_approve_does_not_accept_topic_id() -> None:
    """判别联合分支之间字段不串味：approve 分支没有 topic_id 字段。"""
    with pytest.raises(ValidationError):
        _resume_adapter.validate_python({"action": APPROVE_ACTION, "topic_id": "t1"})


@pytest.mark.parametrize("feedback", ["", "不行", "1234"])
def test_resume_revise_requires_feedback_at_least_5_chars(feedback: str) -> None:
    """revision 的 feedback 最少 5 个字符（少于 5 个拒绝）。"""
    with pytest.raises(ValidationError):
        _resume_adapter.validate_python({"action": REVISE_ACTION, "feedback": feedback})


def test_resume_revise_accepts_5_char_feedback() -> None:
    """恰好 5 个字符是合法下界。"""
    parsed = _resume_adapter.validate_python({"action": REVISE_ACTION, "feedback": "请补充示例"})
    assert parsed.feedback == "请补充示例"


def test_resume_rejects_unknown_action() -> None:
    """未知 action 无法匹配任何分支，直接 422。"""
    with pytest.raises(ValidationError):
        _resume_adapter.validate_python({"action": "delete_everything"})


def test_resume_rejects_missing_action() -> None:
    """缺少判别字段 action 时报错。"""
    with pytest.raises(ValidationError):
        _resume_adapter.validate_python({"topic_id": "t1"})


# ---------------------------------------------------------------------------
# pending_action：两种中断的对外形状必须精确
# ---------------------------------------------------------------------------


def test_topic_selection_pending_shape_is_exact() -> None:
    """选题中断的 pending_action 只有 type 与 allowed_actions 两个字段。"""
    pending = TopicSelectionPending()
    assert pending.model_dump() == {
        "type": "topic_selection",
        "allowed_actions": [SELECT_TOPIC_ACTION],
    }


def test_article_review_pending_shape_is_exact() -> None:
    """审稿中断的 pending_action 额外带上重写次数与是否达上限。"""
    pending = ArticleReviewPending(
        allowed_actions=[APPROVE_ACTION, REVISE_ACTION],
        revision_count=1,
        revision_limit_reached=False,
    )
    assert pending.model_dump() == {
        "type": "article_review",
        "allowed_actions": [APPROVE_ACTION, REVISE_ACTION],
        "revision_count": 1,
        "revision_limit_reached": False,
    }


def test_pending_action_discriminates_by_type() -> None:
    """pending_action 也按 type 判别：两种形状不会互相污染。"""
    pending = _pending_adapter.validate_python(
        {
            "type": "article_review",
            "allowed_actions": [APPROVE_ACTION],
            "revision_count": 3,
            "revision_limit_reached": True,
        }
    )
    assert isinstance(pending, ArticleReviewPending)
    assert pending.revision_limit_reached is True


# ---------------------------------------------------------------------------
# 响应模型：字段固定，且不包含任何 LangGraph 内部对象
# ---------------------------------------------------------------------------


def test_response_model_has_no_internal_langgraph_fields() -> None:
    """响应字段是白名单：不允许出现 __interrupt__ / tasks / next / snapshot。"""
    fields = set(WorkflowResponse.model_fields)

    assert fields == {
        "thread_id",
        "status",
        "topic_direction",
        "generated_topics",
        "selected_topic",
        "article_content",
        "review_action",
        "review_feedback",
        "visual_points",
        "image_assets",
        "revision_count",
        "error_message",
        "pending_action",
    }
    for forbidden in ("__interrupt__", "tasks", "next", "snapshot", "values", "config"):
        assert forbidden not in fields


def test_response_model_accepts_completed_payload_with_null_pending() -> None:
    """已完成的会话可以用 pending_action=None 构造出合法响应。"""
    response = WorkflowResponse(
        thread_id="thread-1",
        status="completed",
        topic_direction="方向",
        generated_topics=[],
        selected_topic=None,
        article_content="# 文章",
        review_action=APPROVE_ACTION,
        review_feedback=None,
        visual_points=[],
        image_assets=[
            {"visual_point_id": "vp1", "status": "success", "url": "https://x/vp1.png", "error": None}
        ],
        revision_count=0,
        error_message=None,
        pending_action=None,
    )

    dumped = response.model_dump()
    assert dumped["pending_action"] is None
    assert set(dumped) == set(WorkflowResponse.model_fields)
