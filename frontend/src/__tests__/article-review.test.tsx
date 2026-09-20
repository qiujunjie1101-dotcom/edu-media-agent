/**
 * 验收用例 5、7：审稿界面的边界条件。
 *
 *   - 达到重写上限时，修改输入与驳回按钮必须同时禁用（依据后端的 allowed_actions）
 *   - 请求在途时，两个操作按钮必须同时禁用（避免「通过」与「要求修改」互相矛盾）
 *
 * 这两条都是「界面必须守住」的规则：后端会独立再校验一遍，
 * 但界面不应该给用户制造一次注定失败的操作。
 */

import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import App from '../App';
import type { WorkflowResponse } from '../api/types';
import { createFakeBackend } from '../test/fakeBackend';
import { articleReviewState } from '../test/fixtures';
import { stubFetch } from '../test/fetchMock';

/** 用指定快照直接进入某条会话（模拟「刷新后恢复」）。 */
function renderRestored(state: WorkflowResponse) {
  const backend = createFakeBackend();
  backend.seed(state);
  window.history.replaceState({}, '', `/?thread_id=${state.thread_id}`);
  const { requests } = stubFetch((request) => backend.handle(request));
  const user = userEvent.setup();
  render(<App />);
  return { backend, requests, user };
}

describe('审稿界面', () => {
  it('达到修改上限时禁止驳回，只允许通过', async () => {
    const state = articleReviewState({
      threadId: 'thread-limit',
      revisionCount: 3,
      limitReached: true,
      // 后端在达到上限时会返回 allowed_actions = ['approve']
    });

    const { user, requests } = renderRestored(state);

    await screen.findByTestId('screen-article-review');

    // 计数与上限都要能看见，且不能凭空编造数字
    expect(screen.getByTestId('revision-count')).toHaveTextContent('3 次');
    expect(screen.getByTestId('revision-limit')).toHaveTextContent('已达上限（上限 3 次）');

    // 驳回入口整体禁用
    expect(screen.getByRole('button', { name: /要求修改/ })).toBeDisabled();
    expect(screen.getByLabelText('修改意见')).toBeDisabled();
    expect(screen.getByText('已达到修改上限，修改输入与驳回按钮已禁用。')).toBeInTheDocument();
    expect(screen.getByText('已达到修改上限，本轮只能「通过」')).toBeInTheDocument();

    // 通过仍然可用
    const approve = screen.getByRole('button', { name: /通过文章/ });
    expect(approve).toBeEnabled();
    await user.click(approve);

    expect(await screen.findByTestId('screen-result')).toBeInTheDocument();
    // 只发出了一次 resume 请求，且动作是 approve
    const resumes = requests.filter((item) => item.path.endsWith('/resume'));
    expect(resumes).toHaveLength(1);
    expect(resumes[0].body).toEqual({ action: 'approve' });
  });

  it('请求在途时两个操作按钮同时禁用', async () => {
    const state = articleReviewState({ threadId: 'thread-slow' });
    const backend = createFakeBackend();
    backend.seed(state);

    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    stubFetch(async (request) => {
      // 只让 resume 变慢，GET 保持即时返回，避免界面卡在加载态
      if (request.path.endsWith('/resume')) {
        await gate;
      }
      return backend.handle(request);
    });

    window.history.replaceState({}, '', '/?thread_id=thread-slow');
    const user = userEvent.setup();
    render(<App />);

    const approve = await screen.findByRole('button', { name: /通过文章/ });
    const feedback = screen.getByLabelText('修改意见');
    await user.type(feedback, '请补充一个最小可运行代码示例');
    const revise = screen.getByRole('button', { name: /要求修改/ });
    expect(revise).toBeEnabled();

    await user.click(approve);

    // 在途：两个按钮都禁用，输入框也锁定
    expect(approve).toBeDisabled();
    expect(revise).toBeDisabled();
    expect(feedback).toBeDisabled();

    await act(async () => {
      release();
    });
    expect(await screen.findByTestId('screen-result')).toBeInTheDocument();
  });
});
