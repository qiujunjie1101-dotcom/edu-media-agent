/**
 * 主工作区的页面骨架：标题 + 说明 + 右上角补充信息 + 内容区。
 *
 * 为什么不做成「大卡片」？
 *   工作台的主工作区本身就是页面级容器，再套一层描边阴影只会产生
 *   「卡片套卡片」的视觉噪音。这里只输出一个 h1 与一个内容槽，
 *   层级交给字号、留白与分隔线表达。
 *
 * 标题区做了一次入场动画（animate-rise）：页面切换时标题先落位，
 * 内容区的卡片再依次跟上，形成自上而下的阅读引导。
 */

import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

interface WorkAreaProps {
  /** 当前阶段标题（每屏唯一的 h1） */
  title: string;
  /** 标题下的一句说明 */
  description?: string;
  /** 右上角的补充信息（计数、状态标签等） */
  meta?: ReactNode;
  /** 供测试定位 */
  testId?: string;
  children: ReactNode;
}

export function WorkArea({ title, description, meta, testId, children }: WorkAreaProps) {
  return (
    <section data-testid={testId} className="min-w-0">
      <header
        className={cn(
          'animate-rise mb-7 flex flex-wrap items-start justify-between gap-x-6 gap-y-3',
          'border-b border-line pb-5',
        )}
      >
        <div className="min-w-0">
          <h1 className="text-[25px] font-semibold leading-tight text-ink">{title}</h1>
          {description !== undefined ? (
            <p className="mt-1.5 text-[13px] leading-relaxed text-ink-mute">{description}</p>
          ) : null}
        </div>

        {meta !== undefined ? (
          <div className="flex shrink-0 flex-wrap items-center gap-2">{meta}</div>
        ) : null}
      </header>

      <div className="min-w-0">{children}</div>
    </section>
  );
}
