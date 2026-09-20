"""工作流会话的三个端点（S3）。

============================================================================
职责边界
============================================================================
本文件里没有一行业务规则，也没有一行 LangGraph 代码。每个端点只有三步：

    1. 让 FastAPI 完成请求体校验（不合法 → 422，请求根本到不了这里）
    2. 把参数交给 WorkflowService
    3. 返回服务给的 WorkflowResponse

「恢复前必须校验什么」「非法请求怎么处理」这类问题全部由
``app/services/workflow_service.py`` 回答——端点不是判断的地方，
判断写在端点里就会出现「这个端点记得校验、那个端点忘了」的漏洞。
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import WorkflowServiceDep
from app.schemas.workflow import (
    ErrorResponse,
    ResumeRequest,
    WorkflowResponse,
    WorkflowStartRequest,
)

router = APIRouter(tags=["workflows"])

# 错误响应声明：只用于让 OpenAPI 文档（/docs）把错误结构展示清楚。
# 真正的错误响应由 app/main.py 里的全局异常处理器统一构造，走同一份结构。
_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse, "description": "会话不存在"},
    409: {"model": ErrorResponse, "description": "当前状态不允许该操作"},
    422: {"model": ErrorResponse, "description": "入参或业务校验失败"},
    502: {"model": ErrorResponse, "description": "内容/图片生成失败"},
    503: {"model": ErrorResponse, "description": "文本模型上游不可用"},
    500: {"model": ErrorResponse, "description": "服务内部错误"},
}


@router.post(
    "/workflows/start",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkflowResponse,
    summary="启动内容生产工作流",
    description=(
        "根据内容方向启动一条新会话，自动生成候选选题，"
        "并在「人工选题」中断点暂停。返回的 thread_id 用于后续查询与恢复。"
    ),
    responses=_ERROR_RESPONSES,
)
async def start_workflow(
    payload: WorkflowStartRequest,
    service: WorkflowServiceDep,
) -> WorkflowResponse:
    """启动工作流并停在人工选题中断。

    为什么返回 201 而不是 200？
        这个请求**创建了一个新资源**（一条会话），语义上属于 Created；
        而下面的 resume 是在已有资源上推进状态，用 200 更贴切。
    """
    return await service.start(payload.topic_direction)


@router.get(
    "/workflows/{thread_id}",
    response_model=WorkflowResponse,
    summary="查询会话状态",
    description=(
        "返回该会话的最新状态与待办动作（pending_action）。"
        "pending_action 为 null 表示当前没有人工中断。"
    ),
    responses=_ERROR_RESPONSES,
)
async def get_workflow(
    thread_id: str,
    service: WorkflowServiceDep,
) -> WorkflowResponse:
    """查询会话状态。

    ``thread_id`` 直接从路径取原始字符串，不做格式校验：
    非法格式的结果就是「找不到」→ 404，这比 422 更符合 REST 语义
    （路径里的资源标识格式不对，本质就是该资源不存在）。
    """
    return await service.get_state(thread_id)


@router.post(
    "/workflows/{thread_id}/resume",
    response_model=WorkflowResponse,
    summary="恢复工作流（选题 / 通过 / 驳回）",
    description=(
        "提交人工动作把流程推进到下一个中断点或结束。"
        "请求体使用 action 作为判别字段：select_topic / approve / revise。"
    ),
    responses=_ERROR_RESPONSES,
)
async def resume_workflow(
    thread_id: str,
    payload: ResumeRequest,
    service: WorkflowServiceDep,
) -> WorkflowResponse:
    """提交人工动作并返回推进后的状态。

    三种动作的合法中断点不同，服务层会做强制校验：
    校验不通过时**不会调用 Graph**，原会话保持可用。
    """
    return await service.resume(thread_id, payload)
