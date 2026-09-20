/**
 * 提示条：错误 / 警告 / 信息三种语气，均可关闭。
 *
 * 两条设计约束：
 *   1. **错误不遮断操作**：它是页面内的一行，不是弹窗、也不是整屏错误页。
 *      运营人员关掉它就能继续看当前文章，不会因为一次网络抖动丢掉上下文。
 *   2. **错误码始终可见**：友好中文负责让人看懂，错误码负责让人排查。
 *
 * 黑白路线的语气区分靠「左侧粗描边」而不是整块彩色底：
 *   实心黑边 = 错误（最重）、灰蓝边 = 警告、浅灰边 = 信息。
 * 底色只有极浅的一层，避免大色块把页面切碎。
 */

import { Info, TriangleAlert, X } from 'lucide-react';

import { cn } from '@/lib/utils';

/** 三种语气，对应后端不同的「问题严重程度」。 */
export type BannerVariant = 'error' | 'warning' | 'info';

const VARIANT_CLASS: Record<BannerVariant, string> = {
  error: 'border-l-ink bg-ink/[0.035] text-ink',
  warning: 'border-l-steel bg-steel-soft text-ink',
  info: 'border-l-line-strong bg-sunken text-ink-soft',
};

interface ErrorBannerProps {
  variant: BannerVariant;
  /** 面向人的说明文案 */
  message: string;
  /** 机器可读错误码；仅 error 语气会展示 */
  code?: string;
  onDismiss: () => void;
}

export function ErrorBanner({ variant, message, code, onDismiss }: ErrorBannerProps) {
  const Icon = variant === 'info' ? Info : TriangleAlert;

  return (
    <div
      className={cn(
        'animate-rise flex items-start gap-3 rounded-panel border border-line border-l-[3px] px-3.5 py-3',
        VARIANT_CLASS[variant],
      )}
      // error / warning 用 alert 让读屏软件立刻播报；info 用 status 避免打断
      role={variant === 'info' ? 'status' : 'alert'}
    >
      <span aria-hidden="true" className="mt-0.5 shrink-0">
        <Icon size={16} />
      </span>

      <div className="min-w-0 flex-1">
        <p className="text-[13px] leading-relaxed">{message}</p>
        {code !== undefined && variant === 'error' ? (
          <p className="mt-1 font-mono text-[11.5px] text-ink-mute">错误码：{code}</p>
        ) : null}
      </div>

      <button
        type="button"
        onClick={onDismiss}
        aria-label="关闭提示"
        className={cn(
          'shrink-0 rounded-control p-1 text-ink-mute transition-colors duration-200',
          'hover:bg-ink/5 hover:text-ink',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-steel/30',
        )}
      >
        <X size={15} aria-hidden="true" />
      </button>
    </div>
  );
}
