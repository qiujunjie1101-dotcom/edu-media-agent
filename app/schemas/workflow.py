"""S3 接口层的数据结构：请求体、响应体与 pending_action。

============================================================================
这个模块在架构中的位置
============================================================================
    HTTP 世界  ──请求模型──▶  API 层  ──▶  WorkflowService  ──▶  LangGraph
    HTTP 世界  ◀──响应模型──  API 层  ◀──  WorkflowService  ◀──  LangGraph

它承担两件互不重叠的事：

1. **入参把关**：长度、必填、动作取值。任何不合法都在这里变成 422，
   请求根本不会走到 Graph（这正是「非法请求不损坏 thread」的第一道防线）。
2. **出参塑形**：把内部状态裁剪成固定的对外字段集合，
   LangGraph 的 ``StateSnapshot`` / ``Task`` / ``Interrupt`` 一律不出现在响应里。

============================================================================
为什么用「判别联合（discriminated union）」？
============================================================================
三种人工动作的字段形状并不一样：select_topic 要 topic_id，revise 要 feedback，
approve 只有一个可选 comment。用联合类型表达后：

- ``action`` 字段充当**判别器（discriminator）**，Pydantic 先读它再决定用哪个分支校验；
- 合法组合之外的一切（缺字段、字段串味、未知动作）都会在入口处变成 422；
- 相比「一个大模型 + 一堆可选字段 + 手写 if 校验」，它把非法状态在类型层面就排除掉了。

注意：响应里的 ``pending_action`` 也用同一套判别联合，但判别字段换成 ``type``。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.graph.routing import APPROVE_ACTION, REVISE_ACTION, SELECT_TOPIC_ACTION
from app.schemas.domain import ImageAsset, TopicCandidate, VisualPoint

# ---------------------------------------------------------------------------
# 请求模型公共基类
# ---------------------------------------------------------------------------


class RequestModel(BaseModel):
    """所有请求体的公共基类。

    ``extra="forbid"``：多传字段直接报错，而不是被静默忽略。
    这条约束在 S1–S3 阶段尤其重要——它保证 ``idempotency_key`` 这类
    「本阶段明确不引入」的字段一旦被误传，会立刻暴露而不是悄悄生效。

    ``str_strip_whitespace=True``：自动去掉首尾空白，避免
    ``"  "``（全是空格）被当成合法输入，也避免 ``" t1"`` 与 ``"t1"`` 被当成两个 id。
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# 启动请求
# ---------------------------------------------------------------------------


class WorkflowStartRequest(RequestModel):
    """``POST /api/v1/workflows/start`` 的请求体。

    ``thread_id`` 不在这里：它由**服务端**生成，客户端无权指定
    （否则不同客户端可以互相覆盖会话）。
    """

    topic_direction: str = Field(
        min_length=2,
        max_length=200,
        description="内容方向，2–200 个字符",
        examples=["LangGraph 人工审核教程"],
    )


# ---------------------------------------------------------------------------
# 恢复请求：三种人工动作（判别字段 action）
# ---------------------------------------------------------------------------


class SelectTopicAction(RequestModel):
    """人工选题。只在「等待选题」中断点合法。"""

    action: Literal["select_topic"]
    topic_id: str = Field(
        min_length=1,
        description="候选选题的 id，必须存在于本次会话的 generated_topics 中",
    )


class ApproveAction(RequestModel):
    """人工通过。只在「等待审稿」中断点合法，通过后进入视觉要点与生图链路。"""

    action: Literal["approve"]
    comment: str | None = Field(
        default=None,
        description="可选备注，仅供人工留痕，不参与内容生成",
    )


class ReviseAction(RequestModel):
    """人工驳回并要求重写。``feedback`` 至少 5 个字符。"""

    action: Literal["revise"]
    feedback: str = Field(
        min_length=5,
        description="修改意见，至少 5 个字符；会作为重写输入传给文本模型",
    )


ResumeRequest = Annotated[
    SelectTopicAction | ApproveAction | ReviseAction,
    Field(discriminator="action"),
]
"""``POST /.../resume`` 的请求体类型。

用 ``Annotated[..., Field(discriminator="action")]`` 而不是普通 ``Union``：
后者会让 Pydantic 逐个分支尝试（容易产生「字段碰巧对上了」的误判），
前者则是先看 ``action`` 再精确匹配唯一分支，语义无歧义。
"""


# ---------------------------------------------------------------------------
# pending_action：中断的对外表达
# ---------------------------------------------------------------------------


class TopicSelectionPending(BaseModel):
    """等待人工选题时的待办动作。

    刻意**只暴露 type 与 allowed_actions**：候选选题列表已经在响应的
    ``generated_topics`` 顶层字段里，重复放一遍只会让契约有两份真相。
    """

    type: Literal["topic_selection"] = "topic_selection"
    allowed_actions: list[Literal["select_topic"]] = Field(
        default_factory=lambda: [SELECT_TOPIC_ACTION]
    )


class ArticleReviewPending(BaseModel):
    """等待人工审稿时的待办动作。

    带上 ``revision_count`` 与 ``revision_limit_reached``，前端据此决定
    是否禁用「驳回」入口——服务端仍然会独立校验一遍，不依赖前端自觉。
    """

    type: Literal["article_review"] = "article_review"
    allowed_actions: list[Literal["approve", "revise"]]
    revision_count: int
    revision_limit_reached: bool


PendingAction = Annotated[
    TopicSelectionPending | ArticleReviewPending,
    Field(discriminator="type"),
]
"""``pending_action`` 的类型：两种中断形状二选一。

响应里 ``pending_action is None`` 表示「当前没有人工中断」——
流程正在自动运行，或已经跑到 END（此时 ``status`` 为 completed 等终态）。
"""


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------


class WorkflowResponse(BaseModel):
    """三个接口共用的成功响应结构。

    设计要点：

    1. **字段白名单**：这里是接口契约的全部内容。LangGraph 的
       ``StateSnapshot``、``PregelTask``、``Interrupt`` 等内部对象
       只存在于服务层，绝不能出现在响应字段里。
    2. **字段名与状态字段一一对应**：``thread_id`` 是运行时标识（不进状态），
       其余字段与 ``MediaWorkflowState`` 同名，前端不需要记两套名字。
    3. **可空字段显式声明为 None**：``selected_topic`` / ``article_content`` /
       ``review_action`` / ``review_feedback`` / ``error_message`` / ``pending_action``
       在流程早期或终态时为 ``None``，前端据此判断渲染哪种界面。
    """

    thread_id: str
    """本次会话的标识；后续 GET / resume 都用它。"""

    status: str
    """流程阶段，取值见 ``app/graph/state.py`` 的 WorkflowStatus。"""

    topic_direction: str
    """运营人员输入的内容方向。"""

    generated_topics: list[TopicCandidate]
    """AI 生成的候选选题；选题之前为空列表。"""

    selected_topic: TopicCandidate | None
    """人工选中的题目；尚未选题时为 None。"""

    article_content: str | None
    """当前版本的文章正文；写初稿之前为 None。"""

    review_action: Literal["approve", "revise"] | None
    """最近一次人工审核结论；尚未审核或新一轮尚未提交时为 None。"""

    review_feedback: str | None
    """审核意见原文（驳回时有值）。"""

    visual_points: list[VisualPoint]
    """提炼出的视觉要点；未通过审核前为空列表。"""

    image_assets: list[ImageAsset]
    """图片生成结果；未通过审核前为空列表。"""

    revision_count: int
    """已按人工意见重写的次数。"""

    error_message: str | None
    """警告或错误说明；正常情况下为 None（例如部分图片失败时会写在这里）。"""

    pending_action: PendingAction | None
    """当前等待人工完成的动作；None 表示没有中断。"""


class ErrorDetail(BaseModel):
    """统一错误响应体里的 ``detail`` 部分。

    它与技术方案第 7 章的约定一致：``{"detail": {"code", "message", "thread_id"}}``。
    ``message`` 是面向人的中文描述，**不得包含堆栈、密钥或内部对象**。
    """

    code: str
    message: str
    thread_id: str | None = None


class ErrorResponse(BaseModel):
    """统一错误响应体。

    只用于 OpenAPI 文档展示（FastAPI 的 ``responses=`` 参数），
    实际错误响应由 ``app/main.py`` 里的异常处理器构造，走的是同一份结构。
    """

    detail: ErrorDetail


def dump_for_graph(payload: ResumeRequest) -> dict[str, Any]:
    """把恢复请求转成「交给被中断节点」的纯字典。

    为什么必须转：

    1. 工作流状态与中断载荷只允许是 JSON 可序列化的普通数据，
       Pydantic 实例进不去（见 ``app/graph/state.py`` 的说明）；
    2. ``exclude_none=True`` 让未填写的可选字段（如 approve 的 comment）
       不出现在字典里，被中断节点读到的就是「用户真正提交了什么」。
    """
    return payload.model_dump(exclude_none=True)
