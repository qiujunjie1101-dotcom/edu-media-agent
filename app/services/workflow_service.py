"""WorkflowService：工作流的唯一业务入口（S3 的「大脑」）。

============================================================================
为什么必须有这一层？
============================================================================
如果让路由函数直接 ``graph.ainvoke(...)``，会出现四个问题：

1. **版本细节外泄**：中断载荷在 ``result["__interrupt__"][0].value``，
   而查询状态时在 ``snapshot.tasks[*].interrupts[*].value``——
   这类结构一旦写进路由，LangGraph 一升级就要改一圈接口代码；
2. **安全栅栏缺失**：非法 ``Command(resume=...)`` 会让该 thread 的任务进入
   error 状态并**卡死**（S2 已实测），因此「调用前的校验」必须是强制的、
   集中的，而不是每个端点各写一遍；
3. **异常映射散落**：领域异常 → HTTP 错误码的转换只应发生在一个地方；
4. **无法独立测试**：业务规则与 HTTP 细节缠在一起，只能靠端到端测试覆盖。

于是本模块承担四件事，且**只有本模块**做这四件事：

    ┌──────────────────────────────────────────────────────────┐
    │ 1. 调用 Graph（start / 查询 / resume），持有唯一实例        │
    │ 2. 把版本相关的内部结构归一化为 pending_action             │
    │ 3. 恢复前的强制前置校验（不通过就绝不碰 Graph）             │
    │ 4. 把内部状态塑形成对外的 WorkflowResponse                 │
    └──────────────────────────────────────────────────────────┘

============================================================================
关于实例生命周期（S3 硬性要求）
============================================================================
``WorkflowService`` 持有一个 ``CompiledWorkflow``（编译后的图 + InMemorySaver）。
两者在应用启动（lifespan）时各创建一次，之后所有请求共享同一份：

- 每次请求重新构图 → InMemorySaver 被换掉 → 历史检查点全丢，中断无法恢复；
- 每次请求新建 Checkpointer → 同上。

因此本类**只接受**外部注入的 ``CompiledWorkflow``，自己绝不 ``build_workflow``。
"""

from __future__ import annotations

import logging
from typing import Any, Final
from uuid import uuid4

from langgraph.types import Command

from app.core.exceptions import (
    ActionNotAllowedError,
    ContentValidationError,
    InternalError,
    RevisionLimitReachedError,
    ThreadNotFoundError,
    TopicNotFoundError,
    WorkflowError,
    WorkflowNotInterruptedError,
)
from app.graph.builder import CompiledWorkflow
from app.graph.routing import APPROVE_ACTION, REVISE_ACTION, SELECT_TOPIC_ACTION
from app.graph.state import MediaWorkflowState, WorkflowStatus
from app.schemas.workflow import (
    ApproveAction,
    ArticleReviewPending,
    PendingAction,
    ResumeRequest,
    ReviseAction,
    SelectTopicAction,
    TopicSelectionPending,
    WorkflowResponse,
    dump_for_graph,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 与节点对齐的常量
# ---------------------------------------------------------------------------
# 这两个字符串必须与 app/graph/nodes/human_select_topic.py 与 human_review.py
# 里 interrupt(payload) 的 "type" 字段严格一致——它们是节点与接口层之间的口头契约。
# 之所以不写死在多个地方，是因为一旦哪边改了名字，pending_action 会静默变成 null，
# 这种「不报错的错」最难排查。
TOPIC_SELECTION_INTERRUPT: Final = "topic_selection"
ARTICLE_REVIEW_INTERRUPT: Final = "article_review"

# 修改意见的最小长度。数值与 human_review 节点保持一致：
# 接口层先拦一道（变成 422），节点里再拦一道（防御绕过接口层的调用方）。
MIN_FEEDBACK_LENGTH: Final = 5


# ===========================================================================
# 版本适配区：LangGraph 1.2.11 的中断读取
# ===========================================================================
# 下面两个私有函数是本模块中**唯一**接触 LangGraph 内部结构的地方。
# 路由层与其它服务方法一律通过它们拿数据，因此升级 LangGraph 时只需要改这里。
# 以下行为均由探针脚本在 langgraph==1.2.11 上实测确认（见交付说明）。
# ---------------------------------------------------------------------------


def _snapshot_exists(snapshot: Any) -> bool:
    """判断 ``aget_state`` 的结果是否代表「一个真实存在过的会话」。

    实测行为（langgraph 1.2.11）:

    - **不存在的 thread_id**：``values == {}``、``next == ()``、``tasks == ()``、
      ``created_at is None``。注意它**不会报错**，只是返回一个空快照——
      如果直接拿它构造响应，就会把「不存在」伪装成「流程还没开始」。
    - **存在过的 thread_id**：``created_at`` 一定有时间戳，``values`` 至少含
      ``topic_direction``。

    因此用「有创建时间 **或** 有状态值」作为存在判据：两者都为空才算不存在。
    """
    return getattr(snapshot, "created_at", None) is not None or bool(
        getattr(snapshot, "values", None)
    )


def _read_interrupt(source: Any) -> dict[str, Any] | None:
    """从「图调用结果」或「状态快照」中统一取出中断载荷。

    参数:
        source: 二选一
            - ``graph.ainvoke(...)`` 的返回值（dict）：
              中断载荷位于 ``result["__interrupt__"][0].value``；
            - ``graph.aget_state(...)`` 的返回值（StateSnapshot）：
              中断载荷位于 ``snapshot.tasks[*].interrupts[*].value``。

    返回:
        dict | None: 中断载荷（节点调用 ``interrupt(payload)`` 时传入的字典）；
        没有中断（流程运行中 / 已到 END / 任务出错）时返回 None。

    说明:
        - 这是**唯一**的版本适配点：路由与其它服务方法都不再解析这些结构；
        - 「任务出错」会被显式跳过：一次失败的运行会在检查点里留下
          ``task.error``，而它的 ``interrupts`` 是**上一次中断的旧值**。
          若把它当成「当前中断」，就会对着一个已经卡死的会话继续发恢复指令。
    """
    if isinstance(source, dict):
        # 分支一：ainvoke 的返回值
        interrupts: list[Any] = list(source.get("__interrupt__") or ())
    else:
        # 分支二：StateSnapshot。tasks 是「下一步要执行的任务」，
        # 正常中断时恰好有一个任务在等待人工输入。
        interrupts = []
        for task in getattr(source, "tasks", None) or ():
            if getattr(task, "error", None):
                continue  # 出错的任务跳过，见上面说明
            interrupts.extend(getattr(task, "interrupts", None) or ())

    if not interrupts:
        return None

    # Interrupt 对象的 .value 才是节点传入的载荷；
    # 兼容「已经是普通字典」的情况，便于单元测试直接喂字典。
    payload = getattr(interrupts[0], "value", interrupts[0])
    return payload if isinstance(payload, dict) else None


def _to_pending_action(payload: dict[str, Any] | None) -> PendingAction | None:
    """把中断载荷归一化成对外的 ``pending_action``。

    归一化做三件事：

    1. **只保留契约字段**：节点给的中断载荷里有 ``article`` / ``topics`` 等大字段，
       它们不适合塞进 ``pending_action``（文章正文在响应顶层已有）；
    2. **收窄允许的动作**：过滤掉未知动作，避免把节点里的笔误透给前端；
    3. **不认识的 type 一律返回 None**：宁可让调用方看到「没有待办动作」，
       也不要编造一个语义不明的 pending_action。
    """
    if not isinstance(payload, dict):
        return None

    raw_actions = [action for action in payload.get("allowed_actions") or [] if isinstance(action, str)]
    interrupt_type = payload.get("type")

    if interrupt_type == TOPIC_SELECTION_INTERRUPT:
        allowed = [action for action in raw_actions if action == SELECT_TOPIC_ACTION]
        return TopicSelectionPending(allowed_actions=allowed or [SELECT_TOPIC_ACTION])

    if interrupt_type == ARTICLE_REVIEW_INTERRUPT:
        allowed = [action for action in raw_actions if action in (APPROVE_ACTION, REVISE_ACTION)]
        return ArticleReviewPending(
            allowed_actions=allowed or [APPROVE_ACTION],
            revision_count=int(payload.get("revision_count") or 0),
            revision_limit_reached=bool(payload.get("revision_limit_reached")),
        )

    return None


def _initial_state(topic_direction: str) -> MediaWorkflowState:
    """构造一次会话的完整初始状态。

    为什么要在服务层显式给出**全部**字段？

    - 工作流第一个节点就可能读取多个字段，缺字段会直接抛 ``KeyError``；
    - 显式列出全部字段，等于给「状态结构」留了一份可执行的文档：
      将来 ``MediaWorkflowState`` 增删字段时，这里会第一时间被注意到。

    注意 ``status`` 写的是 ``WorkflowStatus.X.value``（纯字符串），
    而不是枚举对象本身——检查点里只允许放 JSON 数据。
    """
    return {
        "topic_direction": topic_direction,
        "generated_topics": [],
        "selected_topic": None,
        "article_content": None,
        "review_action": None,
        "review_feedback": None,
        "visual_points": [],
        "image_assets": [],
        "status": WorkflowStatus.PLANNING.value,
        "error_message": None,
        "revision_count": 0,
    }


# ===========================================================================
# 服务本体
# ===========================================================================


class WorkflowService:
    """工作流的启动、状态查询与人工恢复。

    参数:
        workflow: 应用启动时构建好的 ``CompiledWorkflow``（图 + 检查点）。
                  本类不负责创建它，只负责使用它——这样实例在生命周期内唯一。

    """

    def __init__(self, workflow: CompiledWorkflow) -> None:
        self._workflow = workflow

    # ------------------------------------------------------------------
    # 只读属性：供依赖注入与测试断言「拿到的确实是同一个实例」
    # ------------------------------------------------------------------

    @property
    def workflow(self) -> CompiledWorkflow:
        """本服务使用的编译后工作流。"""
        return self._workflow

    @property
    def graph(self) -> Any:
        """编译后的图（与 ``workflow.graph`` 是同一个对象）。"""
        return self._workflow.graph

    @property
    def checkpointer(self) -> Any:
        """检查点存储（与 ``workflow.checkpointer`` 是同一个对象）。"""
        return self._workflow.checkpointer

    @property
    def max_revisions(self) -> int:
        """本工作流允许的最大重写次数，来自配置。

        从图本身读取而不是重新读一次配置：单一真相，避免「图用 3、
        接口层以为还是 5」这种漂移。
        """
        return self._workflow.max_revisions

    # ------------------------------------------------------------------
    # 对外能力 1：启动
    # ------------------------------------------------------------------

    async def start(self, topic_direction: str) -> WorkflowResponse:
        """启动一次新会话，并一直运行到第一个人工中断点。

        参数:
            topic_direction: 内容方向（接口层已校验长度 2–200）

        返回:
            WorkflowResponse: 停在中选题中断时的完整状态

        异常:
            WorkflowError: 节点抛出的领域异常（如 LLM_UNAVAILABLE）
            InternalError: 未预期异常

        说明:
            ``thread_id`` 由服务端生成（UUID4），客户端无权指定：
            否则不同客户端可能用同一个 id 互相覆盖会话。
            这与 S6 的幂等键无关，纯粹是会话标识。
        """
        thread_id = str(uuid4())
        result = await self._invoke(_initial_state(topic_direction), thread_id)
        return self._build_response(thread_id, result, _read_interrupt(result))

    # ------------------------------------------------------------------
    # 对外能力 2：查询状态
    # ------------------------------------------------------------------

    async def get_state(self, thread_id: str) -> WorkflowResponse:
        """查询会话的最新状态。

        参数:
            thread_id: 会话标识

        返回:
            WorkflowResponse: 最新状态与归一化后的 pending_action

        异常:
            ThreadNotFoundError: 该会话不存在（含进程重启后内存检查点丢失）

        说明:
            这里**只读**：不调用任何会推进流程的方法，因此查询接口
            永远不可能改变会话状态。已完成的会话 ``pending_action`` 为 None。
        """
        snapshot = await self._require_snapshot(thread_id)
        values = dict(getattr(snapshot, "values", None) or {})
        return self._build_response(thread_id, values, _read_interrupt(snapshot))

    # ------------------------------------------------------------------
    # 对外能力 3：人工恢复
    # ------------------------------------------------------------------

    async def resume(self, thread_id: str, payload: ResumeRequest) -> WorkflowResponse:
        """提交人工动作，把流程推进到下一个中断点或 END。

        参数:
            thread_id: 会话标识
            payload: 已通过 Pydantic 校验的人工动作（选题 / 通过 / 驳回）

        返回:
            WorkflowResponse: 推进后的最新状态

        异常:
            ThreadNotFoundError: 会话不存在（404）
            WorkflowNotInterruptedError: 当前没有中断（409）
            ActionNotAllowedError: 动作与当前中断类型不匹配（409）
            TopicNotFoundError: topic_id 不在候选选题中（422）
            RevisionLimitReachedError: 已达驳回上限仍提交 revise（409）
            ContentValidationError: 修改意见不合法（502）
            其它 WorkflowError / InternalError

        为什么必须「先校验、后调用」？
            S2 实测：一次非法的 ``Command(resume=...)`` 会让该 thread 的
            当前任务进入 error 状态，之后**再用合法的恢复值也推不动了**。
            所以下面这七步校验不是「锦上添花」，而是保护会话可用性的硬前提：

                1. 会话存在（否则连状态都读不到）
                2. 当前确实处于人工中断
                3. 读出并归一化 pending_action
                4. 动作与中断类型匹配
                5. select_topic：topic_id 必须存在于 generated_topics
                6. revise：未达驳回上限
                7. revise：修改意见合法
                8. 动作在 allowed_actions 内

            任何一步失败都会**在调用 Graph 之前**抛错，原会话丝毫不受影响。
        """
        snapshot = await self._require_snapshot(thread_id)
        values = dict(getattr(snapshot, "values", None) or {})

        pending = _to_pending_action(_read_interrupt(snapshot))
        if pending is None:
            raise WorkflowNotInterruptedError(
                "当前流程不处于人工中断点，无法恢复"
                "（可能正在运行、已结束，或上一次执行失败）",
                thread_id=thread_id,
            )

        self._validate_action(thread_id, payload, pending, values)

        # 校验全部通过，才允许触碰 Graph。
        # Command(resume=...) 是 LangGraph 1.x 约定的恢复方式：
        # 被中断的节点会从函数开头重新执行，interrupt() 直接返回这里传进去的值。
        result = await self._invoke(Command(resume=dump_for_graph(payload)), thread_id)
        return self._build_response(thread_id, result, _read_interrupt(result))

    # ------------------------------------------------------------------
    # 内部：Graph 调用（唯一出口）
    # ------------------------------------------------------------------

    async def _invoke(self, graph_input: Any, thread_id: str) -> dict[str, Any]:
        """调用 Graph 并统一处理异常。

        参数:
            graph_input: 初始状态字典（start）或 ``Command(resume=...)``（resume）
            thread_id: 会话标识，同时作为图调用配置

        返回:
            dict: 图运行到中断点或 END 时的状态（中断时额外带 ``__interrupt__``）

        异常:
            WorkflowError: 原样向上传播，并补上 thread_id
            InternalError: 未预期异常统一包装

        说明:
            本方法是**整个应用里唯一调用 ``graph.ainvoke`` 的地方**：
            图调用（含恢复方式、异常映射、日志）只有一份实现，
            不会出现「某个端点忘了做异常映射」这类漏洞。
        """
        config = self._workflow.build_config(thread_id)
        try:
            return await self._workflow.graph.ainvoke(graph_input, config)
        except WorkflowError as exc:
            # 节点抛出的领域异常：补上 thread_id 便于前端定位会话，再原样传播。
            # 为什么是「补上」而不是「包装」：包装会丢掉原始异常类型，
            # 让上层再也无法按 code 精确映射。
            if exc.thread_id is None:
                exc.thread_id = thread_id
            raise
        except Exception as exc:  # noqa: BLE001 —— 这里就是要兜住所有未预期异常
            # 真实原因只写进服务端日志；对外的 message 是固定文案，
            # 绝不把原始异常（可能含连接串、密钥、内部路径）拼进响应体。
            logger.exception("工作流执行失败 thread_id=%s", thread_id)
            raise InternalError("服务内部错误，请稍后重试", thread_id=thread_id) from exc

    # ------------------------------------------------------------------
    # 内部：会话存在性
    # ------------------------------------------------------------------

    async def _require_snapshot(self, thread_id: str) -> Any:
        """读取状态快照；会话不存在时抛 404。

        返回类型是 LangGraph 的 ``StateSnapshot``——**只在服务内部流转**，
        绝不出现在任何响应模型里。
        """
        snapshot = await self._workflow.graph.aget_state(self._workflow.build_config(thread_id))
        if not _snapshot_exists(snapshot):
            raise ThreadNotFoundError(
                "会话不存在或已过期（S3 使用内存检查点，服务重启后历史会话会丢失）",
                thread_id=thread_id,
            )
        return snapshot

    # ------------------------------------------------------------------
    # 内部：前置校验
    # ------------------------------------------------------------------

    def _validate_action(
        self,
        thread_id: str,
        payload: ResumeRequest,
        pending: PendingAction,
        values: dict[str, Any],
    ) -> None:
        """恢复前的强制校验，全部通过才允许调用 Graph。

        参数:
            thread_id: 会话标识（仅用于错误信息）
            payload: 人工动作
            pending: 当前中断归一化后的待办动作
            values: 当前状态值（校验 topic_id 与 revision_count 用）

        异常:
            对应的领域异常；调用方（路由）不再做任何二次判断

        校验顺序的考量:
            「动作与中断类型是否匹配」放在最前，是为了让
            「选题阶段提交 approve」得到 ``ACTION_NOT_ALLOWED``；
            而「驳回是否超限」必须早于「是否在 allowed_actions 内」，
            否则达到上限的 revise 会先撞上「动作不在列表里」，
            错误码就变成 ACTION_NOT_ALLOWED 而不是更精确的 REVISION_LIMIT_REACHED。
        """
        action = payload.action

        # ---- 第 4 步：动作与中断类型是否匹配 ----
        if isinstance(payload, SelectTopicAction):
            if not isinstance(pending, TopicSelectionPending):
                raise ActionNotAllowedError(
                    f"当前处于 {pending.type} 中断点，不接受动作 {action!r}",
                    thread_id=thread_id,
                )

            # ---- 第 5 步：topic_id 必须真实存在于候选选题中 ----
            # 以**状态里的** generated_topics 为准，而不是中断载荷里的副本：
            # 状态是唯一真相，载荷只是它在某个时刻的投影。
            topic_ids = [
                topic.get("id")
                for topic in values.get("generated_topics") or []
                if isinstance(topic, dict)
            ]
            if payload.topic_id not in topic_ids:
                raise TopicNotFoundError(
                    f"候选选题中不存在 id={payload.topic_id!r}，可选：{topic_ids}",
                    thread_id=thread_id,
                )

        elif isinstance(payload, ReviseAction):
            if not isinstance(pending, ArticleReviewPending):
                raise ActionNotAllowedError(
                    f"当前处于 {pending.type} 中断点，不接受动作 {action!r}",
                    thread_id=thread_id,
                )

            # ---- 第 6 步：驳回次数未达上限 ----
            # 上限来自图本身（build_workflow 时注入），保证与节点内的判断同源。
            revision_count = int(values.get("revision_count") or 0)
            if revision_count >= self.max_revisions:
                raise RevisionLimitReachedError(
                    f"文章已重写 {revision_count} 次，达到上限 {self.max_revisions}，"
                    f"此时只允许 {APPROVE_ACTION}",
                    thread_id=thread_id,
                )

            # ---- 第 7 步：修改意见合法 ----
            # 正常情况下 Pydantic 已经拦过（min_length=5），这里是第二道防线：
            # 服务可能被别处调用（脚本、测试、未来的内部任务），不能假设总经过接口层。
            if len(payload.feedback.strip()) < MIN_FEEDBACK_LENGTH:
                raise ContentValidationError(
                    f"驳回时必须提供至少 {MIN_FEEDBACK_LENGTH} 个字符的修改意见",
                    thread_id=thread_id,
                )

        elif isinstance(payload, ApproveAction):
            # 通过：唯一的前置条件就是「当前必须处于审稿中断」
            if not isinstance(pending, ArticleReviewPending):
                raise ActionNotAllowedError(
                    f"当前处于 {pending.type} 中断点，不接受动作 {action!r}",
                    thread_id=thread_id,
                )

        # ---- 第 8 步：兜底——动作必须在 allowed_actions 内 ----
        # 前面按类型判过一遍，这里再按「节点声明的允许清单」判一遍。
        # 两者看似重复，实则一个管「语义」、一个管「当前轮次的策略」：
        # 例如达到驳回上限后，节点会把 allowed_actions 收窄为 ["approve"]，
        # 未来还可能收窄出更多组合，这类策略变化不该让本方法再改一遍。
        if action not in pending.allowed_actions:
            raise ActionNotAllowedError(
                f"当前中断点只允许 {list(pending.allowed_actions)}，收到 {action!r}",
                thread_id=thread_id,
            )

    # ------------------------------------------------------------------
    # 内部：响应构造
    # ------------------------------------------------------------------

    def _build_response(
        self,
        thread_id: str,
        values: dict[str, Any],
        interrupt_payload: dict[str, Any] | None,
    ) -> WorkflowResponse:
        """把内部状态裁剪成对外响应。

        参数:
            thread_id: 会话标识（不属于状态，由调用方提供）
            values: ``MediaWorkflowState`` 的字段字典；start/resume 时来自
                    ainvoke 的返回值，查询时来自 ``StateSnapshot.values``
            interrupt_payload: 归一化前的中断载荷（来自 ``_read_interrupt``）

        返回:
            WorkflowResponse: 严格字段白名单的响应对象

        说明:
            这是「内部结构 → 对外契约」的唯一转换点，因此：
            ``__interrupt__`` / ``tasks`` / ``next`` / ``config`` 等
            LangGraph 内部字段永远不会出现在响应里。
        """
        return WorkflowResponse(
            thread_id=thread_id,
            # status 理论上一定有值；缺字段时退回 planning，避免响应校验失败
            status=str(values.get("status") or WorkflowStatus.PLANNING.value),
            topic_direction=str(values.get("topic_direction") or ""),
            generated_topics=list(values.get("generated_topics") or []),
            selected_topic=values.get("selected_topic"),
            article_content=values.get("article_content"),
            review_action=values.get("review_action"),
            review_feedback=values.get("review_feedback"),
            visual_points=list(values.get("visual_points") or []),
            image_assets=list(values.get("image_assets") or []),
            revision_count=int(values.get("revision_count") or 0),
            error_message=values.get("error_message"),
            pending_action=_to_pending_action(interrupt_payload),
        )
