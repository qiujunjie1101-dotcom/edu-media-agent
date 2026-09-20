/**
 * 骨架屏。
 *
 * 用一道横向扫过的高光模拟「正在加载」，替代静态的「图片无法加载」文字：
 * 静态文字会让人以为已经失败，而流光会持续传达「还在进行中」。
 *
 * 无障碍：容器带 role="status" 与 aria-label，读屏软件会播报加载中，
 * 而内部纯装饰的色块对读屏隐藏。
 */

import type { HTMLAttributes } from 'react';

import { cn } from '@/lib/utils';

interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  /** 读屏软件播报的文案 */
  label?: string;
}

export function Skeleton({ className, label = '加载中', ...props }: SkeletonProps) {
  return (
    <div role="status" aria-label={label} className={cn('h-full w-full', className)} {...props}>
      <div className="skeleton-shimmer animate-shimmer h-full w-full" aria-hidden="true" />
    </div>
  );
}
