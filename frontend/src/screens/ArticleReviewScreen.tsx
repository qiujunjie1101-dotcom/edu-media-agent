/**
 * 第 3 屏：人工审核文章（对应 pending_action.type === "article_review"）。
 *
 * 版式：左侧文档阅读区 + 右侧 300px 审核操作栏（桌面）。
 * 右侧栏在窄屏（≤1023px）会自动落到文章下方，DOM 顺序天然就是「先文章、后操作」。
 *
 * ============================================================================
 * 三条不能妥协的规则
 * ============================================================================
 * 1. 只有「通过」才会进入生图链路（后端图结构保证），界面文案要把这点讲清楚；
 * 2. 达到修改上限后禁用驳回入口——判断依据是后端给的
 *    pending_action.allowed_actions 是否包含 revise，而不是前端自己数次数；
 * 3. 请求进行中锁定全部审核操作，否则用户会同时点「通过文章」和「要求修改」，
 *    发出两个互相矛盾的恢复请求。
 *
 * 关于「剩余修改」：后端响应里只有 revision_count 与 revision_limit_reached，
 * 并没有暴露 max_revisions。因此这里只陈述已知事实：
 * 已达上限时（此时上限就等于当前次数）显示具体数字，未达上限时如实写「未达上限」，
 * 绝不臆造一个上限数字。
 */

import { useEffect, useState } from 'react';
import { Check, SendHorizontal, TriangleAlert } from 'lucide-react';

import { MIN_FEEDBACK_LENGTH, type TopicCandidate } from '../api/types';
import { Button } from '../components/Button';
import { DocumentView } from '../components/DocumentView';
import { classNames } from '../components/classNames';
import { WorkArea } from '../components/WorkArea';
import type { BusyAction } from '../state/useWorkflow';

interface ArticleReviewScreenProps {
  /** 当前选题 */
  topic: TopicCandidate | null;
  /** 当前版本的文章正文（Markdown 原文） */
  article: string | null;
  /** 已重写次数（后端 revision_count） */
  revisionCount: number;
  /** 是否已达重写上限（后端 revision_limit_reached） */
  limitReached: boolean;
  /** 后端是否允许驳回（allowed_actions 是否包含 revise） */
  allowRevise: boolean;
  /** 正在进行的动作；null 表示空闲 */
  busy: BusyAction | null;
  onApprove: () => void;
  onRevise: (feedback: string) => void;
}

export function ArticleReviewScreen({
  topic,
  article,
  revisionCount,
  limitReached,
  allowRevise,
  busy,
  onApprove,
  onRevise,
}: ArticleReviewScreenProps) {
  const [feedback, setFeedback] = useState<string>('');

  // 文章换了版本（初次进入、或驳回重写完成）就清空意见输入框，
  // 否则用户很容易把上一轮的意见原样再提交一次。
  useEffect(() => {
    setFeedback('');
  }, [article, revisionCount]);

  const trimmedFeedback = feedback.trim();
  const feedbackChars = Array.from(trimmedFeedback).length;
  const feedbackTooShort = feedbackChars > 0 && feedbackChars < MIN_FEEDBACK_LENGTH;

  const busyNow = busy !== null;
  const canApprove = !busyNow;
  const canRevise = allowRevise && !busyNow && feedbackChars >= MIN_FEEDBACK_LENGTH;

  const handleRevise = (): void => {
    if (!canRevise) {
      return;
    }
    onRevise(trimmedFeedback);
  };

  return (
    <WorkArea
      title="审核文章"
      description="通过后才会提炼视觉要点并生成图片；驳回则按意见重写。"
      testId="screen-article-review"
    >
      <div className="review">
        <div className="review__doc">
          {article === null || article.trim() === '' ? (
            <p className="empty">后端没有返回文章内容。</p>
          ) : (
            <div className="doc">
              <DocumentView markdown={article} testId="article-content" />
            </div>
          )}
        </div>

        <aside className="sidecard" aria-label="审核操作">
          <div className="sidecard__block">
            <h2 className="sidecard__title">当前选题</h2>
            {topic === null ? (
              <p className="sidecard__note">后端没有返回选题信息。</p>
            ) : (
              <>
                <p className="sidecard__heading">{topic.title}</p>
                <div className="sidecard__meta">
                  <span className="badge">{topic.angle}</span>
                  <span className="mono sidecard__note">{topic.id}</span>
                </div>
              </>
            )}
          </div>

          <div className="sidecard__divider" />

          <div className="sidecard__block">
            <h2 className="sidecard__title">版本与修改</h2>

            <div className="meta-row">
              <span className="meta-row__label">当前版本</span>
              <span className="meta-row__value">第 {revisionCount + 1} 稿</span>
            </div>

            <div className="meta-row">
              <span className="meta-row__label">重写次数</span>
              <span className="meta-row__value" data-testid="revision-count">
                {revisionCount} 次
              </span>
            </div>

            <div className="meta-row">
              <span className="meta-row__label">剩余修改</span>
              <span className="meta-row__value" data-testid="revision-limit">
                {limitReached ? `已达上限（上限 ${revisionCount} 次）` : '未达上限'}
              </span>
            </div>
          </div>

          <div className="sidecard__divider" />

          <div className="sidecard__block">
            {!allowRevise ? (
              <p className="limit-warning" role="status">
                <TriangleAlert size={14} aria-hidden="true" />
                <span>已达到修改上限，修改输入与驳回按钮已禁用。</span>
              </p>
            ) : null}

            <label className="field__label" htmlFor="review-feedback">
              修改意见
            </label>

            <textarea
              id="review-feedback"
              className="textarea textarea--feedback"
              value={feedback}
              placeholder="例如：请补充一个最小可运行代码示例，并把第二节拆成两步"
              disabled={!allowRevise || busyNow}
              aria-describedby="review-feedback-hint"
              aria-invalid={feedbackTooShort}
              onChange={(event) => setFeedback(event.target.value)}
            />

            <div className="field__foot" id="review-feedback-hint">
              <span>至少 {MIN_FEEDBACK_LENGTH} 个字，写清具体要改什么</span>
              <span
                className={feedbackTooShort ? 'field__count field__count--warn' : 'field__count'}
              >
                {feedbackChars} 字
              </span>
            </div>

            {feedbackTooShort ? (
              <p className="field__error">
                修改意见至少需要 {MIN_FEEDBACK_LENGTH} 个字（当前 {feedbackChars} 个）
              </p>
            ) : null}
          </div>

          <div className="sidecard__actions">
            <Button
              variant="primary"
              block
              onClick={onApprove}
              disabled={!canApprove}
              loading={busy === 'approve'}
              icon={<Check size={16} aria-hidden="true" />}
            >
              通过文章
            </Button>

            <Button
              variant="outline"
              block
              onClick={handleRevise}
              disabled={!canRevise}
              loading={busy === 'revise'}
              icon={<SendHorizontal size={16} aria-hidden="true" />}
            >
              要求修改
            </Button>

            <p
              className={classNames(
                'sidecard__note',
                !allowRevise && 'sidecard__note--warn',
              )}
            >
              {allowRevise ? '通过后才会提炼视觉要点并生成图片。' : '已达到修改上限，本轮只能「通过」'}
            </p>
          </div>
        </aside>
      </div>
    </WorkArea>
  );
}
