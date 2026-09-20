"""验证三个领域模型的校验规则与 JSON 转换能力。

验收标准 3：三个领域模型可校验并转为 JSON。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.schemas.domain import (
    ImageAsset,
    ImageAssetStatus,
    TopicCandidate,
    VisualPoint,
)


def test_topic_candidate_validates_and_dumps_to_json() -> None:
    """TopicCandidate 可以通过校验，并用 model_dump(mode="json") 转成纯 JSON 字典。"""
    topic = TopicCandidate(
        id="t1",
        title="检查点到底存了什么",
        angle="原理拆解",
        reason="新手最容易困惑的点",
    )

    payload = topic.model_dump(mode="json")

    # mode="json" 的语义：把 Python 对象转换成「JSON 能表示的类型」。
    # 例如枚举会被转成字符串、日期会被转成 ISO 字符串。
    assert payload == {
        "id": "t1",
        "title": "检查点到底存了什么",
        "angle": "原理拆解",
        "reason": "新手最容易困惑的点",
    }
    # json.dumps 只接受基础类型；能成功 dump 说明结果确实是纯 JSON 数据。
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


def test_visual_point_validates_and_dumps_to_json() -> None:
    """VisualPoint 可以通过校验并转成 JSON，order 从 1 开始计数。"""
    point = VisualPoint(
        id="vp1",
        order=1,
        title="什么是检查点",
        point="检查点把每一步的状态快照保存下来，便于断点续跑",
        prompt="知识卡片：什么是检查点，扁平插画风格",
    )

    payload = point.model_dump(mode="json")

    assert payload["order"] == 1
    assert isinstance(payload["order"], int)
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


def test_image_asset_success_dumps_status_as_plain_string() -> None:
    """ImageAsset 成功态：status 是普通字符串 "success"，url 有值、error 为空。"""
    asset = ImageAsset(
        visual_point_id="vp1",
        status=ImageAssetStatus.SUCCESS,
        url="https://mock.local/images/vp1.png",
        error=None,
    )

    payload = asset.model_dump(mode="json")

    assert payload == {
        "visual_point_id": "vp1",
        "status": "success",
        "url": "https://mock.local/images/vp1.png",
        "error": None,
    }
    # 枚举成员是 str 的子类，但 dump 之后必须是纯字符串，不能是枚举对象
    assert type(payload["status"]) is str


def test_image_asset_failed_dumps_structured_error() -> None:
    """ImageAsset 失败态：url 为空、error 给出失败原因。"""
    asset = ImageAsset(
        visual_point_id="vp2",
        status="failed",
        url=None,
        error="图片服务超时",
    )

    payload = asset.model_dump(mode="json")

    assert payload["status"] == "failed"
    assert payload["url"] is None
    assert payload["error"] == "图片服务超时"


def test_image_asset_rejects_unknown_status() -> None:
    """status 只能是 success / failed，其他取值必须报校验错误。"""
    with pytest.raises(ValidationError):
        ImageAsset(visual_point_id="vp1", status="pending", url=None, error=None)


def test_visual_point_rejects_non_positive_order() -> None:
    """order 必须大于等于 1（第 0 张卡片没有业务含义）。"""
    with pytest.raises(ValidationError):
        VisualPoint(id="vp1", order=0, title="标题", point="要点", prompt="提示词")


def test_models_forbid_unknown_fields() -> None:
    """领域模型配置了 extra="forbid"：多传未声明字段会直接报错。

    这样做可以尽早发现「上游返回结构变了」这类问题，而不是悄悄丢字段。
    """
    with pytest.raises(ValidationError):
        TopicCandidate(id="t1", title="标题", angle="角度", reason="理由", unexpected="多余字段")


def test_models_reject_empty_required_string() -> None:
    """必填字符串不能为空。"""
    with pytest.raises(ValidationError):
        TopicCandidate(id="", title="标题", angle="角度", reason="理由")
