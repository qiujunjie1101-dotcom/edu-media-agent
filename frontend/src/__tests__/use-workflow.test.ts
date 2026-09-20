/**
 * useWorkflow 状态机的单元测试。
 *
 * 这里验证的是「界面之外」的三条硬规则（在 App 级测试里不容易稳定复现）：
 *   1. 并发触发同一个动作，只允许发出一次请求（同步 ref 守卫）；
 *   2. 点了「重新开始」之后，迟到的旧响应必须被丢弃；
 *   3. 请求失败时保留当前状态，只追加错误提示。
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useWorkflow } from '../state/useWorkflow';
import { createFakeBackend } from '../test/fakeBackend';
import { articleReviewState, errorBody } from '../test/fixtures';
import { stubFetch } from '../test/fetchMock';

describe('useWorkflow', () => {
  it('并发调用 start 只会发出一次请求', async () => {
    const backend = createFakeBackend();
    const { requests } = stubFetch((request) => backend.handle(request));
    const { result } = renderHook(() => useWorkflow());

    await waitFor(() => expect(result.current.restoring).toBe(false));

    await act(async () => {
      // 模拟「双击」：两次调用之间没有任何等待，DOM 的 disabled 来不及生效
      await Promise.all([result.current.start('方向一'), result.current.start('方向二')]);
    });

    expect(requests.filter((item) => item.path.endsWith('/workflows/start'))).toHaveLength(1);
    expect(requests[0].body).toEqual({ topic_direction: '方向一' });
    expect(result.current.data?.topic_direction).toBe('方向一');
  });

  it('重新开始之后到达的旧响应会被丢弃', async () => {
    const backend = createFakeBackend();
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    stubFetch(async (request) => {
      await gate;
      return backend.handle(request);
    });

    const { result } = renderHook(() => useWorkflow());
    await waitFor(() => expect(result.current.restoring).toBe(false));

    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.start('方向');
    });

    // 请求在途时用户点了「重新开始」
    act(() => {
      result.current.restart();
    });

    await act(async () => {
      release();
      await pending;
    });

    // 迟到的响应不能把界面拉回旧会话
    expect(result.current.data).toBeNull();
    expect(result.current.threadId).toBeNull();
    expect(window.localStorage.getItem('yy_agent.thread_id')).toBeNull();
  });

  it('动作失败时保留当前状态，只追加可关闭的错误', async () => {
    const backend = createFakeBackend();
    backend.seed(articleReviewState({ threadId: 'thread-keep' }));

    let forceFailure = false;
    stubFetch((request) => {
      if (forceFailure && request.path.endsWith('/resume')) {
        return {
          status: 409,
          body: errorBody('ACTION_NOT_ALLOWED', '当前阶段不允许该操作', 'thread-keep'),
        };
      }
      return backend.handle(request);
    });

    window.localStorage.setItem('yy_agent.thread_id', 'thread-keep');
    const { result } = renderHook(() => useWorkflow());

    await waitFor(() => expect(result.current.data).not.toBeNull());

    forceFailure = true;
    await act(async () => {
      await result.current.approveArticle();
    });

    // 数据一个字都没变，只是多了一条错误
    expect(result.current.data?.article_content).not.toBeNull();
    expect(result.current.error?.code).toBe('ACTION_NOT_ALLOWED');
    expect(result.current.data?.status).toBe('awaiting_review');

    act(() => {
      result.current.dismissError();
    });
    expect(result.current.error).toBeNull();
  });

  it('恢复时收到 THREAD_NOT_FOUND 会清理本地记录并给出中性提示', async () => {
    stubFetch(() => ({
      status: 404,
      body: errorBody('THREAD_NOT_FOUND', '会话不存在或已过期', 'ghost'),
    }));
    window.localStorage.setItem('yy_agent.thread_id', 'ghost');

    const { result } = renderHook(() => useWorkflow());
    await waitFor(() => expect(result.current.restoring).toBe(false));

    expect(result.current.data).toBeNull();
    expect(result.current.notice).toContain('已失效');
    expect(result.current.error).toBeNull();
    expect(window.localStorage.getItem('yy_agent.thread_id')).toBeNull();
  });
});
