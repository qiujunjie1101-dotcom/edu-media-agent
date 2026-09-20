/**
 * 状态标签（shadcn/ui 风格）。
 *
 * 黑白灰极简路线：不用红绿黄表达状态，而是用「填充/描边/深浅」三档区分。
 *   - solid：实心近黑，表示「已完成」这类确定结果，视觉权重最高；
 *   - outline：描边浅底，表示中性/未产生结果；
 *   - muted：纯浅灰底，弱化处理，用于计数等次要信息。
 * 这样既守住了「拒绝彩色」，状态之间也仍然可区分。
 */

import type { HTMLAttributes } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

const badgeVariants = cva(
  // 过渡只作用于颜色与阴影，不做位移——标签是静态信息，不该有浮动感
  'inline-flex items-center gap-1 rounded-full text-[11px] font-medium leading-none transition-colors duration-200 whitespace-nowrap',
  {
    variants: {
      variant: {
        solid: 'bg-ink text-white',
        outline: 'border border-line-strong bg-surface text-ink-soft',
        muted: 'bg-sunken text-ink-mute border border-line',
        /** 低饱和灰蓝：用于「已生成」这类正向结果，是全站唯一的有彩色 */
        steel: 'bg-steel-soft text-steel border border-steel-line',
      },
      size: {
        sm: 'h-5 px-2',
        md: 'h-6 px-2.5',
      },
    },
    defaultVariants: { variant: 'muted', size: 'sm' },
  },
);

interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, size, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, size }), className)} {...props} />;
}

export { badgeVariants };
