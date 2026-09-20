"""FastAPI 应用入口。

============================================================================
当前阶段范围（S1 + S2 + S3）
============================================================================
- ``GET /health``：健康检查（S1）；
- ``/api/v1/workflows/*``：启动 / 查询 / 恢复三个工作流接口（S3）。

**故意不做的事情**：不接数据库、不做登录鉴权、不写业务历史表。
这些留给 S5（PostgreSQL Checkpointer）与 S6（业务落库）。

============================================================================
关于「应用工厂」create_app
============================================================================
为什么写成函数而不是模块级直接创建 ``app = FastAPI()``？

- 测试可以在每个用例里传入自己的配置，互不干扰；
- 将来需要多套配置（例如本地 / 测试）时，直接多调用几次即可；
- 模块底部仍然保留 ``app = create_app()``，所以
  ``uvicorn app.main:app`` 这种启动方式照旧可用。

============================================================================
关于「单例装配」——S3 的一条硬性约束
============================================================================
下面三样东西必须在应用生命周期内**各只有一份**：

    编译后的 Graph  ──▶  InMemorySaver  ──▶  WorkflowService

原因：LangGraph 的会话（thread_id）与中断状态全部存在 Checkpointer 里。
只要哪一次请求顺手重新构了一次图，InMemorySaver 就会被换成一个空的新对象，
之前所有会话的中断状态瞬间丢失，``resume`` 再也恢复不了。

因此装配动作只发生在 lifespan 里（应用启动时执行一次），
路由则通过依赖注入拿同一个实例（见 ``app/api/deps.py``）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.router import router as v1_router
from app.core.config import Settings, get_settings
from app.core.exceptions import (
    DEFAULT_HTTP_STATUS,
    ERROR_CODE_TO_HTTP_STATUS,
    WorkflowError,
)
from app.graph.builder import build_workflow
from app.services.container import ServiceContainer
from app.services.workflow_service import WorkflowService


class HealthResponse(BaseModel):
    """健康检查的响应体。

    用 Pydantic 模型声明响应结构，好处是：

    - FastAPI 会自动写进 OpenAPI 文档（/docs 页面可见）；
    - 返回值会被自动校验和序列化，字段写错会立刻暴露。
    """

    status: str
    app: str
    environment: str


# ---------------------------------------------------------------------------
# 统一错误响应
# ---------------------------------------------------------------------------


def _error_payload(code: str, message: str, thread_id: str | None) -> dict[str, object]:
    """构造统一错误响应体。

    所有错误都走这一个结构：

        {"detail": {"code": "...", "message": "...", "thread_id": "..."}}

    ``message`` 里绝不能出现堆栈、密钥、连接串或内部对象——
    未预期异常在服务层就已经被替换成固定文案了。
    """
    return {"detail": {"code": code, "message": message, "thread_id": thread_id}}


def _format_validation_message(exc: RequestValidationError) -> str:
    """把 Pydantic 的校验错误压成一句中文提示。

    为什么不把 ``exc.errors()`` 原样返回？
        它的结构对前端不友好（含 ctx、url 等冗余字段），
        而且一旦里面混入内部类型，JSON 序列化还可能直接失败。
        这里只取第一条错误的「位置 + 原因」，既够定位，又绝对安全。
    """
    errors = exc.errors()
    if not errors:
        return "请求参数校验失败"

    first = errors[0]
    # loc 形如 ("body", "topic_direction")；去掉 "body" 前缀更像人话
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    reason = str(first.get("msg", "格式不正确"))
    return f"请求参数校验失败：{location} {reason}" if location else f"请求参数校验失败：{reason}"


def _register_exception_handlers(application: FastAPI) -> None:
    """注册全局异常处理器（把内部异常翻译成统一的 HTTP 响应）。

    为什么必须集中注册？
        如果由每个端点在 ``try/except`` 里自己处理，
        就会出现「有的接口返回 500 堆栈、有的接口返回业务错误码」这种不一致。
        集中注册后，端点函数可以完全不管异常，只管写正常路径。
    """

    @application.exception_handler(WorkflowError)
    async def _handle_workflow_error(_request: Request, exc: WorkflowError) -> JSONResponse:
        """领域异常 → HTTP 状态码。

        状态码来自 ``ERROR_CODE_TO_HTTP_STATUS``：新增异常却忘了登记时，
        会落到兜底 500——宁可暴露「这里没配对」，也不要静默返回 200。
        """
        http_status = ERROR_CODE_TO_HTTP_STATUS.get(exc.code, DEFAULT_HTTP_STATUS)
        return JSONResponse(
            status_code=http_status,
            content=_error_payload(exc.code, exc.message, exc.thread_id),
        )

    @application.exception_handler(RequestValidationError)
    async def _handle_request_validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """请求体 / 查询参数校验失败 → 422 VALIDATION_ERROR。

        注意这是**第一道**防线：请求在这里就被拒绝了，
        根本不会进入服务层，因此不可能影响任何已有会话的状态。
        """
        # 路径里的 thread_id 若存在就带上，方便前端把错误挂到对应会话上
        path_params = getattr(_request, "path_params", None) or {}
        thread_id = path_params.get("thread_id")
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                "VALIDATION_ERROR",
                _format_validation_message(exc),
                str(thread_id) if thread_id is not None else None,
            ),
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建 FastAPI 应用实例。

    参数:
        settings: 可选的配置对象。不传则使用全局单例配置（``get_settings()``）。
                  测试里可以传入自定义配置，避免读取本机 .env。

    返回:
        FastAPI: 已注册好生命周期钩子、异常处理器与路由的应用实例

    """
    # 提前把配置解析出来，这样接口函数可以闭包引用它，
    # 不必等到应用启动后才能取到值。
    resolved_settings = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """应用生命周期钩子：启动时装配服务，关闭时做清理。

        语法说明:
            ``@asynccontextmanager`` 把一个「用 yield 分隔前后两段」的生成器
            变成异步上下文管理器。yield 之前的代码在应用启动时执行，
            yield 之后的代码在应用关闭时执行。

        装配顺序（每一步都只做一次）:

            1. ServiceContainer  ：按配置选好 LLM / 图片服务实现；
            2. CompiledWorkflow  ：把服务闭包注入节点，编译出图 + Checkpointer；
            3. WorkflowService   ：持有上一步的图，成为唯一的业务入口。

        为什么在启动时装配？
            服务实例应该「创建一次、全程复用」，而不是每次请求都新建；
            同时这样能在启动阶段就发现配置错误（比如 provider 写错），快速失败。
        """
        container = ServiceContainer.build(resolved_settings)
        workflow = build_workflow(
            llm_service=container.llm_service,
            image_service=container.image_service,
            max_revisions=resolved_settings.max_revisions,
        )

        _app.state.settings = resolved_settings
        _app.state.container = container
        _app.state.workflow = workflow
        _app.state.workflow_service = WorkflowService(workflow)

        # yield 代表「应用正在运行」这一段。
        # InMemorySaver 没有需要显式关闭的资源；将来接入数据库连接池时，
        # 清理逻辑写在这里（S5）。
        yield

    application = FastAPI(
        title=resolved_settings.app_name,
        version="0.3.0",
        description=(
            "自媒体内容运营 AI 智能体 —— S3 阶段："
            "工作流三个 HTTP 接口（start / get / resume），"
            "两个人工中断点，Mock 服务，内存 Checkpointer。"
        ),
        lifespan=lifespan,
    )

    _register_exception_handlers(application)

    # 挂载 v1 业务路由（/api/v1/workflows/*）。
    # 前缀与资源清单都在 app/api/v1/router.py 里集中声明。
    application.include_router(v1_router)

    # response_model 告诉 FastAPI「这个接口一定返回 HealthResponse 结构」，
    # 它会把返回值校验一遍再序列化，同时自动生成接口文档。
    @application.get(
        "/health",
        response_model=HealthResponse,
        summary="健康检查",
        tags=["system"],
    )
    async def health() -> HealthResponse:
        """返回服务健康状态。

        ``async def`` 写法让这个接口运行在事件循环里；
        将来出现耗时的 I/O 操作（调用模型、查库）时不会阻塞其他请求。
        """
        return HealthResponse(
            status="healthy",
            app=resolved_settings.app_name,
            environment=resolved_settings.app_env,
        )

    return application


# 模块级应用实例：供 `uvicorn app.main:app` 直接使用。
app = create_app()
