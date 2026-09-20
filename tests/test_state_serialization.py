"""验证 MediaWorkflowState 的字段完整性，以及「只能存 JSON 可序列化数据」这条约束。

验收标准 4：MediaWorkflowState 示例可完成 JSON 序列化往返。
"""

from __future__ import annotations

import json
from typing import Any, get_type_hints

from app.graph.state import MediaWorkflowState, WorkflowStatus

# 技术方案 v2 第 4 章约定的 11 个状态字段
EXPECTED_FIELDS = {
    "topic_direction",
    "generated_topics",
    "selected_topic",
    "article_content",
    "review_action",
    "review_feedback",
    "visual_points",
    "image_assets",
    "status",
    "error_message",
    "revision_count",
}


def _sample_state() -> MediaWorkflowState:
    """构造一份「审核驳回一次之后、等待再次审稿」的示例状态。

    注意：这里写入的全部是基础类型（str / int / list / dict / None），
    领域模型已用 model_dump(mode="json") 转成普通字典，而不是 Pydantic 实例。
    """
    return MediaWorkflowState(
        topic_direction="面向零基础学员讲清楚 LangGraph 的检查点机制",
        generated_topics=[
            {"id": "t1", "title": "检查点到底存了什么", "angle": "原理拆解", "reason": "新手最困惑的点"},
            {"id": "t2", "title": "一次断点续跑的复盘", "angle": "实战演练", "reason": "可复现"},
            {"id": "t3", "title": "为什么你的状态总是丢", "angle": "避坑指南", "reason": "痛点明确"},
        ],
        selected_topic={"id": "t1", "title": "检查点到底存了什么", "angle": "原理拆解", "reason": "新手最困惑的点"},
        article_content="# 检查点到底存了什么\n\n这里是文章正文……",
        review_action="revise",
        review_feedback="请补充一个最小可运行示例",
        visual_points=[
            {"id": "vp1", "order": 1, "title": "什么是检查点", "point": "保存每一步状态快照", "prompt": "知识卡片：检查点"},
        ],
        image_assets=[
            {
                "visual_point_id": "vp1",
                "status": "success",
                "url": "https://mock.local/images/vp1.png",
                "error": None,
            }
        ],
        status=WorkflowStatus.AWAITING_REVIEW,
        error_message=None,
        revision_count=1,
    )


def test_state_declares_all_expected_fields() -> None:
    """TypedDict 声明了全部 11 个字段，与设计文档一致。

    get_type_hints 会读取类上的类型注解，返回「字段名 -> 类型」的字典。
    TypedDict 在运行期其实就是一个普通 dict，注解只起文档和类型检查作用，
    所以我们需要用这种方式来断言「字段没有漏写」。
    """
    hints = get_type_hints(MediaWorkflowState)

    assert set(hints) == EXPECTED_FIELDS


def test_state_round_trips_through_json() -> None:
    """示例状态可以 json.dumps 后再 json.loads，内容完全一致（往返无损）。

    这正是 LangGraph 检查点持久化时要做的事：把状态序列化存盘，再用时反序列化回来。
    """
    state = _sample_state()

    raw = json.dumps(state, ensure_ascii=False)
    restored = json.loads(raw)

    assert restored == state
    assert restored["status"] == "awaiting_review"
    assert restored["revision_count"] == 1
    assert restored["review_action"] == "revise"
    # review_feedback 之类字段在真实运行中可能是 None，None 也必须能安全往返
    assert restored["error_message"] is None


def test_state_contains_only_json_serializable_values() -> None:
    """递归检查状态里的每个值都是 JSON 基础类型。

    这条测试是「状态里不能放 Pydantic 实例 / 客户端 / Logger / 数据库对象」
    这条约束的自动化守卫：一旦有人往状态里塞了不可序列化对象，测试立刻失败。
    """
    state = _sample_state()

    for field_name, value in state.items():
        _assert_json_only(value, path=field_name)


def test_default_skeleton_state_is_serializable() -> None:
    """工作流刚启动时的「初始骨架」也必须是可序列化的。

    初始状态只有内容方向和默认值，其余字段留空，方便后续节点逐步填充。
    """
    initial_state = MediaWorkflowState(
        topic_direction="讲讲 AI 训练师的就业方向",
        generated_topics=[],
        selected_topic=None,
        article_content=None,
        review_action=None,
        review_feedback=None,
        visual_points=[],
        image_assets=[],
        status=WorkflowStatus.PLANNING,
        error_message=None,
        revision_count=0,
    )

    assert json.loads(json.dumps(initial_state, ensure_ascii=False))["status"] == "planning"


def test_workflow_status_enum_covers_documented_lifecycle() -> None:
    """WorkflowStatus 覆盖技术方案 4.3 节列出的全部生命周期取值。"""
    assert {status.value for status in WorkflowStatus} == {
        "planning",
        "awaiting_topic_selection",
        "drafting",
        "awaiting_review",
        "revising",
        "extracting_visuals",
        "generating_images",
        "completed",
        "completed_with_warnings",
        "failed",
    }


def _assert_json_only(value: Any, path: str) -> None:
    """辅助函数：递归断言 value 只由 JSON 基础类型组成。

    参数说明：
        value : 待检查的值
        path  : 已经走过的字段路径，仅用于报错时指出问题位置
    """
    # bool 必须写在 int 前面判断吗？不需要，bool 是 int 的子类，
    # 但两者都属于合法 JSON 类型，放在同一个 isinstance 里即可。
    if isinstance(value, (str, int, float, bool)) or value is None:
        return

    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_only(item, path=f"{path}[{index}]")
        return

    if isinstance(value, dict):
        for key, item in value.items():
            # JSON 的键必须是字符串
            assert isinstance(key, str), f"{path} 的键必须是字符串，实际是 {type(key)}"
            _assert_json_only(item, path=f"{path}.{key}")
        return

    raise AssertionError(f"{path} 含有不可 JSON 序列化的类型：{type(value)}")
