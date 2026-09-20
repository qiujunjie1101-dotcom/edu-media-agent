/**
 * 步骤导航：桌面为窄竖排侧栏，窄屏自动变为横向紧凑步骤条。
 *
 * 判定「第几步」的逻辑集中在 resolveStepIndex 里（纯函数，可单测），
 * 本组件只负责把这个数字渲染成三种视觉状态：
 *
 *   done    —— 极浅黑底 + 勾。勾选走 pop 动画（轻微回弹），并按序号错开，
 *              形成从左到右依次打勾的节奏；
 *   current —— 当前步骤的线性图标转为近黑，外圈一道极淡的描边 + halo 脉冲。
 *              强调刻意做得很轻：它只需要「和别的不一样」，不需要抢戏；
 *   todo    —— 浅灰线性图标。
 *
 * 图标一律是 1.75 描边的线性风格（lucide），不用实心图标，
 * 与整体「轻、克制」的调性一致。
 */

import { Check, FileSearch, Images, ListChecks, PenLine } from 'lucide-react';

import { COMPLETED_STATUSES, type WorkflowResponse } from '../api/types';
import { cn } from '@/lib/utils';

/** 四个步骤：文案与副标题（副标题只在桌面侧栏显示）。 */
export const STEP_LABELS = ['内容方向', '选择题目', '审核文章', '生成结果'] as const;

const STEP_HINTS = ['描述要写什么', '挑一个写作主线', '通过或要求修改', '文章与小红书素材'] as const;

/** 每一步的线性图标：方向 → 选题 → 审稿 → 出图。 */
const STEP_ICONS = [PenLine, ListChecks, FileSearch, Images] as const;

/**
 * 计算当前应该高亮第几步（从 0 开始）。
 *
 * 判断依据**优先是 status**（后端权威字段）：
 *   awaiting_topic_selection → 第 1 步（等选题）
 *   awaiting_review/revising → 第 2 步（等审稿）
 *   completed*              → 第 3 步（出结果）
 *
 * 只有在中间态与 failed 这类「status 无法直接定位进度」的情况下，
 * 才退化为「看已有数据判断走到哪了」。这仅用于步骤高亮，
 * 决定渲染哪一屏的逻辑在 Workbench 里，且只看 status 与 pending_action。
 */
export function resolveStepIndex(data: WorkflowResponse | null): number {
  if (data === null) {
    return 0;
  }

  const { status } = data;

  if (COMPLETED_STATUSES.includes(status)) {
    return 3;
  }
  if (status === 'awaiting_review' || status === 'revising') {
    return 2;
  }
  if (status === 'awaiting_topic_selection') {
    return 1;
  }

  // failed 与运行中的中间态：按「已经产出到哪一步」来高亮
  if (data.visual_points.length > 0) {
    return 3;
  }
  if (data.article_content !== null) {
    return 2;
  }
  if (data.generated_topics.length > 0) {
    return 1;
  }
  return 0;
}

export function StepNav({ currentIndex }: { currentIndex: number }) {
  return (
    <nav aria-label="内容生产流程" className="min-w-0 lg:sticky lg:top-[78px]">
      <p className="mb-3 hidden text-[11px] font-medium text-ink-faint lg:block">内容生产流程</p>

      <ol className="flex gap-1.5 max-lg:flex-row max-lg:overflow-x-auto lg:flex-col lg:gap-0.5">
        {STEP_LABELS.map((label, index) => {
          const state = index < currentIndex ? 'done' : index === currentIndex ? 'current' : 'todo';
          const Icon = STEP_ICONS[index];

          return (
            <li
              key={label}
              aria-current={state === 'current' ? 'step' : undefined}
              className={cn(
                'flex shrink-0 items-center gap-2.5 rounded-panel px-2 py-1.5',
                'transition-colors duration-200 ease-out',
                state === 'current' && 'bg-surface',
              )}
            >
              <span
                className={cn(
                  'flex size-[22px] shrink-0 items-center justify-center rounded-full',
                  'transition-colors duration-200 ease-out',
                  state === 'done' && 'bg-ink/[0.07] text-ink',
                  // 当前步骤：图标转黑 + 一圈极淡描边 + 微弱脉冲，强调很克制
                  state === 'current' && 'animate-halo bg-surface text-ink ring-1 ring-ink/25',
                  state === 'todo' && 'text-ink-faint',
                )}
              >
                {state === 'done' ? (
                  // key 让「状态变为 done」时重新挂载，动画才会重播
                  <Check
                    key="done"
                    size={12}
                    strokeWidth={2.75}
                    aria-hidden="true"
                    className="animate-pop"
                    // 按序号错开，形成依次打勾的节奏
                    style={{ animationDelay: `${index * 80}ms` }}
                  />
                ) : (
                  <Icon size={15} strokeWidth={1.75} aria-hidden="true" />
                )}
              </span>

              <span className="min-w-0">
                <span
                  className={cn(
                    'block truncate text-[13px] leading-5 transition-colors duration-200',
                    state === 'current'
                      ? 'font-semibold text-ink'
                      : state === 'done'
                        ? 'font-medium text-ink-soft'
                        : 'font-medium text-ink-faint',
                  )}
                >
                  {label}
                </span>
                {/* 副标题只在桌面侧栏出现，窄屏隐藏，避免横向步骤条被撑开 */}
                <span className="hidden truncate text-[11px] leading-4 text-ink-faint lg:block">
                  {STEP_HINTS[index]}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
