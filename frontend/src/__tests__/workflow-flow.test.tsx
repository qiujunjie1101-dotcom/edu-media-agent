/**
 * 完整主流程的验收用例（对应 2、3、4、5、6、8、10、13）：
 *
 *   输入方向 → 生成选题 → 选择题目 → 查看文章 → 驳回重写 → 通过 → 查看结果
 *
 * 这里用的是 fakeBackend（按真实接口契约实现的测试替身），
 * 因此断言的字段名、状态值与错误码都与后端一致。
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import App from '../App';
import { createFakeBackend } from '../test/fakeBackend';
import { articleReviewState, errorBody } from '../test/fixtures';
import { stubFetch } from '../test/fetchMock';

type User = ReturnType<typeof userEvent.setup>;

/** 渲染整个应用，并接上假后端。 */
function renderApp(backend = createFakeBackend()) {
  const { requests } = stubFetch((request) => backend.handle(request));
  const user = userEvent.setup();
  render(<App />);
  return { backend, requests, user };
}

/** 走到「等待选题」。 */
async function generateTopics(user: User, direction = 'LangGraph 检查点机制'): Promise<void> {
  await user.type(screen.getByLabelText('内容方向'), direction);
  await user.click(screen.getByRole('button', { name: /生成选题/ }));
  await screen.findByTestId('screen-topic-selection');
}

/** 走到「等待审稿」。 */
async function selectFirstTopic(user: User): Promise<void> {
  await generateTopics(user);
  await user.click(screen.getByRole('radio', { name: /先搞懂它到底解决什么问题/ }));
  await user.click(screen.getByRole('button', { name: /使用此选题/ }));
  await screen.findByTestId('screen-article-review');
}

describe('主流程', () => {
  it('生成选题后展示候选题目，并把 thread_id 写入 URL 与 localStorage', async () => {
    const { user, requests } = renderApp();

    await generateTopics(user);

    // 后端返回的三个候选都渲染出来了
    expect(screen.getByText('先搞懂它到底解决什么问题')).toBeInTheDocument();
    expect(screen.getByText('一次完整的动手实践')).toBeInTheDocument();
    expect(screen.getByText('新手最容易踩的 3 个坑')).toBeInTheDocument();
    // 角度与理由也要可见（运营人员据此判断写哪个）
    expect(screen.getByText('避坑指南')).toBeInTheDocument();
    expect(screen.getByText('适合零基础学员建立整体图景。')).toBeInTheDocument();

    // 请求体字段名必须是 topic_direction（后端契约）
    const startRequest = requests.find((item) => item.path.endsWith('/workflows/start'));
    expect(startRequest?.method).toBe('POST');
    expect(startRequest?.body).toEqual({ topic_direction: 'LangGraph 检查点机制' });

    // 会话落到了两个地方，刷新才能恢复
    expect(window.localStorage.getItem('yy_agent.thread_id')).toBe('thread-test-1');
    expect(new URLSearchParams(window.location.search).get('thread_id')).toBe('thread-test-1');
  });

  it('未选择题目时「使用此选题」保持禁用', async () => {
    const { user } = renderApp();
    await generateTopics(user);

    const confirm = screen.getByRole('button', { name: /使用此选题/ });
    expect(confirm).toBeDisabled();

    await user.click(screen.getByRole('radio', { name: /一次完整的动手实践/ }));
    expect(confirm).toBeEnabled();
  });

  it('选择题目后进入文章审核界面', async () => {
    const { user, requests } = renderApp();
    await selectFirstTopic(user);

    // 选题请求体使用后端约定的判别字段
    const resumeRequest = requests.find((item) => item.path.endsWith('/resume'));
    expect(resumeRequest?.body).toEqual({ action: 'select_topic', topic_id: 't1' });

    expect(screen.getByTestId('article-content')).toHaveTextContent('先搞懂它到底解决什么问题');
    expect(screen.getByTestId('revision-count')).toHaveTextContent('0 次');
    expect(screen.getByTestId('revision-limit')).toHaveTextContent('未达上限');
  });

  it('驳回意见少于 5 个字时不能提交', async () => {
    const { user } = renderApp();
    await selectFirstTopic(user);

    const reviseButton = screen.getByRole('button', { name: /要求修改/ });
    const feedback = screen.getByLabelText('修改意见');

    // 还没填 → 禁用
    expect(reviseButton).toBeDisabled();

    await user.type(feedback, '不行');
    expect(reviseButton).toBeDisabled();
    expect(screen.getByText(/修改意见至少需要 5 个字/)).toBeInTheDocument();

    await user.type(feedback, '，请补充代码示例');
    expect(reviseButton).toBeEnabled();
  });

  it('驳回后立即展示重写的新文章与更新后的重写次数', async () => {
    const { user } = renderApp();
    await selectFirstTopic(user);

    const feedbackText = '请补充一个最小可运行代码示例';
    await user.type(screen.getByLabelText('修改意见'), feedbackText);
    await user.click(screen.getByRole('button', { name: /要求修改/ }));

    // 重写完成后不换页：还是这一屏，但文章与计数都换了
    await waitFor(() => {
      expect(screen.getByTestId('revision-count')).toHaveTextContent('1 次');
    });
    const article = screen.getByTestId('article-content');
    // 文章现在是按 Markdown 渲染的，标题标记（##）不会出现在可见文本里
    expect(article).toHaveTextContent('修订说明');
    expect(article).toHaveTextContent(feedbackText);
    // 意见输入框已清空，避免把上一轮意见重复提交
    expect(screen.getByLabelText('修改意见')).toHaveValue('');
  });

  it('通过后展示最终文章与小红书图片资产', async () => {
    const { user } = renderApp();
    await selectFirstTopic(user);

    await user.click(screen.getByRole('button', { name: /通过文章/ }));

    expect(await screen.findByTestId('screen-result')).toBeInTheDocument();
    // 默认展示公众号文章
    expect(screen.getByTestId('final-article')).toHaveTextContent('先搞懂它到底解决什么问题');

    await user.click(screen.getByRole('tab', { name: /小红书素材/ }));

    expect(screen.getByTestId('asset-grid')).toBeInTheDocument();
    expect(screen.getByTestId('asset-card-vp1')).toBeInTheDocument();
    expect(screen.getByTestId('asset-card-vp2')).toBeInTheDocument();
    expect(screen.getByTestId('asset-card-vp3')).toBeInTheDocument();
    // 每张卡片都要能看到「第几张」与要点标题
    expect(screen.getByText('第 1 张')).toBeInTheDocument();
    expect(screen.getByText('核心结论')).toBeInTheDocument();
  });

  it('API 失败时显示可关闭的错误提示，且不丢失当前状态', async () => {
    const backend = createFakeBackend();
    let forceReviseFailure = false;

    const { requests } = stubFetch((request) => {
      if (forceReviseFailure && request.path.endsWith('/resume')) {
        return {
          status: 409,
          body: errorBody('ACTION_NOT_ALLOWED', '当前阶段不允许该操作', 'thread-test-1'),
        };
      }
      return backend.handle(request);
    });
    const user = userEvent.setup();
    render(<App />);

    await selectFirstTopic(user);

    forceReviseFailure = true;
    await user.type(screen.getByLabelText('修改意见'), '请补充一个最小可运行代码示例');
    await user.click(screen.getByRole('button', { name: /要求修改/ }));

    // 1. 出现可关闭的错误提示，文案友好且保留错误码
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('当前阶段不允许这个操作');
    expect(alert).toHaveTextContent('错误码：ACTION_NOT_ALLOWED');

    // 2. 当前状态完全没有丢失：文章还在、计数没变、仍停留在审稿界面
    expect(screen.getByTestId('screen-article-review')).toBeInTheDocument();
    expect(screen.getByTestId('article-content')).toHaveTextContent('先搞懂它到底解决什么问题');
    expect(screen.getByTestId('revision-count')).toHaveTextContent('0 次');
    expect(requests.filter((item) => item.path.endsWith('/resume'))).toHaveLength(2);

    // 3. 关掉提示后界面依然可用
    await user.click(screen.getByRole('button', { name: '关闭提示' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByTestId('article-content')).toBeInTheDocument();
  });

  it('重复提交只会发出一次请求', async () => {
    const backend = createFakeBackend();
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    // 让第一次请求一直挂在「在途」状态，模拟慢网络
    const { requests } = stubFetch(async (request) => {
      await gate;
      return backend.handle(request);
    });

    const user = userEvent.setup();
    render(<App />);

    const textarea = screen.getByLabelText('内容方向');
    await user.type(textarea, 'LangGraph 检查点机制');

    const button = screen.getByRole('button', { name: /生成选题/ });
    await user.click(button);

    // 在途期间按钮必须禁用（用户点不动）
    expect(button).toBeDisabled();

    // 绕过 disabled 直接再提交两次：同步守卫必须挡住
    const form = textarea.closest('form');
    expect(form).not.toBeNull();
    fireEvent.submit(form as HTMLFormElement);
    fireEvent.submit(form as HTMLFormElement);

    expect(requests.filter((item) => item.path.endsWith('/workflows/start'))).toHaveLength(1);
    expect(requests).toHaveLength(1);

    // 放行后流程正常继续
    await act(async () => {
      release();
    });
    expect(await screen.findByTestId('screen-topic-selection')).toBeInTheDocument();
  });

  it('重新开始会清空会话记录并回到初始界面', async () => {
    const { user } = renderApp();
    await generateTopics(user);

    await user.click(screen.getByRole('button', { name: /重新开始/ }));

    expect(screen.getByTestId('screen-direction')).toBeInTheDocument();
    expect(window.localStorage.getItem('yy_agent.thread_id')).toBeNull();
    expect(new URLSearchParams(window.location.search).get('thread_id')).toBeNull();
  });

  it('文章内容为空时给出明确说明而不是空白', async () => {
    // 构造一个「等待审稿但没有正文」的异常快照，验证界面不会白屏
    const backend = createFakeBackend();
    backend.seed(articleReviewState({ threadId: 'thread-empty-article', article: null }));

    window.history.replaceState({}, '', '/?thread_id=thread-empty-article');
    stubFetch((request) => backend.handle(request));

    render(<App />);

    expect(await screen.findByText('后端没有返回文章内容。')).toBeInTheDocument();
  });
});
