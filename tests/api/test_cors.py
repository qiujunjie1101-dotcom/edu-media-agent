"""S4 跨源访问（CORS）契约测试。

============================================================================
为什么单独为 CORS 写测试？
============================================================================
CORS 是「浏览器侧的安全边界」，写错的两个典型方向都很危险：

1. 配得太宽（``allow_origins=["*"]`` + 凭证）——浏览器会直接拒绝，
   或者在没有凭证时把接口暴露给任意站点；
2. 配得太窄——前端本地联调直接被浏览器拦掉，且报错信息晦涩难查。

因此这里把「放行谁、放行哪些方法、不放行时是什么表现」全部固化成断言：
以后有人顺手把来源改成 ``*``，或者把方法放开成 ``["*"]``，测试会立刻失败。

本文件只验证 S4 新增的跨源配置，不触碰任何工作流语义。
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

# 默认配置里放行的前端来源（与 .env.example 的 CORS_ALLOW_ORIGINS 保持一致）
ALLOWED_ORIGIN = "http://localhost:5173"
# 一个「没被登记」的来源，用来验证白名单确实生效
DISALLOWED_ORIGIN = "http://evil.example.com"


@pytest.mark.asyncio
async def test_preflight_from_allowed_origin_is_accepted(client: Any) -> None:
    """来自放行来源的预检请求（OPTIONS）会被接受，并回显该来源。

    预检请求是浏览器在发送「非简单请求」前自动发出的探询：
    只有它返回了正确的 ``access-control-allow-origin``，真正的 POST 才会发出。
    """
    response = await client.options(
        "/api/v1/workflows/start",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    # 凭证与具体来源必须同时出现：这正是不允许使用 "*" 的原因
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.asyncio
async def test_preflight_does_not_expose_write_methods(client: Any) -> None:
    """预检不暴露 PUT / DELETE / PATCH。

    S3–S4 的接口面只有 GET / POST，把写方法放开属于不必要的暴露面。
    """
    response = await client.options(
        "/api/v1/workflows/start",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "PUT",
        },
    )

    allowed_methods = response.headers.get("access-control-allow-methods", "")
    assert "PUT" not in allowed_methods
    assert "DELETE" not in allowed_methods
    assert "PATCH" not in allowed_methods


@pytest.mark.asyncio
async def test_origin_outside_allowlist_is_not_granted(client: Any) -> None:
    """未登记来源不会拿到放行头（浏览器因此会拦截响应）。"""
    response = await client.get("/health", headers={"Origin": DISALLOWED_ORIGIN})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_empty_origin_config_disables_cors_entirely() -> None:
    """``CORS_ALLOW_ORIGINS`` 留空时完全不注册中间件。

    这是「默认关闭跨源」的证明：需要跨源必须显式配置，
    而不是默认对全世界开放。
    """
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_allow_origins="",
    )
    app = create_app(settings)

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
            response = await async_client.options(
                "/api/v1/workflows/start",
                headers={
                    "Origin": ALLOWED_ORIGIN,
                    "Access-Control-Request-Method": "POST",
                },
            )

    # 没有中间件时 OPTIONS 不会被特殊处理，也就不会出现任何放行头
    assert "access-control-allow-origin" not in response.headers
