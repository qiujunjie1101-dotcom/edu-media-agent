"""领域模型：流程各环节之间传递的数据契约。

============================================================================
什么是「领域模型」？
============================================================================
领域模型描述的是**业务概念**，而不是某个第三方接口的原始返回结构。
本文件里的三个模型构成了「AI 适配层」与「工作流节点」之间的唯一契约：

    MockLLMService / 真实 LLM 实现  ──产出──▶  TopicCandidate / VisualPoint
    MockImageService / 真实图床    ──产出──▶  ImageAsset

好处：将来把 Mock 换成真实模型时，只要适配器负责把外部数据「翻译」成这些模型，
工作流节点一行都不用改。

============================================================================
为什么都用 Pydantic 模型而不是普通 dict？
============================================================================
1. 自动校验：字段缺失、类型写错、多余字段都会立刻报错，而不是运行到一半才炸。
2. 自动补全：IDE 能提示字段名，避免拼写错误。
3. 一键转换：``model_dump(mode="json")`` 可以直接得到可 JSON 序列化的普通字典，
   这正是写入 LangGraph 状态所需要的形式。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ImageAssetStatus(str, Enum):
    """图片资产的状态。

    为什么写成 ``str, Enum``？

    - 继承 ``str``：枚举成员本身就是字符串，可以直接参与字符串比较；
      序列化成 JSON 时天然就是 ``"success"`` / ``"failed"``，无需额外转换。
    - 继承 ``Enum``：取值被限定在下面两个之内，写错会在校验阶段就报错。
    """

    SUCCESS = "success"  # 生成成功
    FAILED = "failed"  # 生成失败，此时 error 字段给出原因


class DomainModel(BaseModel):
    """所有领域模型的公共基类，用来集中声明校验行为。

    这样每个子类都不用重复写 model_config，风格保持一致。
    """

    model_config = ConfigDict(
        # extra="forbid"：出现未声明的字段时直接报错。
        # 好处是上游结构发生变化（比如多返回了一个字段）能立刻暴露，而不是被悄悄忽略。
        extra="forbid",
        # 自动去掉字符串首尾空白，避免 "标题 " 与 "标题" 被视为不同内容。
        str_strip_whitespace=True,
        # 允许用「字段名」或「字段别名」来构造对象，后续加别名时更平滑。
        populate_by_name=True,
    )


class TopicCandidate(DomainModel):
    """一个候选选题。

    运营人员看到的就是这个模型渲染出来的内容，所以要同时给出「标题」与
    「为什么值得写」，方便人工快速判断。
    """

    id: str = Field(
        min_length=1,
        description="选题唯一标识，例如 t1 / t2；人工选题时用它回传选择结果",
    )
    title: str = Field(
        min_length=1,
        description="选题标题，会作为公众号文章的大标题",
    )
    angle: str = Field(
        min_length=1,
        description="写作角度，例如「原理拆解」「实战演练」「避坑指南」",
    )
    reason: str = Field(
        min_length=1,
        description="推荐理由，说明这个角度为什么适合目标读者",
    )


class VisualPoint(DomainModel):
    """一个适合做成小红书知识卡片的视觉要点。

    一条记录同时承担两件事：给人工看的「要点内容」，以及给图片模型用的「提示词」。
    """

    id: str = Field(
        min_length=1,
        description="要点唯一标识，例如 vp1；用于与图片资产 image_assets 精确对齐",
    )
    order: int = Field(
        ge=1,
        description="展示顺序，从 1 开始连续递增，对应小红书图文的第几张卡片",
    )
    title: str = Field(
        min_length=1,
        description="卡片标题",
    )
    point: str = Field(
        min_length=1,
        description="要点正文，直接展示在卡片上的文字",
    )
    prompt: str = Field(
        min_length=1,
        description="生图提示词，由图片服务使用",
    )


class ImageAsset(DomainModel):
    """一张图片的生成结果。

    为什么不用简单的字符串列表？
        因为图片是**并发**生成的，完成顺序不确定；而且部分失败是允许的（降级场景）。
        用「结构化结果 + visual_point_id」才能准确回答：
        「第 3 张卡片到底有没有出图？失败原因是什么？」
    """

    visual_point_id: str = Field(
        min_length=1,
        description="对应的视觉要点 id，用于与 VisualPoint.id 一一对应",
    )
    status: ImageAssetStatus = Field(
        description="生成状态：success 或 failed",
    )
    url: str | None = Field(
        default=None,
        description="图片访问地址；成功时应有值",
    )
    error: str | None = Field(
        default=None,
        description="失败原因；成功时为 None",
    )
