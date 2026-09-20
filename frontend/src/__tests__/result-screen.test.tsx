/**
 * 验收用例 8、9 以及「其他状态」：
 *   - 通过后同时能看到公众号文章与小红书素材
 *   - 部分图片失败时展示失败信息（含失败原因与对应的 visual_point_id）
 *   - 图片元素加载失败不破坏布局
 *   - failed / 处理中 / 未知状态都必须有明确界面，不出现空白页
 */

import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import App from '../App';
import type { WorkflowResponse } from '../api/types';
import { createFakeBackend } from '../test/fakeBackend';
import {
  articleReviewState,
  completedState,
  completedWithWarningsState,
  makeState,
} from '../test/fixtures';
import { stubFetch } from '../test/fetchMock';

/** 用指定快照直接进入某条会话（模拟「刷新后恢复」）。 */
function renderRestored(state: WorkflowResponse) {
  const backend = createFakeBackend();
  backend.seed(state);
  window.history.replaceState({}, '', `/?thread_id=${state.thread_id}`);
  stubFetch((request) => backend.handle(request));
  const user = userEvent.setup();
  render(<App />);
  return { backend, user };
}

describe('最终结果', () => {
  it('全部成功时展示公众号文章与 3 张小红书卡片', async () => {
    const { user } = renderRestored(completedState('thread-done'));

    expect(await screen.findByTestId('screen-result')).toBeInTheDocument();
    expect(await screen.findByTestId('final-article')).toHaveTextContent('先搞懂它到底解决什么问题');

    await user.click(screen.getByRole('tab', { name: /小红书素材/ }));

    const cards = screen.getAllByRole('article');
    expect(cards).toHaveLength(3);
    expect(screen.getByText(/成功 3/)).toBeInTheDocument();
    expect(screen.queryByText(/失败 \d/)).not.toBeInTheDocument();

    // 每张图都有可读的替代文本，且包在固定比例的容器里（3:4 由 CSS 保证）
    const image = screen.getByAltText(/视觉要点 1：核心结论/);
    expect(image).toBeInTheDocument();
    expect(image.closest('.asset-card__media')).not.toBeNull();

    // 图片地址完全来自后端，前端不拼接、不伪造
    expect(image).toHaveAttribute('src', 'https://mock.local/images/vp1.png');
  });

  it('部分图片失败时展示失败占位、失败原因与对应的 visual_point_id', async () => {
    const { user } = renderRestored(completedWithWarningsState(['vp2'], 'thread-warn'));

    expect(await screen.findByTestId('screen-result')).toBeInTheDocument();

    // 顶部是非阻塞警告，说明有多少张失败
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('共 1 张图片生成失败：vp2；其余图片已正常生成');

    await user.click(screen.getByRole('tab', { name: /小红书素材/ }));

    // 失败卡片：占位 + 失败原因 + 要点 ID
    const failedCard = screen.getByTestId('asset-card-vp2');
    expect(failedCard).toHaveTextContent('图片生成失败');
    expect(failedCard).toHaveTextContent('失败原因：RuntimeError: 图片服务返回 500');
    expect(failedCard).toHaveTextContent('要点 ID：vp2');
    expect(screen.getByText(/失败 1/)).toBeInTheDocument();

    // 成功的那两张仍然正常展示图片
    expect(screen.getByAltText(/视觉要点 1：核心结论/)).toBeInTheDocument();
    expect(screen.getByAltText(/视觉要点 3：动手步骤/)).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(3);
  });

  it('图片元素加载失败时回落到灰阶占位，且不影响其它卡片布局', async () => {
    const { user } = renderRestored(completedState('thread-broken-image'));
    await screen.findByTestId('screen-result');
    await user.click(screen.getByRole('tab', { name: /小红书素材/ }));

    const image = screen.getByAltText(/视觉要点 1：核心结论/);
    // jsdom 不会真的去下载图片，这里手动触发 onError，等价于浏览器加载失败的路径
    fireEvent.error(image);

    // 渲染层失败（地址不可达）不展示技术性文案，统一回落到灰阶预览位。
    // 注意与「图片生成失败」区分：后者是后端明确返回的业务结果，仍要显示文案。
    expect(screen.getByTestId('asset-placeholder-vp1')).toBeInTheDocument();
    expect(screen.queryByText(/图片无法加载/)).not.toBeInTheDocument();
    // 关键：容器比例由 CSS 决定，卡片数量与结构完全不变
    expect(screen.getAllByRole('article')).toHaveLength(3);
    expect(screen.getByTestId('asset-grid')).toBeInTheDocument();
  });

  it('复制文章：写入剪贴板并给出非阻塞的短暂反馈', async () => {
    const { user } = renderRestored(completedState('thread-copy'));
    await screen.findByTestId('screen-result');

    // 在点击前安装剪贴板替身（组件在点击时才读取 navigator.clipboard）
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });

    await user.click(screen.getByRole('button', { name: /复制文章/ }));

    expect(writeText).toHaveBeenCalledTimes(1);
    // 复制的是后端返回的 Markdown 原文，而不是渲染后的可见文本
    expect(writeText.mock.calls[0][0]).toContain('# 先搞懂它到底解决什么问题');

    // 反馈是页内一行字，不是阻塞式弹窗
    expect(await screen.findByText('已复制')).toBeInTheDocument();
    expect(screen.getByTestId('final-article')).toBeInTheDocument();
  });
});

describe('其他状态', () => {
  it('status=failed 时展示错误信息与重新开始按钮', async () => {
    const { user } = renderRestored(
      makeState({
        thread_id: 'thread-failed',
        status: 'failed',
        error_message: '图片全部生成失败，无法继续。',
      }),
    );

    expect(await screen.findByTestId('screen-failed')).toBeInTheDocument();
    expect(screen.getByText('图片全部生成失败，无法继续。')).toBeInTheDocument();

    // 顶栏也有一个「重新开始」，这里只针对失败界面内部的按钮
    const failureScreen = within(screen.getByTestId('screen-failed'));
    await user.click(failureScreen.getByRole('button', { name: /重新开始/ }));
    expect(screen.getByTestId('screen-direction')).toBeInTheDocument();
    expect(window.localStorage.getItem('yy_agent.thread_id')).toBeNull();
  });

  it('pending_action 为 null 且尚未完成时显示处理中状态', async () => {
    renderRestored(
      makeState({
        thread_id: 'thread-running',
        status: 'generating_images',
        pending_action: null,
      }),
    );

    const processing = within(await screen.findByTestId('screen-processing'));
    expect(processing.getByText('处理中')).toBeInTheDocument();
    // 状态中文名会出现在标题与状态标签两处，因此用 getAllByText
    expect(processing.getAllByText('正在生成图片')).toHaveLength(2);
    expect(processing.getByRole('button', { name: /刷新状态/ })).toBeInTheDocument();
  });

  it('未知状态显示明确异常与原样字段，而不是空白页', async () => {
    renderRestored(
      makeState({
        thread_id: 'thread-weird',
        status: 'paused_by_system',
        pending_action: null,
      }),
    );

    const unknown = within(await screen.findByTestId('screen-unknown'));
    expect(unknown.getByText('paused_by_system')).toBeInTheDocument();
    expect(unknown.getByRole('button', { name: /刷新状态/ })).toBeInTheDocument();
    expect(unknown.getByRole('button', { name: /重新开始/ })).toBeInTheDocument();
  });

  it('审稿状态但后端未给中断载荷时不假装可操作', async () => {
    // status 说在等审稿，但 pending_action 是 null（不一致的快照）：
    // 界面按「处理中」处理，而不是猜出审核界面
    renderRestored(
      makeState({
        thread_id: 'thread-inconsistent',
        status: 'awaiting_review',
        article_content: articleReviewState().article_content,
        pending_action: null,
      }),
    );

    expect(await screen.findByTestId('screen-processing')).toBeInTheDocument();
    expect(screen.queryByTestId('screen-article-review')).not.toBeInTheDocument();
  });
});
