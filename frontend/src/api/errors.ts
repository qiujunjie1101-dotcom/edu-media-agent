/**
 * 统一错误对象与「后端错误体 → 前端可用错误」的翻译层。
 *
 * ============================================================================
 * 后端错误体的固定结构（app/main.py 的 _error_payload）
 * ============================================================================
 *   {
 *     "detail": {
 *       "code": "THREAD_NOT_FOUND",     // 机器可读，前端保留它用于排查
 *       "message": "……中文描述……",      // 面向人的描述
 *       "thread_id": "……" 或 null       // 出错的会话，便于定位
 *     }
 *   }
 *
 * 前端做三件事：
 *   1. 把上面这段结构解析成 ApiError（code / message / threadId / httpStatus）；
 *   2. 用**友好中文**替换掉技术味过重的文案，但绝不吞掉 code；
 *   3. 对「连不上后端」这类非 HTTP 错误也给出明确提示（否则界面只能显示空白）。
 */

/** 后端错误体里的 detail 部分。 */
interface ErrorDetailShape {
  code: string;
  message: string;
  thread_id?: string | null;
}

/**
 * 前端补充的友好文案。
 *
 * 为什么还要在前端再写一份？
 *   后端文案面向「排查问题」，偏精确（例如「当前中断不接受该动作」）；
 *   前端文案面向「运营人员下一步该怎么做」。两者受众不同，都要有。
 *   若某个错误码不在这张表里，就退回后端原文，绝不凭空编造。
 *
 * 注意：这里**只改文案，不改错误码**，排查时仍然以 code 为准。
 */
const FRIENDLY_MESSAGES: Record<string, string> = {
  NETWORK_ERROR: '无法连接后端服务，请确认后端已启动（默认 http://localhost:8000）。',
  THREAD_NOT_FOUND: '该会话不存在或已过期（后端重启后内存中的会话会丢失），已为你重置。',
  WORKFLOW_NOT_INTERRUPTED: '当前流程不处于等待人工操作的阶段，请刷新状态后再试。',
  ACTION_NOT_ALLOWED: '当前阶段不允许这个操作，请刷新状态后再试。',
  REVISION_LIMIT_REACHED: '已达到修改上限，此时只能选择「通过」。',
  TOPIC_NOT_FOUND: '所选题目已不在候选列表中，请重新选择。',
  CONTENT_VALIDATION_ERROR: '生成的内容不符合要求，请稍后重试或调整内容方向。',
  IMAGE_GENERATION_FAILED: '图片全部生成失败，请稍后重试。',
  LLM_UNAVAILABLE: '文本模型暂时不可用，请稍后重试。',
  INTERNAL_ERROR: '服务内部错误，请稍后重试。',
  UNKNOWN_ERROR: '请求失败，请稍后重试。',
};

/** 连不上后端时使用的错误码（不是后端返回的，是前端自造的）。 */
export const NETWORK_ERROR_CODE = 'NETWORK_ERROR';
/** 响应体结构无法识别时使用的兜底错误码。 */
export const UNKNOWN_ERROR_CODE = 'UNKNOWN_ERROR';
/** 会话不存在：界面据此清理本地记录并回到初始界面。 */
export const THREAD_NOT_FOUND_CODE = 'THREAD_NOT_FOUND';

/** 把 code + 后端原文翻译成一句给运营人员看的中文。 */
function resolveMessage(code: string, backendMessage: string | null): string {
  const friendly = FRIENDLY_MESSAGES[code];
  if (friendly) {
    return friendly;
  }
  // 没有预设文案时，优先使用后端的中文描述；再没有才用带错误码的兜底句
  return backendMessage ?? `请求失败（错误码 ${code}）`;
}

/** 前端统一的错误类型。 */
export class ApiError extends Error {
  /** 机器可读错误码，界面上会原样展示，便于排查 */
  readonly code: string;
  /** 后端返回的原始描述，调试时可用 */
  readonly backendMessage: string | null;
  /** 出错时所属的会话标识 */
  readonly threadId: string | null;
  /** HTTP 状态码；网络层失败时为 0 */
  readonly httpStatus: number;

  constructor(
    code: string,
    message: string,
    options: { backendMessage?: string | null; threadId?: string | null; httpStatus?: number } = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.backendMessage = options.backendMessage ?? null;
    this.threadId = options.threadId ?? null;
    this.httpStatus = options.httpStatus ?? 0;
  }

  /**
   * 从「HTTP 状态码 + 已解析的响应体」构造错误。
   *
   * 兼容性策略：后端错误体结构是契约的一部分，但**网络中间层**（代理、网关）
   * 可能返回完全不同的结构（例如纯文本 502）。这种情况不能崩，
   * 也不能显示空白，而是退化成 UNKNOWN_ERROR 并带上状态码。
   */
  static fromResponse(httpStatus: number, payload: unknown): ApiError {
    const detail = extractDetail(payload);
    if (detail === null) {
      return new ApiError(
        UNKNOWN_ERROR_CODE,
        resolveMessage(UNKNOWN_ERROR_CODE, `请求失败（HTTP ${httpStatus}）。`),
        { httpStatus },
      );
    }
    return new ApiError(detail.code, resolveMessage(detail.code, detail.message), {
      backendMessage: detail.message,
      threadId: detail.thread_id ?? null,
      httpStatus,
    });
  }

  /** fetch 本身失败（后端没启动、端口不通、被浏览器拦截）时使用。 */
  static fromNetworkFailure(cause: unknown): ApiError {
    const detail = cause instanceof Error && cause.message ? `（${cause.message}）` : '';
    return new ApiError(NETWORK_ERROR_CODE, resolveMessage(NETWORK_ERROR_CODE, null) + detail, {
      httpStatus: 0,
    });
  }
}

/**
 * 校验并取出 ``{detail: {code, message, thread_id}}``。
 *
 * 为什么逐字段判断而不是直接类型断言？
 *   断言只是「骗过编译器」，运行时该崩还是崩。这里做真实的存在性检查，
 *   结构不符就返回 null，由调用方走兜底分支。
 */
function extractDetail(payload: unknown): ErrorDetailShape | null {
  if (typeof payload !== 'object' || payload === null) {
    return null;
  }
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail !== 'object' || detail === null) {
    return null;
  }
  const candidate = detail as Record<string, unknown>;
  if (typeof candidate.code !== 'string' || typeof candidate.message !== 'string') {
    return null;
  }
  const threadId = candidate.thread_id;
  return {
    code: candidate.code,
    message: candidate.message,
    thread_id: typeof threadId === 'string' ? threadId : null,
  };
}

/** 任意异常 → ApiError。组件里统一用它，避免到处写 instanceof。 */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  if (error instanceof Error) {
    return new ApiError(UNKNOWN_ERROR_CODE, resolveMessage(UNKNOWN_ERROR_CODE, error.message), {
      backendMessage: error.message,
    });
  }
  return new ApiError(UNKNOWN_ERROR_CODE, resolveMessage(UNKNOWN_ERROR_CODE, null));
}

/** 是否为「会话不存在」——界面据此清理本地记录并回到初始界面。 */
export function isThreadNotFound(error: unknown): boolean {
  return toApiError(error).code === THREAD_NOT_FOUND_CODE;
}
