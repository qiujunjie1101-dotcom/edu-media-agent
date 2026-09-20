"""依赖注入：把应用级单例交给路由使用。

============================================================================
为什么用「应用状态 + 依赖函数」而不是全局变量？
============================================================================
- 全局变量在模块导入时创建：测试无法替换，多套配置会打架；
- 挂在 ``app.state`` 上的实例随应用生命周期创建/销毁，
  且每个测试可以用自己的 app 实例，互不干扰；
- 把它包成 FastAPI 依赖后，测试还能用 ``app.dependency_overrides``
  替换实现（S3 的「节点异常映射」等场景正是这么测的）。

============================================================================
为什么这里的依赖是同步函数？
============================================================================
它只做一件事：从 ``request.app.state`` 取一个已经创建好的对象，
没有任何 I/O，因此不需要 ``async def``。FastAPI 对同步依赖会在
线程池中执行，但对于这种纯取值操作，开销可以忽略。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.services.workflow_service import WorkflowService


def get_workflow_service(request: Request) -> WorkflowService:
    """取出应用生命周期内唯一的 ``WorkflowService``。

    参数:
        request: 当前请求对象。FastAPI 会把 ``request.app`` 设为
                 正在处理该请求的应用实例。

    返回:
        WorkflowService: 启动时装配好的服务（天然是同一实例，
                         不会为每个请求重新构图或重建 Checkpointer）

    异常:
        RuntimeError: 应用尚未启动（lifespan 未执行）。
            这属于「部署/启动流程出错」，不是业务错误，
            因此让它以 500 暴露出来，而不是伪装成某个业务错误码。
    """
    service = getattr(request.app.state, "workflow_service", None)
    if not isinstance(service, WorkflowService):
        raise RuntimeError(
            "WorkflowService 尚未装配：应用启动钩子（lifespan）没有执行。"
            "请通过 uvicorn / 测试夹具正常启动应用。"
        )
    return service


WorkflowServiceDep = Annotated[WorkflowService, Depends(get_workflow_service)]
"""路由里直接使用的类型别名。

写法收益：函数签名变成 ``service: WorkflowServiceDep``，
比 ``service: WorkflowService = Depends(get_workflow_service)`` 更短，
而且类型检查器能正确推断出 ``service`` 的类型（默认值写法会被推断成 WorkflowService | None）。
"""
