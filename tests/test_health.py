"""验证应用骨架可以正常导入、启动，并且只暴露 /health 一个业务接口。"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

# 导入模块本身（而不是只导入 app 变量），是为了验证「模块可导入」这条验收标准。
import app.main as main_module
from app.services.container import ServiceContainer


def test_app_module_exposes_fastapi_instance() -> None:
    """""import app.main" 不报错，且模块级 app 是一个 FastAPI 实例。

    验收标准 1：FastAPI 能正常导入和启动。
    """
    assert isinstance(main_module.app, FastAPI)


def test_create_app_returns_new_instance_each_time(settings: Any) -> None:
    """应用工厂每次调用都返回独立实例，方便测试注入不同配置。"""
    from app.main import create_app

    first = create_app(settings)
    second = create_app(settings)
    assert first is not second


@pytest.mark.asyncio
async def test_health_endpoint_returns_200(client: Any, settings: Any) -> None:
    """GET /health 返回 200，且响应体字段与配置一致。

    验收标准 2：/health 返回 200 且内容符合约定。

    S5 起增加了 ``checkpointer`` 字段：只暴露后端**名称**，
    用于一眼判断「当前会话重启后会不会丢」。
    """
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "app": settings.app_name,
        "environment": settings.app_env,
        "checkpointer": settings.resolved_checkpointer_backend,
    }


@pytest.mark.asyncio
async def test_health_checkpointer_field_does_not_leak_connection_info(
    settings: Any,
) -> None:
    """``/health`` 只能暴露后端名，绝不能带出连接串的任何片段。

    连接串里含口令，一旦进响应体，就会出现在浏览器、日志、监控采样里。
    这里直接搜索响应原文，确保连主机名、库名、用户名都不出现。
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    secret_uri = "postgresql://leakuser:leakpass@leakhost:5432/leakdb"
    configured = settings.model_copy(
        update={"checkpointer_backend": "memory", "postgres_uri": secret_uri}
    )

    app = create_app(configured)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/health")

    # memory 模式下即便配了连接串，也不该出现在响应里
    assert response.json()["checkpointer"] == "memory"
    raw = response.text
    for fragment in ("leakpass", "leakhost", "leakdb", "leakuser", secret_uri):
        assert fragment not in raw, f"响应体泄露了连接信息：{fragment}"


@pytest.mark.asyncio
async def test_registered_routes_match_current_stage_scope(app: FastAPI) -> None:
    """业务路由清单必须与「当前阶段范围」严格一致。

    S1 断言的是「只有 /health」；S3 交付三个工作流接口后，这里同步升级为
    「/health + 三个工作流路由，且不再多出任何路由」——范围守卫的意图不变：
    多出未申报的接口会被立刻发现。

    为什么用 OpenAPI 的 paths 而不是 ``app.routes``？
        新版 FastAPI（>=0.130）对 ``include_router`` 采用**延迟展开**：
        ``app.routes`` 里只会看到一个 ``_IncludedRouter`` 占位对象，
        子路由并不直接可见。``app.openapi()["paths"]`` 反映的是真实对外暴露的
        接口面，既不依赖框架内部的树形结构，也顺带检查了文档能否正常生成。
    """
    paths = set(app.openapi()["paths"])

    assert paths == {
        "/health",
        "/api/v1/workflows/start",
        "/api/v1/workflows/{thread_id}",
        "/api/v1/workflows/{thread_id}/resume",
    }


@pytest.mark.asyncio
async def test_lifespan_builds_service_container(app: FastAPI) -> None:
    """应用启动钩子（lifespan）会装配服务容器并挂到 app.state 上。

    lifespan 是 FastAPI 的启动/关闭钩子：里面 yield 之前的代码在服务启动时执行。
    测试里用 "async with app.router.lifespan_context(app)" 手动进入该上下文，
    等价于真实启动一次服务，从而验证容器装配成功。
    """
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.container, ServiceContainer)
        assert app.state.settings is not None


@pytest.mark.asyncio
async def test_lifespan_builds_single_workflow_service_instance(app: FastAPI) -> None:
    """S3 验收：Graph、Checkpointer 与 WorkflowService 在应用生命周期内是同一个实例。

    做法：进入 lifespan 后连续取两次服务，断言 ``is`` 相等；
    并断言服务内部持有的图与检查点，就是 ``app.state.workflow`` 里那一份。
    """
    from app.services.workflow_service import WorkflowService

    async with app.router.lifespan_context(app):
        service = app.state.workflow_service
        assert isinstance(service, WorkflowService)
        # 同一个实例：不会为每个请求重新构图、重新建 Checkpointer
        assert app.state.workflow_service is service
        assert service.workflow is app.state.workflow
        assert service.graph is app.state.workflow.graph
        assert service.checkpointer is app.state.workflow.checkpointer
