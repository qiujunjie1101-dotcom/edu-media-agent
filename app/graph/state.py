"""工作流全局状态定义。

============================================================================
这份状态是什么？
============================================================================
在 LangGraph 里，整条工作流共享一个「状态对象」（通常称为 State / 数据总线）：

    节点读状态  →  干活  →  返回「要更新的字段」  →  框架合并回状态  →  下一个节点

可以把它理解成一条流水线上的托盘：每个工位从托盘里取东西、放东西，
托盘本身由框架保管。框架会在每一步之后把托盘内容**序列化**写入检查点
（Checkpoint），从而支持「暂停 / 恢复 / 断点续跑」。

============================================================================
两条硬性约束
============================================================================
1. **只能放 JSON 可序列化的数据**：str / int / float / bool / None / list / dict。
   绝对不能放 Pydantic 实例、数据库 Session、HTTP 客户端、Logger、异常对象——
   这些东西无法（也不该）被序列化到检查点里。领域模型需要用
   ``model_dump(mode="json")`` 转成普通字典后再放进来。

2. **不放运行时依赖**：服务实例（LLM / 图片）通过「构图时闭包注入」传给节点函数，
   不作为状态字段传递。

============================================================================
关于 TypedDict
============================================================================
``TypedDict`` 是 Python 标准库 typing 提供的工具：它让一个普通 dict 拥有
「字段名 + 类型」的声明，从而获得 IDE 补全和静态类型检查（mypy / pyright）。

    class Foo(TypedDict):
        name: str

    foo: Foo = {"name": "张三"}   # 运行期就是普通 dict，注解只用于类型检查

注意：TypedDict **不做运行期校验**。要保证状态合法，靠的是测试
（见 tests/test_state_serialization.py 里的递归 JSON 检查）。
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, TypedDict


class WorkflowStatus(str, Enum):
    """工作流所处的阶段。

    取值与技术方案 v2 第 4.3 节一致。前端会根据这个字段决定展示哪种界面
    （例如 ``awaiting_review`` 时展示审稿页）。
    """

    PLANNING = "planning"  # 正在生成候选选题
    AWAITING_TOPIC_SELECTION = "awaiting_topic_selection"  # 人工中断点 1：等待选题
    DRAFTING = "drafting"  # 正在写作
    AWAITING_REVIEW = "awaiting_review"  # 人工中断点 2：等待审稿
    REVISING = "revising"  # 人工驳回后正在重写
    EXTRACTING_VISUALS = "extracting_visuals"  # 正在提炼视觉要点
    GENERATING_IMAGES = "generating_images"  # 正在生成图片
    COMPLETED = "completed"  # 全部成功
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"  # 完成但有图片生成失败
    FAILED = "failed"  # 出现不可恢复错误


class MediaWorkflowState(TypedDict):
    """一次内容生产会话的完整状态。

    一次会话由 ``thread_id`` 唯一标识（``thread_id`` 属于运行时配置而不是状态字段，
    因此不在这里声明）。
    """

    # ---------------- 输入与选题 ----------------
    topic_direction: str
    """运营人员输入的内容方向，例如「面向零基础学员讲清楚 LangGraph 的检查点机制」。"""

    generated_topics: list[dict]
    """AI 生成的候选选题列表，元素是 TopicCandidate 的 JSON 字典：
    ``{"id": ..., "title": ..., "angle": ..., "reason": ...}``。"""

    selected_topic: dict | None
    """人工选中的题目（同样是 TopicCandidate 的 JSON 字典）；选题之前为 None。"""

    # ---------------- 文章与人工审核 ----------------
    article_content: str | None
    """当前版本的文章正文；写第一稿之前为 None。每次重写都会**整体覆盖**旧值。"""

    review_action: Literal["approve", "revise"] | None
    """人工审核结论：approve（通过）/ revise（驳回重写）；尚未审核时为 None。"""

    review_feedback: str | None
    """驳回时人工填写的修改意见，是重写的输入；通过时为 None。"""

    # ---------------- 视觉要点与图片 ----------------
    visual_points: list[dict]
    """按人工通过的文章提炼出的 3–5 个视觉要点，元素是 VisualPoint 的 JSON 字典。"""

    image_assets: list[dict]
    """图片生成结果，元素是 ImageAsset 的 JSON 字典（含 visual_point_id / status / url / error）。"""

    # ---------------- 运行控制 ----------------
    status: str
    """当前所处阶段，取值来自 WorkflowStatus。

    注意写入的是 ``WorkflowStatus.X.value``（纯字符串），而不是枚举对象本身：
    LangGraph 的检查点序列化器遇到自定义类型会给出告警
    （"Deserializing unregistered type ... will be blocked in a future version"），
    纯字符串则永远安全，也符合「状态里只放 JSON 数据」的约束。
    """

    error_message: str | None
    """错误或警告信息；正常情况下为 None。"""

    revision_count: int
    """已按人工意见重写的次数：初稿为 0，每次重写加 1（连续驳回两次再通过时最终为 2）。"""
