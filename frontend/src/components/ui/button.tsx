/**
 * 按钮（shadcn/ui 风格，cva 变体）。
 *
 * 与旧的 components/Button.tsx 并存，而不是替换：
 * 旧按钮仍在为「内容方向 / 选择题目 / 审核文章」三屏服务，
 * 等那三屏迁移过来之后再统一收敛，避免一次改动同时踩到两处。
 *
 * 动效取向：hover 只做颜色与阴影的过渡，按下时轻微缩放（active:scale-98）。
 * 不做位移或发光——按钮是高频点击控件，过度动效会让人烦躁。
 */

import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { LoaderCircle } from 'lucide-react';

import { cn } from '@/lib/utils';

const buttonVariants = cva(
  [
    'inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium',
    'rounded-control transition-all duration-200 ease-out',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-steel/30',
    'disabled:pointer-events-none disabled:opacity-40',
    'active:scale-[0.98]',
  ],
  {
    variants: {
      variant: {
        /** 实心近黑：每屏唯一的主操作 */
        primary:
          'bg-ink text-white shadow-[0_1px_2px_rgba(11,11,13,0.18)] hover:bg-ink/88 hover:shadow-[0_8px_20px_-10px_rgba(11,11,13,0.5)]',
        /** 描边：次操作，与白底卡片同色以保持轻盈 */
        outline:
          'border border-line-strong bg-surface text-ink hover:bg-sunken hover:border-ink/25',
        /** 无边框：最弱一级，用于「返回」「跳过」这类 */
        ghost: 'text-ink-soft hover:bg-sunken hover:text-ink',
        /** 低饱和灰蓝：需要与主操作区分、但又不该是黑的地方 */
        steel: 'bg-steel text-white hover:bg-steel-strong',
      },
      size: {
        sm: 'h-8 px-3 text-[13px]',
        md: 'h-9 px-4 text-sm',
        icon: 'h-9 w-9',
      },
    },
    defaultVariants: { variant: 'outline', size: 'md' },
  },
);

interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** 请求中：自动禁用并把左侧图标换成转圈 */
  loading?: boolean;
  /** 请求中替代显示的文案（默认沿用 children） */
  loadingLabel?: ReactNode;
  icon?: ReactNode;
  /** 占满整行 */
  block?: boolean;
}

export function Button({
  className,
  variant,
  size,
  loading = false,
  loadingLabel,
  icon,
  block = false,
  disabled,
  children,
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      type={type}
      className={cn(buttonVariants({ variant, size }), block && 'w-full', className)}
      // 加载中一并禁用：这是防重复提交的第一层，第二层在状态层
      disabled={disabled === true || loading}
    >
      {loading ? (
        <LoaderCircle size={15} className="animate-spin-slow" aria-hidden="true" />
      ) : (
        icon
      )}
      <span>{loading ? (loadingLabel ?? children) : children}</span>
    </button>
  );
}

export { buttonVariants };
