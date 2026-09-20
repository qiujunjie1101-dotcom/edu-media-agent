/**
 * 标签页（shadcn/ui × Radix Tabs）。
 *
 * 为什么上 Radix 而不是继续手写按钮 + role="tab"？
 *   方向键切换、roving tabindex、aria-controls 与面板 id 的配对，
 *   手写要覆盖的分支很多；Radix 这些都做过无障碍验证。
 *
 * 本项目的两个约定被保留：
 *   1. 非激活面板**卸载**（Radix 默认行为），因此 role="article" 只会
 *      出现在当前面板里，测试无需区分隐藏节点；
 *   2. 激活项用「白色浮起的小块」表达，而不是下划线——与卡片的浮起语言一致。
 *
 * 切换时的淡入由 TabsContent 上的 animate-fade 承担。
 */

import type { ComponentProps } from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';

import { cn } from '@/lib/utils';

const Tabs = TabsPrimitive.Root;

function TabsList({ className, ...props }: ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn(
        'inline-flex items-center gap-1 rounded-panel border border-line bg-sunken p-1',
        className,
      )}
      {...props}
    />
  );
}

function TabsTrigger({ className, ...props }: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        'inline-flex items-center gap-1.5 rounded-control px-3 py-1.5 text-[13px] font-medium',
        'text-ink-mute transition-all duration-250 ease-out',
        'hover:text-ink-soft',
        // 激活态：白底 + 极轻阴影，像从凹槽里浮起来
        'data-[state=active]:bg-surface data-[state=active]:text-ink',
        'data-[state=active]:shadow-[0_1px_2px_rgba(11,11,13,0.08)]',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-steel/30',
      )}
      {...props}
    />
  );
}

function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      className={cn('animate-fade focus-visible:outline-none', className)}
      {...props}
    />
  );
}

export { Tabs, TabsList, TabsTrigger, TabsContent };
