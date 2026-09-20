/**
 * 验收用例 11、12：状态恢复。
 *
 *   页面刷新后，必须能只凭 thread_id 把界面恢复到原来那一屏；
 *   如果这个 thread_id 已经失效（后端重启会丢失内存检查点），
 *   必须清掉本地记录回到初始界面，而不是让用户反复刷新反复失败。
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import App from '../App';
import { createFakeBackend } from '../test/fakeBackend';
import { articleReviewState } from '../test/fixtures';
import { stubFetch } from '../test/fetchMock';

/** 只重置一次 URL，避免用例之间互相污染（setup.ts 已在每个用例前重置）。 */
function setUrlThreadId(threadId: string): void {
  window.history.replaceState({}, '', `/?thread_id=${threadId}`);
}

describe('状态恢复', () => {
  it('刷新后按 URL 里的 thread_id 恢复界面', async () => {
    const backend = createFakeBackend();
    backend.seed(articleReviewState({ threadId: 'thread-restore-1' }));
    const { requests } = stubFetch((request) => backend.handle(request));

    setUrlThreadId('thread-restore-1');
    render(<App />);

    // 先看到恢复中的加载态（不是空白页）
    expect(screen.getByTestId('screen-restoring')).toBeInTheDocument();

    // 恢复成功后直接回到「审核文章」这一屏，而不是从头开始
    expect(await screen.findByTestId('screen-article-review')).toBeInTheDocument();
    expect(screen.getByTestId('article-content')).toHaveTextContent('先搞懂它到底解决什么问题');

    // 用的是一次只读的 GET，路径里带着 thread_id
    expect(requests).toHaveLength(1);
    expect(requests[0].method).toBe('GET');
    expect(requests[0].path).toBe('/api/v1/workflows/thread-restore-1');
  });

  it('URL 没有 thread_id 时用 localStorage 恢复，并回填到地址栏', async () => {
    const backend = createFakeBackend();
    backend.seed(articleReviewState({ threadId: 'thread-from-storage' }));
    stubFetch((request) => backend.handle(request));

    window.localStorage.setItem('yy_agent.thread_id', 'thread-from-storage');
    render(<App />);

    expect(await screen.findByTestId('screen-article-review')).toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).get('thread_id')).toBe(
      'thread-from-storage',
    );
  });

  it('THREAD_NOT_FOUND 时清理失效会话并回到初始界面', async () => {
    // 后端里根本不存在这条会话
    const backend = createFakeBackend();
    stubFetch((request) => backend.handle(request));

    setUrlThreadId('ghost-thread');
    window.localStorage.setItem('yy_agent.thread_id', 'ghost-thread');
    const user = userEvent.setup();
    render(<App />);

    // 回到初始输入界面
    expect(await screen.findByTestId('screen-direction')).toBeInTheDocument();

    // 两份记录都被清理干净
    expect(window.localStorage.getItem('yy_agent.thread_id')).toBeNull();
    expect(new URLSearchParams(window.location.search).get('thread_id')).toBeNull();

    // 用中性提示说明发生了什么，而不是一个红色报错
    expect(screen.getByRole('status')).toHaveTextContent('已为你重置工作台');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    // 提示可以关掉
    await user.click(screen.getByRole('button', { name: '关闭提示' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByTestId('screen-direction')).toBeInTheDocument();
  });

  it('恢复请求失败（后端未启动）时显示可关闭错误，且保留 thread_id 供重试', async () => {
    // 模拟 fetch 直接抛错：后端没启动、端口不通
    stubFetch(() => {
      throw new Error('Failed to fetch');
    });

    setUrlThreadId('thread-offline');
    render(<App />);

    expect(await screen.findByTestId('screen-direction')).toBeInTheDocument();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('无法连接后端服务');
    expect(alert).toHaveTextContent('错误码：NETWORK_ERROR');

    // 与「会话失效」不同：这次 id 没有被清掉，用户启动后端后刷新即可重试
    expect(window.localStorage.getItem('yy_agent.thread_id')).toBe('thread-offline');
  });
});
