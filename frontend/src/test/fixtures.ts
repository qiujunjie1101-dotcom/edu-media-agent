/**
 * 测试用固定数据（fixtures）。
 *
 * 这些对象**严格按后端真实响应的字段结构**构造（字段名、可空、枚举取值都对齐
 * app/schemas/workflow.py 与 app/schemas/domain.py），内容则取自 S1–S3 的
 * MockLLMService / MockImageService 的输出形态（t1..t3、vp1..vp3、id 形式等），
 * 这样前端测试与真实联调看到的数据是同一种形状。
 */

import type {
  ImageAsset,
  TopicCandidate,
  VisualPoint,
  WorkflowResponse,
} from '../api/types';

/** 造一个候选选题。 */
export function makeTopic(partial: Partial<TopicCandidate> & { id: string }): TopicCandidate {
  return {
    title: `${partial.id} 的标题`,
    angle: '原理拆解',
    reason: `${partial.id} 的推荐理由`,
    ...partial,
  };
}

/** 三个候选选题（与 Mock LLM 的 id 规则一致）。 */
export function makeTopics(): TopicCandidate[] {
  return [
    makeTopic({
      id: 't1',
      title: '先搞懂它到底解决什么问题',
      angle: '原理拆解',
      reason: '适合零基础学员建立整体图景。',
    }),
    makeTopic({
      id: 't2',
      title: '一次完整的动手实践',
      angle: '实战演练',
      reason: '边做边学，最容易形成肌肉记忆。',
    }),
    makeTopic({
      id: 't3',
      title: '新手最容易踩的 3 个坑',
      angle: '避坑指南',
      reason: '降低首次上手时的挫败感。',
    }),
  ];
}

/** 三个视觉要点（order 从 1 连续递增，与后端约定一致）。 */
export function makeVisualPoints(): VisualPoint[] {
  return [
    {
      id: 'vp1',
      order: 1,
      title: '核心结论',
      point: '核心结论：先说清楚它解决的问题。',
      prompt: '小红书知识卡片，竖版 3:4，核心结论',
    },
    {
      id: 'vp2',
      order: 2,
      title: '关键概念',
      point: '关键概念：把三个术语解释清楚。',
      prompt: '小红书知识卡片，竖版 3:4，关键概念',
    },
    {
      id: 'vp3',
      order: 3,
      title: '动手步骤',
      point: '动手步骤：给出最小可运行示例。',
      prompt: '小红书知识卡片，竖版 3:4，动手步骤',
    },
  ];
}

/** 全部成功的图片资产。 */
export function makeSuccessAssets(): ImageAsset[] {
  return makeVisualPoints().map((point) => ({
    visual_point_id: point.id,
    status: 'success',
    url: `https://mock.local/images/${point.id}.png`,
    error: null,
  }));
}

/** 部分失败的图片资产：把指定的要点标记为 failed。 */
export function makeAssetsWithFailures(failedIds: string[]): ImageAsset[] {
  return makeVisualPoints().map((point) =>
    failedIds.includes(point.id)
      ? {
          visual_point_id: point.id,
          status: 'failed' as const,
          url: null,
          error: 'RuntimeError: 图片服务返回 500',
        }
      : {
          visual_point_id: point.id,
          status: 'success' as const,
          url: `https://mock.local/images/${point.id}.png`,
          error: null,
        },
  );
}

/** 构造一个完整的 WorkflowResponse，未指定的字段用「刚启动」的默认值填充。 */
export function makeState(partial: Partial<WorkflowResponse> = {}): WorkflowResponse {
  return {
    thread_id: 'thread-test-1',
    status: 'planning',
    topic_direction: 'LangGraph 检查点机制',
    generated_topics: [],
    selected_topic: null,
    article_content: null,
    review_action: null,
    review_feedback: null,
    visual_points: [],
    image_assets: [],
    revision_count: 0,
    error_message: null,
    pending_action: null,
    ...partial,
  };
}

/** 状态：等待人工选题（每次 start 成功后后端就是这个状态）。 */
export function topicSelectionState(threadId = 'thread-test-1'): WorkflowResponse {
  return makeState({
    thread_id: threadId,
    status: 'awaiting_topic_selection',
    generated_topics: makeTopics(),
    pending_action: { type: 'topic_selection', allowed_actions: ['select_topic'] },
  });
}

/** 一篇文章正文（结构与 Mock LLM 输出一致：Markdown 原文）。 */
export function makeArticle(heading = '先搞懂它到底解决什么问题', feedback?: string): string {
  const parts = [`# ${heading}`, ''];
  if (feedback !== undefined) {
    parts.push('## 修订说明', '', `> ${feedback}`, '');
  }
  parts.push('## 一、为什么值得先搞懂这件事', '', '正文第一段。', '');
  return parts.join('\n');
}

/** 状态：等待人工审稿。 */
export function articleReviewState(options: {
  threadId?: string;
  revisionCount?: number;
  limitReached?: boolean;
  /** 传 null 可以构造「有选题但没有正文」的异常快照 */
  article?: string | null;
} = {}): WorkflowResponse {
  const revisionCount = options.revisionCount ?? 0;
  const limitReached = options.limitReached ?? false;
  return makeState({
    thread_id: options.threadId ?? 'thread-test-1',
    status: 'awaiting_review',
    generated_topics: makeTopics(),
    selected_topic: makeTopics()[0],
    article_content: options.article === undefined ? makeArticle() : options.article,
    revision_count: revisionCount,
    // 已实测：处在「等待审稿」中断点时，后端这两个字段一定是 null
    // （上一轮的结论在新一稿生成时就已被清空，表示「本轮尚未审核」）
    review_action: null,
    review_feedback: null,
    pending_action: {
      type: 'article_review',
      allowed_actions: limitReached ? ['approve'] : ['approve', 'revise'],
      revision_count: revisionCount,
      revision_limit_reached: limitReached,
    },
  });
}

/** 状态：全部成功完成。 */
export function completedState(threadId = 'thread-test-1'): WorkflowResponse {
  return makeState({
    thread_id: threadId,
    status: 'completed',
    generated_topics: makeTopics(),
    selected_topic: makeTopics()[0],
    article_content: makeArticle(),
    review_action: 'approve',
    visual_points: makeVisualPoints(),
    image_assets: makeSuccessAssets(),
    pending_action: null,
    error_message: null,
  });
}

/** 状态：完成但部分图片失败（降级完成）。 */
export function completedWithWarningsState(
  failedIds: string[] = ['vp2'],
  threadId = 'thread-test-1',
): WorkflowResponse {
  return makeState({
    thread_id: threadId,
    status: 'completed_with_warnings',
    generated_topics: makeTopics(),
    selected_topic: makeTopics()[0],
    article_content: makeArticle(),
    review_action: 'approve',
    visual_points: makeVisualPoints(),
    image_assets: makeAssetsWithFailures(failedIds),
    pending_action: null,
    error_message: `共 ${failedIds.length} 张图片生成失败：${failedIds.join(', ')}；其余图片已正常生成`,
  });
}

/** 后端统一错误体。 */
export function errorBody(code: string, message: string, threadId: string | null = null) {
  return { detail: { code, message, thread_id: threadId } };
}
