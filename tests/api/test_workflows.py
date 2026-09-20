"""S3：三个工作流 HTTP 接口的契约、状态流转与错误码测试。

============================================================================
这个文件覆盖什么
============================================================================
技术方案第 7 章的 API 契约 + 本阶段「必测场景」1–15：

    POST /api/v1/workflows/start               启动，停在选题中断
    GET  /api/v1/workflows/{thread_id}         查询最新状态
    POST /api/v1/workflows/{thread_id}/resume  恢复（选题 / 通过 / 驳回）

以及本阶段最关键的一条工程约束：
**任何非法请求都不得调用 Graph，原 thread 必须仍可继续使用。**

============================================================================
两层断言策略
============================================================================
1. **HTTP 层**：状态码、错误码、响应字段集合；
2. **状态机层**：通过后续合法请求能继续推进，证明 thread 没被弄脏。
   例如「选题阶段误传 approve 返回 409」之后，紧接着必须能成功 select_topic。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_workflow_service
from app.core.exceptions import ContentValidationError, LLMUnavailableError
from app.graph.builder import build_workflow
from app.graph.routing import APPROVE_ACTION, REVISE_ACTION, SELECT_TOPIC_ACTION
from app.main import create_app
from app.schemas.domain import ImageAsset, ImageAssetStatus, TopicCandidate, VisualPoint
from app.services.image.base import ImageService
from app.services.image.mock import MockImageService
from app.services.llm.base import LLMService
from app.services.llm.mock import MockLLMService
from app.services.workflow_service import WorkflowService

DIRECTION = "LangGraph 人工审核教程"
OTHER_DIRECTION = "AI 训练师面试准备"

FEEDBACK_A = "请补充一个最小可运行代码示例"
FEEDBACK_B = "第二段太啰嗦，请压缩到三句话以内"
FEEDBACK_C = "请把代码示例换成伪代码"

MAX_REVISIONS = 3

API = "/api/v1/workflows"

# 响应契约：字段白名单。多一个字段（例如把 LangGraph 的 __interrupt__ 漏出去）
# 都会被下面的断言抓住。
EXPECTED_FIELDS = {
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


# ---------------------------------------------------------------------------
# 测试替身：只在「异常映射」与「图片降级」两个场景使用
# ---------------------------------------------------------------------------


class _FailingLLMService(LLMService):
    """任何调用都抛指定异常的文本模型替身，用来验证错误码映射。"""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def plan_topics(self, direction: str) -> list[TopicCandidate]:
        raise self._exc

    async def write_article(self, topic: TopicCandidate, feedback: str | None = None) -> str:
        raise self._exc

    async def extract_visual_points(self, article: str) -> list[VisualPoint]:
        raise self._exc


class _FailOnWriteLLMService(LLMService):
    """选题正常、但一进入写作就失败的替身。

    用途：验证**恢复路径**上的异常映射。
    start 必须能成功（否则拿不到 thread_id），所以不能复用「全失败」的替身。
    """

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self._delegate = MockLLMService()

    async def plan_topics(self, direction: str) -> list[TopicCandidate]:
        return await self._delegate.plan_topics(direction)

    async def write_article(self, topic: TopicCandidate, feedback: str | None = None) -> str:
        raise self._exc

    async def extract_visual_points(self, article: str) -> list[VisualPoint]:
        raise self._exc


class _PartialImageService(ImageService):
    """指定 visual_point_id 失败、其余成功的图片替身（部分失败降级场景）。"""

    def __init__(self, fail_ids: set[str]) -> None:
        self._fail_ids = fail_ids

    async def generate(self, prompt: str, size: str, visual_point_id: str) -> ImageAsset:
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


@pytest.fixture
def override_workflow(app: Any) -> Any:
    """把应用的工作流服务替换成「用自定义服务构建」的实例。

    为什么用 dependency_overrides 而不是重建 app？
        这正是「服务通过依赖注入获取」这条架构约定带来的红利：
        替换实现不需要改应用代码，也不用真去改 .env。
        覆盖只作用于当前测试自己的 app 实例（app 夹具是函数级）。
    """

    def _override(
        *,
        llm_service: LLMService | None = None,
        image_service: ImageService | None = None,
    ) -> None:
        workflow = build_workflow(
            llm_service=llm_service or MockLLMService(),
            image_service=image_service or MockImageService(),
            max_revisions=MAX_REVISIONS,
        )
        app.dependency_overrides[get_workflow_service] = lambda: WorkflowService(workflow)

    return _override


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _assert_contract(body: dict[str, Any]) -> None:
    """所有成功响应都必须严格符合字段白名单。"""
    assert set(body) == EXPECTED_FIELDS, f"响应字段不符合契约：{sorted(body)}"


async def _start(client: AsyncClient, direction: str = DIRECTION) -> dict[str, Any]:
    """启动一条工作流，返回响应体。"""
    response = await client.post(f"{API}/start", json={"topic_direction": direction})
    assert response.status_code == 201, response.text
    return response.json()


async def _get(client: AsyncClient, thread_id: str) -> dict[str, Any]:
    response = await client.get(f"{API}/{thread_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def _resume(client: AsyncClient, thread_id: str, payload: dict[str, Any]) -> Any:
    """提交恢复请求，返回原始响应（由调用方断言状态码）。"""
    return await client.post(f"{API}/{thread_id}/resume", json=payload)


async def _resume_ok(client: AsyncClient, thread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = await _resume(client, thread_id, payload)
    assert response.status_code == 200, response.text
    return response.json()


async def _select_topic(client: AsyncClient, thread_id: str, topic_id: str = "t1") -> dict[str, Any]:
    return await _resume_ok(
        client, thread_id, {"action": SELECT_TOPIC_ACTION, "topic_id": topic_id}
    )


async def _approve(client: AsyncClient, thread_id: str) -> dict[str, Any]:
    return await _resume_ok(client, thread_id, {"action": APPROVE_ACTION})


async def _revise(client: AsyncClient, thread_id: str, feedback: str) -> dict[str, Any]:
    return await _resume_ok(client, thread_id, {"action": REVISE_ACTION, "feedback": feedback})


def _error(body: dict[str, Any]) -> dict[str, Any]:
    """取出统一错误体里的 detail。"""
    assert "detail" in body, body
    return body["detail"]


# ---------------------------------------------------------------------------
# 场景 2–3：启动并停在选题中断；GET 能恢复同一状态
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_returns_201_and_stops_at_topic_selection(client: AsyncClient) -> None:
    """场景 2：start 返回 201，状态停在选题中断，pending_action 精确匹配契约。"""
    response = await client.post(f"{API}/start", json={"topic_direction": DIRECTION})

    assert response.status_code == 201
    body = response.json()
    _assert_contract(body)

    # thread_id 由服务端生成，且必须是合法 UUID
    assert uuid.UUID(body["thread_id"])

    assert body["status"] == "awaiting_topic_selection"
    assert body["topic_direction"] == DIRECTION
    assert 3 <= len(body["generated_topics"]) <= 5

    # 尚未进入写作环节
    assert body["selected_topic"] is None
    assert body["article_content"] is None
    assert body["visual_points"] == []
    assert body["image_assets"] == []
    assert body["revision_count"] == 0
    assert body["review_action"] is None
    assert body["review_feedback"] is None
    assert body["error_message"] is None

    assert body["pending_action"] == {
        "type": "topic_selection",
        "allowed_actions": [SELECT_TOPIC_ACTION],
    }


@pytest.mark.asyncio
async def test_get_returns_same_state_as_start(client: AsyncClient) -> None:
    """场景 3：GET 用同一 thread_id 取回与 start 完全一致的状态。"""
    started = await _start(client)
    fetched = await _get(client, started["thread_id"])

    _assert_contract(fetched)
    assert fetched == started


@pytest.mark.asyncio
async def test_get_does_not_leak_langgraph_internals(client: AsyncClient) -> None:
    """GET 响应里不得出现 __interrupt__ / tasks / next 等框架内部结构。"""
    started = await _start(client)
    fetched = await _get(client, started["thread_id"])

    for forbidden in ("__interrupt__", "tasks", "next", "snapshot", "values", "config"):
        assert forbidden not in fetched


# ---------------------------------------------------------------------------
# 场景 4–6：选题 → 审稿 → 通过完成
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_topic_stops_at_article_review(client: AsyncClient) -> None:
    """场景 4：select_topic 后生成初稿并停在文章审核中断。"""
    started = await _start(client)
    body = await _select_topic(client, started["thread_id"], "t2")

    _assert_contract(body)
    assert body["status"] == "awaiting_review"
    assert body["selected_topic"]["id"] == "t2"
    assert body["article_content"]
    assert body["revision_count"] == 0
    assert body["review_action"] is None
    assert body["pending_action"] == {
        "type": "article_review",
        "allowed_actions": [APPROVE_ACTION, REVISE_ACTION],
        "revision_count": 0,
        "revision_limit_reached": False,
    }

    # GET 与 resume 的返回结构一致
    assert (await _get(client, started["thread_id"])) == body


@pytest.mark.asyncio
async def test_revise_produces_new_draft_and_increments_revision_count(
    client: AsyncClient,
) -> None:
    """场景 5：revise 生成新稿，revision_count 正确 +1，旧审核结论被清空。"""
    started = await _start(client)
    thread_id = started["thread_id"]
    first = await _select_topic(client, thread_id)
    first_draft = first["article_content"]

    body = await _revise(client, thread_id, FEEDBACK_A)

    assert body["revision_count"] == 1
    assert body["article_content"] != first_draft
    assert FEEDBACK_A in body["article_content"]
    assert body["review_action"] is None
    assert body["review_feedback"] is None
    assert body["status"] == "awaiting_review"
    assert body["pending_action"]["revision_count"] == 1


@pytest.mark.asyncio
async def test_approve_completes_workflow_with_image_assets(client: AsyncClient) -> None:
    """场景 6：approve 后跑完生图链路，返回 image_assets 且 pending_action 为 null。"""
    started = await _start(client)
    thread_id = started["thread_id"]
    await _select_topic(client, thread_id)

    body = await _approve(client, thread_id)

    _assert_contract(body)
    assert body["status"] == "completed"
    assert body["pending_action"] is None
    assert body["error_message"] is None
    assert 3 <= len(body["visual_points"]) <= 5
    assert len(body["image_assets"]) == len(body["visual_points"])
    assert [asset["visual_point_id"] for asset in body["image_assets"]] == [
        point["id"] for point in body["visual_points"]
    ]
    assert all(asset["status"] == "success" for asset in body["image_assets"])
    assert all(asset["url"] for asset in body["image_assets"])


@pytest.mark.asyncio
async def test_full_loop_through_http(client: AsyncClient) -> None:
    """第一版完成标准：start → get → select → get → revise → get → approve → image_assets。"""
    started = await _start(client)
    thread_id = started["thread_id"]

    assert (await _get(client, thread_id))["status"] == "awaiting_topic_selection"
    await _select_topic(client, thread_id)
    assert (await _get(client, thread_id))["status"] == "awaiting_review"
    await _revise(client, thread_id, FEEDBACK_A)
    assert (await _get(client, thread_id))["revision_count"] == 1
    final = await _approve(client, thread_id)

    assert (await _get(client, thread_id))["image_assets"] == final["image_assets"]


# ---------------------------------------------------------------------------
# 场景 7–9：非法请求必须被前置校验挡住，且 thread 不可损坏
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_at_topic_stage_is_rejected_and_thread_still_usable(
    client: AsyncClient,
) -> None:
    """场景 7：选题阶段提交 approve → 409 ACTION_NOT_ALLOWED；随后合法选题仍成功。"""
    started = await _start(client)
    thread_id = started["thread_id"]

    response = await _resume(client, thread_id, {"action": APPROVE_ACTION})

    assert response.status_code == 409
    assert _error(response.json())["code"] == "ACTION_NOT_ALLOWED"
    assert _error(response.json())["thread_id"] == thread_id

    # 关键证据：thread 没有被弄脏，仍停在选题中断
    state = await _get(client, thread_id)
    assert state["status"] == "awaiting_topic_selection"
    assert state["article_content"] is None
    assert state["pending_action"]["type"] == "topic_selection"

    # 紧接着的合法请求必须成功
    after = await _select_topic(client, thread_id, "t1")
    assert after["status"] == "awaiting_review"


@pytest.mark.asyncio
async def test_unknown_topic_id_is_rejected_and_thread_still_usable(client: AsyncClient) -> None:
    """场景 8：非法 topic_id → 422 TOPIC_NOT_FOUND；随后合法 topic_id 仍成功。"""
    started = await _start(client)
    thread_id = started["thread_id"]

    response = await _resume(
        client, thread_id, {"action": SELECT_TOPIC_ACTION, "topic_id": "t-not-exist"}
    )

    assert response.status_code == 422
    assert _error(response.json())["code"] == "TOPIC_NOT_FOUND"

    state = await _get(client, thread_id)
    assert state["status"] == "awaiting_topic_selection"
    assert state["selected_topic"] is None
    assert state["article_content"] is None

    after = await _select_topic(client, thread_id, "t3")
    assert after["selected_topic"]["id"] == "t3"


@pytest.mark.asyncio
async def test_revise_at_limit_is_rejected_and_approve_still_completes(
    client: AsyncClient,
) -> None:
    """场景 9：驳回用尽后 revise → 409 REVISION_LIMIT_REACHED；随后 approve 仍能完成。"""
    started = await _start(client)
    thread_id = started["thread_id"]
    await _select_topic(client, thread_id)
    await _revise(client, thread_id, FEEDBACK_A)
    await _revise(client, thread_id, FEEDBACK_B)
    at_limit = await _revise(client, thread_id, FEEDBACK_C)

    assert at_limit["revision_count"] == MAX_REVISIONS
    assert at_limit["pending_action"] == {
        "type": "article_review",
        "allowed_actions": [APPROVE_ACTION],
        "revision_count": MAX_REVISIONS,
        "revision_limit_reached": True,
    }

    response = await _resume(client, thread_id, {"action": REVISE_ACTION, "feedback": FEEDBACK_A})

    assert response.status_code == 409
    assert _error(response.json())["code"] == "REVISION_LIMIT_REACHED"

    state = await _get(client, thread_id)
    assert state["status"] == "awaiting_review"
    assert state["revision_count"] == MAX_REVISIONS
    assert state["visual_points"] == []

    final = await _approve(client, thread_id)
    assert final["status"] == "completed"
    assert final["revision_count"] == MAX_REVISIONS


@pytest.mark.asyncio
async def test_duplicate_resume_after_completion_is_rejected(client: AsyncClient) -> None:
    """场景 10：已完成流程再次 resume → 409 WORKFLOW_NOT_INTERRUPTED（幂等守卫）。"""
    started = await _start(client)
    thread_id = started["thread_id"]
    await _select_topic(client, thread_id)
    await _approve(client, thread_id)

    response = await _resume(client, thread_id, {"action": APPROVE_ACTION})

    assert response.status_code == 409
    assert _error(response.json())["code"] == "WORKFLOW_NOT_INTERRUPTED"

    # 状态没有被二次推进
    state = await _get(client, thread_id)
    assert state["status"] == "completed"
    assert state["pending_action"] is None


@pytest.mark.asyncio
async def test_duplicate_select_topic_is_rejected_and_first_result_kept(
    client: AsyncClient,
) -> None:
    """重复提交同一动作：第一次成功，第二次因为已不在该中断点而 409。"""
    started = await _start(client)
    thread_id = started["thread_id"]
    first = await _select_topic(client, thread_id, "t1")

    response = await _resume(
        client, thread_id, {"action": SELECT_TOPIC_ACTION, "topic_id": "t2"}
    )

    assert response.status_code == 409
    assert _error(response.json())["code"] == "ACTION_NOT_ALLOWED"

    # 选题没有被改成 t2
    assert (await _get(client, thread_id))["selected_topic"]["id"] == "t1"
    assert first["selected_topic"]["id"] == "t1"


# ---------------------------------------------------------------------------
# 场景 11–12：404 与 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_thread_returns_404_on_get(client: AsyncClient) -> None:
    """场景 11：不存在的 thread_id → 404 THREAD_NOT_FOUND。"""
    response = await client.get(f"{API}/{uuid.uuid4()}")

    assert response.status_code == 404
    assert _error(response.json())["code"] == "THREAD_NOT_FOUND"


@pytest.mark.asyncio
async def test_unknown_thread_returns_404_on_resume(client: AsyncClient) -> None:
    """不存在的 thread_id 提交 resume → 404（绝不能落到 Graph 上）。"""
    thread_id = str(uuid.uuid4())
    response = await _resume(client, thread_id, {"action": APPROVE_ACTION})

    assert response.status_code == 404
    assert _error(response.json())["code"] == "THREAD_NOT_FOUND"
    assert _error(response.json())["thread_id"] == thread_id


@pytest.mark.asyncio
async def test_thread_id_gone_after_app_restart_like_new_instance(
    client: AsyncClient,
    settings: Any,
) -> None:
    """换一个全新的应用实例（等价于进程重启），旧 thread_id 应当 404。

    S3 用的是 InMemorySaver：会话只活在进程内存里。
    这条测试把这个限制**显式地固定成契约**，避免将来有人误以为
    「重启后还能凭 thread_id 恢复」——那是 S5（PostgreSQL Checkpointer）的目标。
    """
    started = await _start(client)

    fresh_app = create_app(settings)
    async with fresh_app.router.lifespan_context(fresh_app):
        transport = ASGITransport(app=fresh_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as fresh:
            response = await fresh.get(f"{API}/{started['thread_id']}")

    assert response.status_code == 404
    assert _error(response.json())["code"] == "THREAD_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"topic_direction": "a"},  # 长度不足 2
        {"topic_direction": "x" * 201},  # 超过 200
        {},  # 缺字段
        {"topic_direction": "合法方向", "idempotency_key": "k"},  # 多余字段
    ],
)
async def test_invalid_start_body_returns_422(client: AsyncClient, payload: dict[str, Any]) -> None:
    """场景 12：启动请求体不合法 → 422 VALIDATION_ERROR。"""
    response = await client.post(f"{API}/start", json=payload)

    assert response.status_code == 422
    assert _error(response.json())["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},  # 缺 action
        {"action": "delete_everything"},  # 未知动作
        {"action": SELECT_TOPIC_ACTION},  # 缺 topic_id
        {"action": REVISE_ACTION, "feedback": "不行"},  # 意见过短
        {"action": APPROVE_ACTION, "topic_id": "t1"},  # 分支字段串味
    ],
)
async def test_invalid_resume_body_returns_422_and_keeps_thread_usable(
    client: AsyncClient, payload: dict[str, Any]
) -> None:
    """场景 12：恢复请求体不合法 → 422，且不得影响 thread 的后续使用。"""
    started = await _start(client)
    thread_id = started["thread_id"]

    response = await _resume(client, thread_id, payload)

    assert response.status_code == 422
    assert _error(response.json())["code"] == "VALIDATION_ERROR"

    # 请求根本没被交给服务层，thread 完好
    assert (await _get(client, thread_id))["status"] == "awaiting_topic_selection"
    assert (await _select_topic(client, thread_id, "t1"))["status"] == "awaiting_review"


# ---------------------------------------------------------------------------
# 非法请求不损坏 thread：白盒证据
# ---------------------------------------------------------------------------
# 上面几节证明的是「症状消失了」（后续合法请求仍能成功）。
# 下面两条测试直接检查**机制**：非法请求之后，检查点里的任务是否留下了 error。
# 这是本阶段最关键的一条工程约束，值得用两种粒度的证据各证一次：
#   - 黑盒（行为）：thread 还能继续用；
#   - 白盒（内部）：检查点里没有 error 任务、仍停在原中断点。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_illegal_requests_leave_no_error_task_in_checkpoint(
    client: AsyncClient, app: Any
) -> None:
    """连续三种非法请求后，检查点里不得出现 error 任务，且仍停在原中断点。

    背景（S2 实测的 LangGraph 1.2.11 行为）：
        一次非法的 ``Command(resume=...)`` 会让该 thread 的当前任务进入 error
        状态，之后即使换合法的恢复值也推不动了——会话就此「卡死」。
        S3 用「调用 Graph 之前的强制校验」把非法请求全部拦在门外，
        所以检查点里应当干干净净：``tasks[0].error is None``、``next`` 仍是原节点。
    """
    started = await _start(client)
    thread_id = started["thread_id"]

    # 1) 409：选题阶段提交 approve
    assert (await _resume(client, thread_id, {"action": APPROVE_ACTION})).status_code == 409
    # 2) 422：不存在的 topic_id
    assert (
        await _resume(client, thread_id, {"action": SELECT_TOPIC_ACTION, "topic_id": "t99"})
    ).status_code == 422
    # 3) 422：连请求体都不合法（连服务层都没进）
    assert (await _resume(client, thread_id, {"action": REVISE_ACTION, "feedback": "太短"})).status_code == 422

    # 白盒检查：直接读检查点（服务内部对象，不属于对外契约）
    snapshot = await app.state.workflow.graph.aget_state(
        app.state.workflow.build_config(thread_id)
    )

    assert snapshot.next == ("human_select_topic",), "仍应停在选题中断点"
    assert len(snapshot.tasks) == 1
    assert snapshot.tasks[0].error is None, "非法请求不得在图里留下 error 任务"
    assert snapshot.values["status"] == "awaiting_topic_selection"
    assert snapshot.values["selected_topic"] is None

    # 黑盒检查：随后一切照常
    assert (await _select_topic(client, thread_id, "t1"))["status"] == "awaiting_review"


@pytest.mark.asyncio
async def test_graph_and_checkpointer_are_reused_across_requests(
    client: AsyncClient, app: Any
) -> None:
    """多个请求之间复用同一个 Graph / Checkpointer / WorkflowService 实例。

    这是「中断能够恢复」的前提：只要某次请求重新构了一次图，
    InMemorySaver 就会被换成一个空对象，历史会话瞬间丢失。
    """
    service = app.state.workflow_service
    graph = service.graph
    checkpointer = service.checkpointer

    # 跑一遍完整闭环：其中任何一次请求若重建了实例，下面的断言都会失败
    started = await _start(client)
    thread_id = started["thread_id"]
    await _select_topic(client, thread_id)
    await _revise(client, thread_id, FEEDBACK_A)
    await _approve(client, thread_id)

    assert app.state.workflow_service is service
    assert service.graph is graph
    assert service.checkpointer is checkpointer

    # 会话历史确实还在同一个 Checkpointer 里
    snapshot = await graph.aget_state(service.workflow.build_config(thread_id))
    assert snapshot.values["status"] == "completed"


# ---------------------------------------------------------------------------
# 场景 13：两个 thread 交错执行时的状态隔离
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_threads_are_isolated_through_http(client: AsyncClient) -> None:
    """场景 13：两条会话交错推进，状态互不串线。"""
    a = await _start(client, DIRECTION)
    b = await _start(client, OTHER_DIRECTION)
    assert a["thread_id"] != b["thread_id"]

    await _select_topic(client, a["thread_id"], "t1")
    await _select_topic(client, b["thread_id"], "t3")

    state_a = await _get(client, a["thread_id"])
    state_b = await _get(client, b["thread_id"])

    assert state_a["selected_topic"]["id"] == "t1"
    assert state_b["selected_topic"]["id"] == "t3"
    assert state_a["topic_direction"] == DIRECTION
    assert state_b["topic_direction"] == OTHER_DIRECTION
    assert state_a["article_content"] != state_b["article_content"]

    # A 驳回不影响 B
    await _revise(client, a["thread_id"], FEEDBACK_A)
    assert (await _get(client, a["thread_id"]))["revision_count"] == 1
    assert (await _get(client, b["thread_id"]))["revision_count"] == 0

    # B 完成不影响 A
    assert (await _approve(client, b["thread_id"]))["status"] == "completed"
    still_a = await _get(client, a["thread_id"])
    assert still_a["status"] == "awaiting_review"
    assert still_a["revision_count"] == 1
    assert still_a["image_assets"] == []


# ---------------------------------------------------------------------------
# 场景 14：节点异常 → 对应 HTTP 错误码
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_unavailable_maps_to_503(client: AsyncClient, override_workflow: Any) -> None:
    """场景 14：文本模型上游不可用 → 503 LLM_UNAVAILABLE（start 阶段）。"""
    override_workflow(llm_service=_FailingLLMService(LLMUnavailableError("上游 503")))

    response = await client.post(f"{API}/start", json={"topic_direction": DIRECTION})

    assert response.status_code == 503
    assert _error(response.json())["code"] == "LLM_UNAVAILABLE"


@pytest.mark.asyncio
async def test_llm_unavailable_maps_to_503_on_resume(
    client: AsyncClient, override_workflow: Any
) -> None:
    """场景 14（续）：resume 触发写作时上游不可用 → 503。"""
    override_workflow(llm_service=_FailOnWriteLLMService(LLMUnavailableError("上游 503")))
    started = await _start(client)

    response = await _resume(
        client, started["thread_id"], {"action": SELECT_TOPIC_ACTION, "topic_id": "t1"}
    )

    assert response.status_code == 503
    assert _error(response.json())["code"] == "LLM_UNAVAILABLE"
    assert _error(response.json())["thread_id"] == started["thread_id"]


@pytest.mark.asyncio
async def test_content_validation_error_maps_to_502(
    client: AsyncClient, override_workflow: Any
) -> None:
    """生成内容不符合业务规则 → 502 CONTENT_VALIDATION_ERROR。"""
    override_workflow(
        llm_service=_FailOnWriteLLMService(ContentValidationError("模型返回的正文为空"))
    )
    started = await _start(client)

    response = await _resume(
        client, started["thread_id"], {"action": SELECT_TOPIC_ACTION, "topic_id": "t1"}
    )

    assert response.status_code == 502
    assert _error(response.json())["code"] == "CONTENT_VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_unexpected_node_error_maps_to_500_without_leaking_internals(
    client: AsyncClient, override_workflow: Any
) -> None:
    """场景 14（续）：未预期异常 → 500 INTERNAL_ERROR，且不泄露堆栈/内部对象。"""
    override_workflow(llm_service=_FailingLLMService(RuntimeError("内部细节：数据库密码是 xxx")))

    response = await client.post(f"{API}/start", json={"topic_direction": DIRECTION})
    body = response.json()

    assert response.status_code == 500
    assert _error(body)["code"] == "INTERNAL_ERROR"
    # 原始异常信息不得出现在响应里
    serialized = response.text
    assert "RuntimeError" not in serialized
    assert "数据库密码" not in serialized
    assert "Traceback" not in serialized


# ---------------------------------------------------------------------------
# 场景 15：图片部分失败 → completed_with_warnings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_image_failure_returns_completed_with_warnings(
    client: AsyncClient, override_workflow: Any
) -> None:
    """场景 15：部分图片失败时流程正常完成，状态为 completed_with_warnings。"""
    override_workflow(image_service=_PartialImageService(fail_ids={"vp2"}))
    started = await _start(client)
    thread_id = started["thread_id"]
    await _select_topic(client, thread_id)

    body = await _approve(client, thread_id)

    _assert_contract(body)
    assert body["status"] == "completed_with_warnings"
    assert body["pending_action"] is None
    assert "vp2" in body["error_message"]

    assets = {asset["visual_point_id"]: asset for asset in body["image_assets"]}
    assert len(assets) == len(body["visual_points"])
    assert assets["vp2"]["status"] == "failed"
    assert assets["vp2"]["url"] is None
    assert assets["vp2"]["error"]


@pytest.mark.asyncio
async def test_all_images_failing_maps_to_502(client: AsyncClient, override_workflow: Any) -> None:
    """全部图片失败属于不可恢复错误 → 502 IMAGE_GENERATION_FAILED。"""
    override_workflow(image_service=_PartialImageService(fail_ids={"vp1", "vp2", "vp3", "vp4", "vp5"}))
    started = await _start(client)
    thread_id = started["thread_id"]
    await _select_topic(client, thread_id)

    response = await _resume(client, thread_id, {"action": APPROVE_ACTION})

    assert response.status_code == 502
    assert _error(response.json())["code"] == "IMAGE_GENERATION_FAILED"
