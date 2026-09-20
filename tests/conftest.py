"""pytest 公共 fixture 配置。

============================================================================
这个文件是做什么的？
============================================================================
pytest 会自动加载名为 ``conftest.py`` 的文件，其中用 ``@pytest.fixture`` 装饰的函数
会变成「测试夹具（fixture）」：测试函数只要把夹具名写成参数，pytest 就会自动调用它
并把返回值注入进来。这样做的好处是：多个测试文件可以共享同一套准备工作
（比如「造一个配置对象」「造一个 HTTP 客户端」），不用每个测试重复写一遍。

============================================================================
本文件提供的夹具
============================================================================
- settings          : 一个与真实 .env 隔离的测试配置对象
- container         : 按测试配置装配好的服务容器（内含 Mock 服务）
- app               : 用测试配置构建的 FastAPI 应用
- client            : 直接调用 ASGI 应用的异步 HTTP 客户端（无需启动真实端口）
- no_network        : 禁止一切网络连接的「护栏」，用来证明 Mock 服务不联网
"""

from __future__ import annotations

# socket 是 Python 标准库中的网络通信模块。我们要把它的底层连接方法替换掉，
# 从而在任何代码试图联网时立刻抛错。
import socket

# collections.abc 里的这两个类型用于给「生成器夹具」写返回类型注解：
# - AsyncIterator：可以被 async for 遍历的异步迭代器（异步夹具用）
# - Iterator     ：普通迭代器（同步夹具用）
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

# pytest_asyncio 是第三方插件：pytest 本身只支持同步测试函数，
# 加上它之后才能写 "async def test_xxx()" 这样的异步测试。
import pytest_asyncio

# httpx 是异步 HTTP 客户端库。这里用它的 ASGITransport：
# 让请求不经过真实网络，而是直接交给内存中的 FastAPI 应用对象处理。
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.graph.builder import CompiledWorkflow, build_workflow
from app.main import create_app
from app.services.container import ServiceContainer
from app.services.image.mock import MockImageService
from app.services.llm.mock import MockLLMService

# ---------------------------------------------------------------------------
# 基础夹具
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    """构造一个完全独立于真实 .env 文件的测试配置。

    关键点：``_env_file=None``
        这是 pydantic-settings 提供的特殊参数，含义是「不要读取任何 .env 文件」。
        如果不加它，测试结果就会受开发者本机上那个 .env 影响，出现「我这儿能过、
        你那儿不过」的假故障。测试必须是可重复的，所以这里显式关掉文件读取。

    关于优先级（从高到低）：
        初始化参数 > 环境变量 > .env 文件 > 字段默认值
        所以这里传入的 app_name / app_env 会覆盖机器上可能存在的同名环境变量。
    """
    return Settings(
        _env_file=None,  # 不读取 .env 文件
        app_name="测试应用",  # 故意用一个与默认值不同的名字，验证配置真的生效了
        app_env="test",
        llm_provider="mock",
        image_provider="mock",
        max_revisions=3,
    )


@pytest.fixture
def container(settings: Settings) -> ServiceContainer:
    """按测试配置装配好的服务容器。

    ServiceContainer.build 内部会根据 llm_provider / image_provider 选择具体实现，
    这里两个都是 mock，所以拿到的是 MockLLMService 与 MockImageService。
    """
    return ServiceContainer.build(settings)


@pytest.fixture
def app(settings: Settings) -> Any:
    """用测试配置构建 FastAPI 应用实例。

    注意用的是应用工厂 create_app(settings) 而不是模块级的全局 app，
    这样测试就能注入自己的配置，不会读到本机的 .env。
    """
    return create_app(settings)


@pytest_asyncio.fixture
async def client(app: Any) -> AsyncIterator[AsyncClient]:
    """提供异步 HTTP 客户端，用来在测试里请求 FastAPI 接口。

    为什么用 ASGITransport 而不是真起一个 uvicorn？
        ASGITransport 把请求直接在进程内交给 ASGI 应用函数处理，
        不监听端口、不产生真实网络流量，测试更快也更稳定。

    为什么这里必须用 @pytest_asyncio.fixture 而不是 @pytest.fixture？
        因为这是异步夹具（函数体里有 await / async with），
        pytest 需要 pytest-asyncio 插件提供的专用装饰器才能正确驱动它。

    yield 的用法：
        夹具函数在 yield 之前是「准备阶段」，yield 之后是「清理阶段」。
        这里 yield 出客户端对象给测试使用，测试结束后 async with 会自动关闭连接。

    S3 补充：为什么要手动进入 lifespan_context？
        httpx 的 ASGITransport **只转发 HTTP 请求，不执行 lifespan 钩子**。
        而 S3 的工作流服务（Graph + InMemorySaver 的组合体）正是在 lifespan
        里装配到 ``app.state`` 上的。不进入 lifespan，依赖注入就取不到服务实例。
        ``app.router.lifespan_context(app)`` 等价于「真实启动一次服务」，
        让测试环境与生产启动路径完全一致。
    """
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
            yield async_client


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """禁止测试期间发起任何真实网络连接。

    monkeypatch 是 pytest 内置的夹具，用来「临时」修改属性；
    测试结束后它会自动还原，不会污染其他测试。

    这里替换了两处底层调用：
        - socket.socket.connect      ：建立 TCP 连接时调用
        - socket.create_connection   ：高层封装（内部也会调用 connect）

    一旦有代码试图联网，就会立刻抛出 AssertionError，从而证明
    「Mock 服务不访问网络」这条验收标准确实成立。
    """

    def _blocked(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("S1 阶段的 Mock 服务不允许发起任何网络请求")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


# ---------------------------------------------------------------------------
# 工作流夹具（S2 新增）
# ---------------------------------------------------------------------------


@pytest.fixture
def workflow() -> CompiledWorkflow:
    """用 Mock 服务构建一条「编译好的工作流」。

    注意 build_workflow 是「构图函数」：LLMService / ImageService 在这里被注入，
    并在内部以闭包形式传给各个节点。节点自己从不创建服务实例。

    每个测试都会拿到全新的图 + 全新的 InMemorySaver，
    因此不同测试之间不会互相看到对方的会话（thread_id 也不会串）。
    """
    return build_workflow(
        llm_service=MockLLMService(),
        image_service=MockImageService(),
        max_revisions=3,
    )
