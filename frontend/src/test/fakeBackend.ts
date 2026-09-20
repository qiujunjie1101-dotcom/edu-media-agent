/**
 * 假后端：在测试里模拟 S3 那三个接口的状态机。
 *
 * ============================================================================
 * 为什么值得为测试写这么一小段「后端」？
 * ============================================================================
 * 前端真正需要验证的是「根据后端给的状态渲染正确的界面」。
 * 如果每个用例都手工写死一连串响应，那么：
 *   - 无法验证「选题之后必然进入审稿」这类连续流程；
 *   - 一旦真实后端的字段名变了，测试里的假数据不会跟着变，反而掩盖问题。
 *
 * 这里只实现**与前端相关的最小规则**（状态迁移、错误码、计数上限），
 * 且字段结构与取值都照抄后端：
 *   start → awaiting_topic_selection
 *   select_topic → awaiting_review（撰写初稿）
 *   revise → awaiting_review（revision_count +1，达到上限后 allowed_actions 收窄为 ['approve']）
 *   approve → completed / completed_with_warnings
 *
 * 真实接口的联调（不是替身）在验收阶段用启动的 uvicorn 完成。
 */

import type { WorkflowResponse } from '../api/types';
import type { FakeResponseInit, RecordedRequest } from './fetchMock';
import {
  errorBody,
  makeArticle,
  makeAssetsWithFailures,
  makeSuccessAssets,
  makeVisualPoints,
  topicSelectionState,
} from './fixtures';

/** 与后端 human_review.py 的 MIN_FEEDBACK_LENGTH 保持一致。 */
const MIN_FEEDBACK_LENGTH = 5;

export interface FakeBackendOptions {
  /** 允许的重写次数上限（后端默认来自 MAX_REVISIONS=3） */
  revisionLimit?: number;
  /** 通过后要标记为失败的图片要点 id，用于验证降级完成场景 */
  failedImageIds?: string[];
}

export interface FakeBackend {
  /** 预置一条已存在的会话（用于「按 thread_id 恢复」类用例） */
  seed: (state: WorkflowResponse) => WorkflowResponse;
  /** 交给 stubFetch 的处理函数 */
  handle: (request: RecordedRequest) => FakeResponseInit;
  /** 读取当前会话状态（断言用） */
  get: (threadId: string) => WorkflowResponse | undefined;
}

export function createFakeBackend(options: FakeBackendOptions = {}): FakeBackend {
  const revisionLimit = options.revisionLimit ?? 3;
  const failedImageIds = options.failedImageIds ?? [];
  const threads = new Map<string, WorkflowResponse>();
  let counter = 0;

  function seed(state: WorkflowResponse): WorkflowResponse {
    threads.set(state.thread_id, state);
    return state;
  }

  function notFound(threadId: string): FakeResponseInit {
    return {
      status: 404,
      body: errorBody(
        'THREAD_NOT_FOUND',
        '会话不存在或已过期（S3 使用内存检查点，服务重启后历史会话会丢失）',
        threadId,
      ),
    };
  }

  function handleStart(request: RecordedRequest): FakeResponseInit {
    const raw = request.body?.topic_direction;
    const direction = typeof raw === 'string' ? raw.trim() : '';

    if (direction.length < 2 || direction.length > 200) {
      return {
        status: 422,
        body: errorBody(
          'VALIDATION_ERROR',
          '请求参数校验失败：topic_direction String should have at least 2 characters',
        ),
      };
    }

    counter += 1;
    const threadId = `thread-test-${counter}`;
    const state = topicSelectionState(threadId);
    state.topic_direction = direction;
    threads.set(threadId, state);
    return { status: 201, body: state };
  }

  function handleSelectTopic(
    current: WorkflowResponse,
    threadId: string,
    request: RecordedRequest,
  ): FakeResponseInit {
    const topicId = request.body?.topic_id;
    const topic = current.generated_topics.find((item) => item.id === topicId);
    if (topic === undefined) {
      return { status: 422, body: errorBody('TOPIC_NOT_FOUND', '选题不存在', threadId) };
    }

    const limitReached = revisionLimit <= 0;
    const next: WorkflowResponse = {
      ...current,
      status: 'awaiting_review',
      selected_topic: topic,
      article_content: makeArticle(topic.title),
      review_action: null,
      review_feedback: null,
      revision_count: 0,
      pending_action: {
        type: 'article_review',
        allowed_actions: limitReached ? ['approve'] : ['approve', 'revise'],
        revision_count: 0,
        revision_limit_reached: limitReached,
      },
    };
    threads.set(threadId, next);
    return { status: 200, body: next };
  }

  function handleRevise(
    current: WorkflowResponse,
    threadId: string,
    request: RecordedRequest,
  ): FakeResponseInit {
    const raw = request.body?.feedback;
    const feedback = typeof raw === 'string' ? raw.trim() : '';

    if (feedback.length < MIN_FEEDBACK_LENGTH) {
      return {
        status: 422,
        body: errorBody(
          'VALIDATION_ERROR',
          `请求参数校验失败：feedback String should have at least ${MIN_FEEDBACK_LENGTH} characters`,
          threadId,
        ),
      };
    }

    if (current.revision_count >= revisionLimit) {
      return {
        status: 409,
        body: errorBody(
          'REVISION_LIMIT_REACHED',
          `文章已重写 ${current.revision_count} 次，达到上限 ${revisionLimit}，此时只允许 approve`,
          threadId,
        ),
      };
    }

    const revisionCount = current.revision_count + 1;
    const limitReached = revisionCount >= revisionLimit;
    const next: WorkflowResponse = {
      ...current,
      status: 'awaiting_review',
      article_content: makeArticle(current.selected_topic?.title ?? '未命名主题', feedback),
      // 已与真实后端核对：重写完成后处于「新一轮尚未审核」，
      // review_action / review_feedback 都被清空为 null
      review_action: null,
      review_feedback: null,
      revision_count: revisionCount,
      pending_action: {
        type: 'article_review',
        allowed_actions: limitReached ? ['approve'] : ['approve', 'revise'],
        revision_count: revisionCount,
        revision_limit_reached: limitReached,
      },
    };
    threads.set(threadId, next);
    return { status: 200, body: next };
  }

  function handleApprove(current: WorkflowResponse, threadId: string): FakeResponseInit {
    const hasFailures = failedImageIds.length > 0;
    const next: WorkflowResponse = {
      ...current,
      status: hasFailures ? 'completed_with_warnings' : 'completed',
      review_action: 'approve',
      review_feedback: null,
      visual_points: makeVisualPoints(),
      image_assets: hasFailures ? makeAssetsWithFailures(failedImageIds) : makeSuccessAssets(),
      pending_action: null,
      error_message: hasFailures
        ? `共 ${failedImageIds.length} 张图片生成失败：${failedImageIds.join('、')}；其余图片已正常生成`
        : null,
    };
    threads.set(threadId, next);
    return { status: 200, body: next };
  }

  function handle(request: RecordedRequest): FakeResponseInit {
    // /api/v1/workflows/start | /api/v1/workflows/<id> | /api/v1/workflows/<id>/resume
    const rest = request.path.replace(/^.*\/workflows\/?/, '');
    const segments = rest.split('/').filter((segment) => segment !== '');

    if (segments.length === 1 && segments[0] === 'start' && request.method === 'POST') {
      return handleStart(request);
    }

    const threadId = segments[0];
    if (threadId === undefined) {
      return { status: 404, body: errorBody('THREAD_NOT_FOUND', '未知路径', null) };
    }

    const current = threads.get(threadId);
    if (current === undefined) {
      return notFound(threadId);
    }

    if (request.method === 'GET' && segments.length === 1) {
      return { status: 200, body: current };
    }

    if (request.method === 'POST' && segments[1] === 'resume') {
      const action = request.body?.action;
      if (action === 'select_topic') {
        return handleSelectTopic(current, threadId, request);
      }
      if (action === 'revise') {
        return handleRevise(current, threadId, request);
      }
      if (action === 'approve') {
        return handleApprove(current, threadId);
      }
      return {
        status: 409,
        body: errorBody('ACTION_NOT_ALLOWED', '当前阶段不允许该操作', threadId),
      };
    }

    return notFound(threadId);
  }

  return {
    seed,
    handle,
    get: (threadId: string) => threads.get(threadId),
  };
}
