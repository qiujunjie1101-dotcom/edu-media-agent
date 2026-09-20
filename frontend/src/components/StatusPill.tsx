/**
 * 当前状态标签（顶栏与各阶段页面共用）。
 *
 * 三个原则：
 *   1. 已知状态翻译成中文短句（STATUS_LABELS）；
 *   2. **未知状态原样显示**，方便定位「后端加了状态、前端没跟上」；
 *   3. 颜色只是辅助，文案本身必须能独立表达含义（色弱用户同样可读）。
 *
 * 黑白极简下的语气分档：不再用红/绿/黄，而是用「实心黑 → 灰蓝 → 描边 → 浅灰」
 * 四档权重。需要人立刻注意的状态（失败、等待人工决策）用实心黑，
 * 已完成这类「不用再管」的状态反而最轻。文案承担全部语义，颜色只做权重提示。
 */

import { COMPLETED_STATUSES, STATUS_LABELS } from '../api/types';
import { cn } from '@/lib/utils';

/** 视觉语气：只影响配色，不影响文案。 */
type Tone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger';

function resolveTone(status: string): Tone {
  if (status === 'failed') {
    return 'danger';
  }
  if (status === 'completed_with_warnings') {
    return 'warning';
  }
  if (COMPLETED_STATUSES.includes(status)) {
    return 'success';
  }
  if (status === 'awaiting_topic_selection' || status === 'awaiting_review') {
    // 两个人工中断点：它们最需要人注意
    return 'primary';
  }
  return 'neutral';
}

/** 语气 → 样式。solid 两档视觉上一致，靠文案区分（见文件头第 3 条）。 */
const TONE_CLASS: Record<Tone, string> = {
  danger: 'bg-ink text-white border-transparent',
  primary: 'bg-ink text-white border-transparent',
  warning: 'bg-steel-soft text-steel border-steel-line',
  success: 'bg-sunken text-ink-soft border-line',
  neutral: 'bg-sunken text-ink-mute border-line',
};

/** 取状态的中文名；未知状态返回带原值的说明。 */
export function statusLabelOf(status: string): string {
  return STATUS_LABELS[status] ?? `未知状态：${status}`;
}

interface StatusPillProps {
  status: string;
  testId?: string;
}

export function StatusPill({ status, testId }: StatusPillProps) {
  const tone = resolveTone(status);
  return (
    /*
     * 刻意不加 role="status"：
     * 状态会随每次轮询变化，若声明为 live region，读屏软件会不断打断用户；
     * 而且 role="status" 已被「中性提示条」独占，避免同一页面出现多个同名角色。
     */
    <span
      className={cn(
        'inline-flex h-6 items-center rounded-full border px-2.5 text-[11px] font-medium leading-none',
        'transition-colors duration-300',
        TONE_CLASS[tone],
      )}
      data-testid={testId}
    >
      {statusLabelOf(status)}
    </span>
  );
}
