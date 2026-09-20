/**
 * shadcn/ui 约定的类名合并工具。
 *
 * clsx 负责「按条件拼接类名」，tailwind-merge 负责「消解冲突」：
 * 传入 `'p-2 p-4'` 时后者只保留 `p-4`，而不是两条都留着让 CSS 顺序决定胜负。
 * 组件把 className 透传给调用方时，这一层是必须的——否则调用方的覆盖会时灵时不灵。
 */

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
