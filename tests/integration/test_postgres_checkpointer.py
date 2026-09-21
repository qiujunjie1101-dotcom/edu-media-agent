"""PostgreSQL Checkpointer 集成测试（S5）。

============================================================================
怎么启用
============================================================================
这组测试需要一个**真实可写**的 PostgreSQL 库，通过环境变量提供：

    export TEST_POSTGRES_URI='postgresql://用户:口令@localhost:5432/langgraph_test'
    python -m pytest tests/integration/test_postgres_checkpointer.py -v

没设这个变量时，整个文件里的用例都会被 skip —— 这是刻意的：
本机没装数据库的人跑 ``pytest`` 必须依然是全绿的，
而且**绝不允许伪造「持久化测试通过」**。

============================================================================
「重启」是怎么模拟的
============================================================================
每次 ``running_app()`` 都会新建一套完整的东西：

    Settings → ServiceContainer → CheckpointerResource（含新的连接池）
             → 编译后的 Graph → WorkflowService → FastAPI app

退出 ``async with`` 时 lifespan 的 finally 会关掉连接池。
所以「关掉一个 running_app、再开一个新的」= 应用、图、服务、连接池
**四者全部销毁重建**，只有 PostgreSQL 里的数据是延续的。
这正是「重启后还能不能恢复」要验证的场景。

============================================================================
两个纪律
============================================================================
1. **绝不清空 checkpoint 表**。每个用例用独立的 thread_id（带 uuid 后缀）
   来保证互不干扰，而不是靠 TRUNCATE——清表会连带毁掉别人正在用的会话。
2. 只使用 LangGraph 自己维护的表，不建任何业务表（那是 S6）。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

# 没有这个环境变量就整体 skip。
# 用 skipif 而不是在测试体里 assert，是为了让「跳过」这件事在报告里
# 明确可见（SKIPPED 而不是 PASSED）。
TEST_POSTGRES_URI = os.environ.get("TEST_POSTGRES_URI", "").strip()

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not TEST_POSTGRES_URI,
        reason=(
            "未设置 TEST_POSTGRES_URI，跳过 PostgreSQL 集成测试。"
            "启用方式见本文件头部说明。"
        ),
    ),
]


def unique_thread_hint() -> str:
    """生成一次性的内容方向，顺带充当「这条会话属于本次运行」的标记。"""
    return f"PG 集成测试 {uuid.uuid4().hex[:12]}"


@pytest.fixture
def pg_settings() -> Settings:
    """指向测试库的配置。池大小取最小，避免一次性占用太多连接。"""
    return Settings(
        _env_file=None,
        app_name="PG 集成测试",
        app_env="test",
        checkpointer_backend="postgres",
        postgres_uri=TEST_POSTGRES_URI,
        postgres_pool_min_size=1,
        postgres_pool_max_size=4,
    )


@asynccontextmanager
async def running_app(settings: Settings) -> AsyncIterator[tuple[AsyncClient, Any]]:
    """启动一套完整的应用（含 lifespan），退出时完整关闭。

    yield 出来的是 ``(HTTP 客户端, FastAPI 实例)``。
    FastAPI 实例用于在关闭后检查连接池确实被释放了。
    """
    application = create_app(settings)
    transport = ASGITransport(app=application)
    async with application.router.lifespan_context(application):
        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http, application


# ---------------------------------------------------------------------------
# 表结构
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_creates_langgraph_tables(pg_settings: Settings) -> None:
    """启动即完成表结构迁移，且**只创建 LangGraph 自己需要的表**。

    这条断言同时也是「数据库边界」的守卫：一旦有人在这里建了
    workflow_session 之类的业务表，测试会立刻失败。
    """
    async with running_app(pg_settings) as (_, application):
        pool = application.state.checkpointer.pool
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "select tablename from pg_tables where schemaname = 'public' order by tablename"
                )
                tables = {row["tablename"] for row in await cur.fetchall()}

    langgraph_tables = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
    assert langgraph_tables <= tables, f"缺少 LangGraph 表：{langgraph_tables - tables}"

    forbidden = {"workflow_session", "content_artifact", "review_log"}
    assert not (forbidden & tables), f"出现了 S6 才该有的业务表：{forbidden & tables}"


# ---------------------------------------------------------------------------
# 重启恢复
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interrupt_survives_full_restart(pg_settings: Settings) -> None:
    """跑到人工审核中断 → 完全重启 → 凭 thread_id 仍能看到文章与待办动作。"""
    direction = unique_thread_hint()

    # ---- 第一次启动：跑到「等待审核」中断 ----
    async with running_app(pg_settings) as (http, _):
        started = await http.post("/api/v1/workflows/start", json={"topic_direction": direction})
        assert started.status_code == 201
        thread_id = started.json()["thread_id"]

        resumed = await http.post(
            f"/api/v1/workflows/{thread_id}/resume",
            json={"action": "select_topic", "topic_id": "t1"},
        )
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "awaiting_review"
        article_before = resumed.json()["article_content"]
        assert article_before

    # ---- 完全重启：新的池、新的图、新的服务 ----
    async with running_app(pg_settings) as (http2, _):
        restored = await http2.get(f"/api/v1/workflows/{thread_id}")

        assert restored.status_code == 200
        body = restored.json()
        assert body["status"] == "awaiting_review"
        assert body["article_content"] == article_before
        assert body["pending_action"]["type"] == "article_review"
        assert body["topic_direction"] == direction


@pytest.mark.asyncio
async def test_resume_continues_after_restart(pg_settings: Settings) -> None:
    """重启后**继续推进**流程，而不只是能读到状态。"""
    async with running_app(pg_settings) as (http, _):
        thread_id = (
            await http.post("/api/v1/workflows/start", json={"topic_direction": unique_thread_hint()})
        ).json()["thread_id"]
        await http.post(
            f"/api/v1/workflows/{thread_id}/resume",
            json={"action": "select_topic", "topic_id": "t1"},
        )

    # 重启后提交一次驳回
    async with running_app(pg_settings) as (http2, _):
        revised = await http2.post(
            f"/api/v1/workflows/{thread_id}/resume",
            json={"action": "revise", "feedback": "请补充一个最小可运行示例"},
        )
        assert revised.status_code == 200
        assert revised.json()["status"] == "awaiting_review"
        assert revised.json()["revision_count"] == 1
        article_after_revise = revised.json()["article_content"]

    # 再重启一次，确认驳回的结果也落库了
    async with running_app(pg_settings) as (http3, _):
        again = await http3.get(f"/api/v1/workflows/{thread_id}")

        assert again.status_code == 200
        assert again.json()["revision_count"] == 1
        assert again.json()["article_content"] == article_after_revise


@pytest.mark.asyncio
async def test_completed_state_persists_across_restart(pg_settings: Settings) -> None:
    """走完整条流程后重启，最终状态与 image_assets 依然可查。"""
    async with running_app(pg_settings) as (http, _):
        thread_id = (
            await http.post("/api/v1/workflows/start", json={"topic_direction": unique_thread_hint()})
        ).json()["thread_id"]
        await http.post(
            f"/api/v1/workflows/{thread_id}/resume",
            json={"action": "select_topic", "topic_id": "t1"},
        )
        finished = await http.post(
            f"/api/v1/workflows/{thread_id}/resume", json={"action": "approve"}
        )
        assert finished.status_code == 200
        assert finished.json()["status"] == "completed"
        asset_count = len(finished.json()["image_assets"])
        assert asset_count > 0

    async with running_app(pg_settings) as (http2, _):
        restored = await http2.get(f"/api/v1/workflows/{thread_id}")

        assert restored.status_code == 200
        assert restored.json()["status"] == "completed"
        assert len(restored.json()["image_assets"]) == asset_count
        assert restored.json()["article_content"]


@pytest.mark.asyncio
async def test_threads_stay_isolated_across_restart(pg_settings: Settings) -> None:
    """两条会话交错推进，重启后各自的状态不串线。"""
    async with running_app(pg_settings) as (http, _):
        first = (
            await http.post("/api/v1/workflows/start", json={"topic_direction": unique_thread_hint()})
        ).json()["thread_id"]
        second = (
            await http.post("/api/v1/workflows/start", json={"topic_direction": unique_thread_hint()})
        ).json()["thread_id"]

        assert first != second

        # 第一条推进到审核，第二条停在选题
        await http.post(
            f"/api/v1/workflows/{first}/resume",
            json={"action": "select_topic", "topic_id": "t1"},
        )
        await http.post(
            f"/api/v1/workflows/{second}/resume",
            json={"action": "select_topic", "topic_id": "t2"},
        )
        # 第一条再驳回一次，制造两条会话的差异
        await http.post(
            f"/api/v1/workflows/{first}/resume",
            json={"action": "revise", "feedback": "第一条会话的修改意见"},
        )
        first_article = (await http.get(f"/api/v1/workflows/{first}")).json()["article_content"]

    async with running_app(pg_settings) as (http2, _):
        a = (await http2.get(f"/api/v1/workflows/{first}")).json()
        b = (await http2.get(f"/api/v1/workflows/{second}")).json()

        assert a["thread_id"] == first
        assert b["thread_id"] == second
        assert a["revision_count"] == 1
        assert b["revision_count"] == 0
        assert a["article_content"] == first_article
        assert a["selected_topic"]["id"] == "t1"
        assert b["selected_topic"]["id"] == "t2"


# ---------------------------------------------------------------------------
# 表结构与连接池的生命周期
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pool_is_closed_on_shutdown(pg_settings: Settings) -> None:
    """应用关闭后连接池必须真的被关掉，不能留下后台连接。"""
    async with running_app(pg_settings) as (_, application):
        pool = application.state.checkpointer.pool
        assert not pool.closed, "运行期间连接池应当是打开状态"

    # 退出 lifespan 后
    assert pool.closed, "关闭应用后连接池没有被释放"


@pytest.mark.asyncio
async def test_repeated_setup_keeps_existing_checkpoints(pg_settings: Settings) -> None:
    """重复 setup（= 再次启动应用）不得清空已有检查点。

    ``AsyncPostgresSaver.setup()`` 读 ``checkpoint_migrations`` 的最大版本号，
    只补跑增量迁移，所以重复调用是幂等的。这条测试把这个前提钉死：
    一旦将来库改成「先 DROP 再 CREATE」，会话就会在每次重启时集体蒸发。
    """
    async with running_app(pg_settings) as (http, _):
        thread_id = (
            await http.post("/api/v1/workflows/start", json={"topic_direction": unique_thread_hint()})
        ).json()["thread_id"]
        await http.post(
            f"/api/v1/workflows/{thread_id}/resume",
            json={"action": "select_topic", "topic_id": "t1"},
        )

    # 再启动两次，每次都会执行一次 setup()
    for _ in range(2):
        async with running_app(pg_settings) as (http2, _):
            restored = await http2.get(f"/api/v1/workflows/{thread_id}")
            assert restored.status_code == 200, "重复 setup 之后会话丢失了"
            assert restored.json()["status"] == "awaiting_review"
