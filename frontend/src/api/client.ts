/**
 * 集中式 API 客户端：前端**唯一**允许发起 HTTP 请求的地方。
 *
 * ============================================================================
 * 为什么必须集中？
 * ============================================================================
 * 如果每个组件各自 fetch，会出现四个必然的问题：
 *   1. 基础地址写死在不同文件里，换环境要全局搜索；
 *   2. 错误体解析各写一套，个别地方漏解析就变成「白屏无提示」；
 *   3. 请求头、超时、编码规则不一致；
 *   4. 测试时要逐个组件去 mock，成本高且容易漏。
 *
 * 集中之后，组件只面对三个语义清晰的函数（start / get / resume），
 * 以及一个统一的 ApiError。
 *
 * ============================================================================
 * 只调用 S4 之前已经存在的接口
 * ============================================================================
 *    POST /workflows/start        → startWorkflow
 *    GET  /workflows/{thread_id}  → getWorkflow
 *    POST /workflows/{thread_id}/resume → resumeWorkflow
 * 前端不新增任何后端接口，也不推测工作流语义。
 */

import { ApiError } from './errors';
import type { ResumeRequest, WorkflowResponse } from './types';

/**
 * 后端基础地址，来自环境变量 VITE_API_BASE_URL。
 *
 * 兜底值指向本地默认端口，这样即使忘了建 .env 也能跑起来。
 * 结尾的斜杠统一去掉，避免拼出 "//workflows/start" 这种地址。
 */
export const API_BASE_URL: string = (
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'
).replace(/\/+$/, '');

/**
 * 发起请求并解析响应。
 *
 * 泛型 T 表示「期望的响应体类型」。注意这里**不做运行期结构校验**：
 * 结构正确性由后端契约保证，并由测试覆盖；
 * 前端只保证「拿不到合法响应时能给出可读错误」。
 */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const url = `${API_BASE_URL}${path}`;

  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (cause) {
    // 走到这里说明请求根本没发出去：后端没启动、端口不对、被浏览器拦截等
    throw ApiError.fromNetworkFailure(cause);
  }

  const payload = await readJson(response);

  if (!response.ok) {
    throw ApiError.fromResponse(response.status, payload);
  }

  return payload as T;
}

/** 安全地解析 JSON：即使响应不是 JSON（网关错误页）也不抛异常。 */
async function readJson(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown;
  } catch {
    return undefined;
  }
}

/** 公共请求头。后端只接受 JSON 请求体。 */
const JSON_HEADERS: Record<string, string> = { 'Content-Type': 'application/json' };

/**
 * 启动一条新会话（后端 POST /workflows/start，成功返回 201）。
 *
 * 返回的 thread_id 由**服务端**生成，前端必须原样保存用于后续查询与恢复。
 */
export async function startWorkflow(topicDirection: string): Promise<WorkflowResponse> {
  return request<WorkflowResponse>('/workflows/start', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ topic_direction: topicDirection }),
  });
}

/**
 * 查询会话最新状态（后端 GET /workflows/{thread_id}）。
 *
 * 这是纯只读操作，不会推进工作流，因此可以安全地在页面初始化、
 * 以及用户点击「刷新状态」时调用。
 */
export async function getWorkflow(threadId: string): Promise<WorkflowResponse> {
  return request<WorkflowResponse>(`/workflows/${encodeURIComponent(threadId)}`, {
    method: 'GET',
    headers: { Accept: 'application/json' },
  });
}

/**
 * 提交人工动作（后端 POST /workflows/{thread_id}/resume）。
 *
 * ``action`` 是判别字段，三种取值对应三套互不相同的字段：
 *   select_topic → topic_id
 *   approve      → 可选 comment
 *   revise       → feedback（至少 5 个字符）
 */
export async function resumeWorkflow(
  threadId: string,
  action: ResumeRequest,
): Promise<WorkflowResponse> {
  return request<WorkflowResponse>(`/workflows/${encodeURIComponent(threadId)}/resume`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(action),
  });
}
