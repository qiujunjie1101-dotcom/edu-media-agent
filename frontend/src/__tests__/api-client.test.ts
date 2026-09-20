/**
 * API 客户端的单元测试：请求形状与错误解析。
 *
 * 这一层是前端唯一与后端「说话」的地方，因此它的正确性必须单独验证：
 *   - 三个函数的路径、方法、请求体字段名是否与后端契约一致；
 *   - 后端统一错误体 {detail: {code, message, thread_id}} 是否被正确解析；
 *   - 结构不符（网关错误页）或网络失败时，是否能给出可读错误而不是崩掉。
 */

import { describe, expect, it } from 'vitest';

import { getWorkflow, resumeWorkflow, startWorkflow } from '../api/client';
import { ApiError, toApiError } from '../api/errors';
import { errorBody, topicSelectionState } from '../test/fixtures';
import { stubFetch } from '../test/fetchMock';

describe('API 客户端', () => {
  it('start 把内容方向放在 topic_direction 字段里', async () => {
    const { requests } = stubFetch(() => ({ status: 201, body: topicSelectionState() }));

    const result = await startWorkflow('LangGraph 检查点机制');

    expect(result.thread_id).toBe('thread-test-1');
    expect(requests[0].method).toBe('POST');
    expect(requests[0].path).toBe('/api/v1/workflows/start');
    expect(requests[0].body).toEqual({ topic_direction: 'LangGraph 检查点机制' });
  });

  it('get 用 GET 且把 thread_id 做 URL 编码', async () => {
    const { requests } = stubFetch(() => ({ status: 200, body: topicSelectionState() }));

    await getWorkflow('a b/c');

    expect(requests[0].method).toBe('GET');
    expect(requests[0].path).toBe('/api/v1/workflows/a%20b%2Fc');
  });

  it('resume 发送判别字段 action', async () => {
    const { requests } = stubFetch(() => ({ status: 200, body: topicSelectionState() }));

    await resumeWorkflow('thread-1', { action: 'select_topic', topic_id: 't1' });
    await resumeWorkflow('thread-1', { action: 'approve' });
    await resumeWorkflow('thread-1', { action: 'revise', feedback: '请补充示例代码' });

    expect(requests.map((item) => item.path)).toEqual([
      '/api/v1/workflows/thread-1/resume',
      '/api/v1/workflows/thread-1/resume',
      '/api/v1/workflows/thread-1/resume',
    ]);
    expect(requests[0].body).toEqual({ action: 'select_topic', topic_id: 't1' });
    expect(requests[1].body).toEqual({ action: 'approve' });
    expect(requests[2].body).toEqual({ action: 'revise', feedback: '请补充示例代码' });
  });

  it('解析后端统一错误体，保留 code 与 thread_id', async () => {
    stubFetch(() => ({
      status: 404,
      body: errorBody('THREAD_NOT_FOUND', '会话不存在或已过期', 'thread-x'),
    }));

    const error = await getWorkflow('thread-x').catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.code).toBe('THREAD_NOT_FOUND');
    expect(apiError.threadId).toBe('thread-x');
    expect(apiError.httpStatus).toBe(404);
    // 面向人的文案被替换成更好懂的一句，原始描述仍然保留
    expect(apiError.message).toContain('已为你重置');
    expect(apiError.backendMessage).toBe('会话不存在或已过期');
  });

  it('响应体结构不符时退化为 UNKNOWN_ERROR，而不是抛类型错误', async () => {
    stubFetch(() => ({ status: 502, body: '<html>Bad Gateway</html>' }));

    const error = (await getWorkflow('thread-1').catch((caught: unknown) => caught)) as ApiError;

    expect(error.code).toBe('UNKNOWN_ERROR');
    expect(error.httpStatus).toBe(502);
    expect(error.message).toContain('请求失败');
  });

  it('网络层失败时给出 NETWORK_ERROR 与可操作的提示', async () => {
    stubFetch(() => {
      throw new TypeError('Failed to fetch');
    });

    const error = (await startWorkflow('方向').catch((caught: unknown) => caught)) as ApiError;

    expect(error.code).toBe('NETWORK_ERROR');
    expect(error.httpStatus).toBe(0);
    expect(error.message).toContain('无法连接后端服务');
    expect(error.message).toContain('Failed to fetch');
  });

  it('toApiError 能把任意异常归一成 ApiError', () => {
    expect(toApiError(new Error('boom')).code).toBe('UNKNOWN_ERROR');
    expect(toApiError('字符串').code).toBe('UNKNOWN_ERROR');

    const original = new ApiError('VALIDATION_ERROR', '参数不合法');
    expect(toApiError(original)).toBe(original);
  });
});
