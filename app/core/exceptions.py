"""统一领域异常。

============================================================================
为什么需要「领域异常」？
============================================================================
如果节点里直接抛 ``ValueError`` / ``KeyError``，上层就无法区分
「这是业务规则不允许」还是「代码写错了」。定义一组专用异常后：

- 节点只管抛出语义明确的异常；
- 应用服务层（S3）只需按类型映射成 HTTP 错误码，不必猜；
- 测试可以精确断言 ``pytest.raises(TopicNotFoundError)``。

============================================================================
S2 的异常处理原则
============================================================================
1. 节点内**不捕获**异常，直接向上抛；
2. 异常会让本次图运行失败，检查点里保留的是**最后一个有效状态**
   （失败的那一步不会被写入），因此 ``GET 状态`` 仍能看到中断时的样子；
3. S2 不使用 ``aupdate_state`` 去补写 failed 状态——那是 S3 的事。
"""

from __future__ import annotations


class WorkflowError(Exception):
    """所有领域异常的基类。

    统一继承自它，S3 阶段就可以用一个 ``except WorkflowError`` 兜住全部业务异常，
    再根据 ``code`` 决定返回哪个 HTTP 状态码。

    属性:
        code: 机器可读的错误码（大写下划线风格），供接口层映射使用
        message: 面向人的错误描述
        thread_id: 出错时所属的会话标识；``start`` 之外的场景都应带上，
            便于前端定位是哪个会话出了问题。

    """

    code: str = "WORKFLOW_ERROR"

    def __init__(self, message: str, *, thread_id: str | None = None) -> None:
        # 调用父类构造，让 str(exc) 与日志里的内容都带上这条消息
        super().__init__(message)
        self.message = message
        self.thread_id = thread_id


class TopicNotFoundError(WorkflowError):
    """人工选择的 topic_id 不在候选选题中。"""

    code = "TOPIC_NOT_FOUND"


class ActionNotAllowedError(WorkflowError):
    """当前中断点不接受该动作（例如待选题时提交 approve，或路由读到未知动作）。"""

    code = "ACTION_NOT_ALLOWED"


class RevisionLimitReachedError(WorkflowError):
    """驳回次数已达上限，仍然收到 revise。此时只允许 approve。"""

    code = "REVISION_LIMIT_REACHED"


class ContentValidationError(WorkflowError):
    """内容不满足业务规则（例如修改意见过短、文章内容为空）。"""

    code = "CONTENT_VALIDATION_ERROR"


class ImageGenerationFailedError(WorkflowError):
    """全部图片生成失败——部分失败属于可降级场景，不抛此异常。"""

    code = "IMAGE_GENERATION_FAILED"


# ---------------------------------------------------------------------------
# S3 新增：接口层特有的三类异常
# ---------------------------------------------------------------------------


class ThreadNotFoundError(WorkflowError):
    """查询 / 恢复一个从未存在过的 thread_id。

    S3 只依赖内存 Checkpointer，进程重启即丢失会话，因此「不存在」是常态而非异常路径。
    """

    code = "THREAD_NOT_FOUND"


class WorkflowNotInterruptedError(WorkflowError):
    """当前会话不处于人工中断点（流程正在运行、或已经跑到 END）。

    这是 S1–S3 的「幂等守卫」：重复提交同一动作时，第二次必然落到这里，
    从而把重复请求挡在图之外。
    """

    code = "WORKFLOW_NOT_INTERRUPTED"


class LLMUnavailableError(WorkflowError):
    """文本模型上游不可用（网络失败、限流、服务 5xx 等）。

    注意：它属于「可重试」的临时故障，因此映射为 503 而不是 500。
    """

    code = "LLM_UNAVAILABLE"


class InternalError(WorkflowError):
    """未预期异常的统一出口。

    设计要点：**只对外暴露这句话，不暴露原始异常**。
    真实原因通过 ``raise ... from exc`` 保留在服务端日志里，
    绝不写进 HTTP 响应体（否则会泄露堆栈、连接串、密钥等内部信息）。
    """

    code = "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# 错误码 → HTTP 状态码映射表
# ---------------------------------------------------------------------------
# 为什么把映射表放在异常定义旁边？
#   领域异常是「业务语言」，HTTP 状态码是「传输层语言」。两者都是接口契约的一部分，
#   放在一起才能一眼看出「新增异常时忘记了配状态码」。
#
# 为什么用「错误码」而不是「异常类」做键？
#   节点抛出的异常与接口层抛出的异常可能来自不同模块；用稳定的字符串错误码做键，
#   映射表就不依赖具体的类对象，也不会因为类被移动而失效。
ERROR_CODE_TO_HTTP_STATUS: dict[str, int] = {
    # 入参不满足 Pydantic 约束（由接口层的请求体校验产生）
    "VALIDATION_ERROR": 422,
    # 业务语义上的非法输入
    "TOPIC_NOT_FOUND": 422,
    # 会话不存在
    "THREAD_NOT_FOUND": 404,
    # 状态机不允许（不处于中断点 / 动作不匹配 / 驳回超限）
    "WORKFLOW_NOT_INTERRUPTED": 409,
    "ACTION_NOT_ALLOWED": 409,
    "REVISION_LIMIT_REACHED": 409,
    # 上游/生成结果不可用
    "CONTENT_VALIDATION_ERROR": 502,
    "IMAGE_GENERATION_FAILED": 502,
    "LLM_UNAVAILABLE": 503,
    # 兜底
    "INTERNAL_ERROR": 500,
}

DEFAULT_HTTP_STATUS = 500
"""映射表里查不到错误码时的兜底状态码。

宁可返回 500 也不要静默返回 200：未知错误码意味着「有人新增异常却忘了登记」，
让它显式暴露出来，比偷偷放行安全得多。
"""
