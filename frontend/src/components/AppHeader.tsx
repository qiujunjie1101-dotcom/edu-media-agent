/**
 * 顶栏。
 *
 * 只保留三样东西（规范明确要求，不再重复放步骤导航）：
 *   左：产品图标 + 产品名
 *   右：当前状态标签 + 「重新开始」图标按钮
 *
 * 两个细节：
 *   1. 品牌文字是唯一允许压缩的元素（空间不足时出省略号），
 *      状态与操作永远完整可见，因此在窄屏也不会溢出或重叠；
 *   2. 「重新开始」用图标按钮，带 aria-label 与原生 title，鼠标与键盘都能看懂。
 *
 * 视觉：半透明白底 + 背景模糊。滚动时下方内容会从毛玻璃后面掠过，
 * 比纯色块更有层次，也不会像实心白条那样把页面切成两截。
 */

import { PenLine, RotateCcw } from 'lucide-react';

import { cn } from '@/lib/utils';
import { StatusPill } from './StatusPill';

interface AppHeaderProps {
  /** 是否正在按 thread_id 恢复会话（恢复期间状态未知） */
  restoring: boolean;
  /** 当前状态字符串；null 表示还没有会话 */
  status: string | null;
  /** 是否允许重新开始（没有会话时无意义，故禁用） */
  canRestart: boolean;
  onRestart: () => void;
}

export function AppHeader({ restoring, status, canRestart, onRestart }: AppHeaderProps) {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/85 backdrop-blur-md">
      <div className="mx-auto flex h-[58px] w-full max-w-[1280px] items-center justify-between gap-4 px-6">
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            aria-hidden="true"
            className="flex size-7 shrink-0 items-center justify-center rounded-[7px] bg-ink text-white"
          >
            <PenLine size={14} />
          </span>
          <span className="truncate text-[14px] font-semibold text-ink">
            自媒体内容运营工作台
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {restoring ? (
            <span
              data-testid="header-status"
              className="inline-flex h-6 items-center rounded-full border border-steel-line bg-steel-soft px-2.5 text-[11px] font-medium leading-none text-steel"
            >
              正在恢复…
            </span>
          ) : status === null ? (
            <span
              data-testid="header-status"
              className="inline-flex h-6 items-center rounded-full border border-line bg-sunken px-2.5 text-[11px] font-medium leading-none text-ink-mute"
            >
              未开始
            </span>
          ) : (
            <StatusPill status={status} testId="header-status" />
          )}

          <button
            type="button"
            aria-label="重新开始"
            title="重新开始：清除当前会话并回到初始界面"
            disabled={!canRestart}
            onClick={onRestart}
            className={cn(
              'flex size-8 items-center justify-center rounded-control text-ink-mute',
              'transition-all duration-200 ease-out',
              'hover:bg-sunken hover:text-ink active:scale-95',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-steel/30',
              'disabled:pointer-events-none disabled:opacity-35',
            )}
          >
            <RotateCcw size={15} aria-hidden="true" />
          </button>
        </div>
      </div>
    </header>
  );
}
