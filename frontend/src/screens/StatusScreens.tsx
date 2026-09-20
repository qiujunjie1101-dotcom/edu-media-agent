/**
 * 四类「非主流程」界面：恢复中 / 处理中 / 失败 / 状态异常。
 *
 * 共同的一条硬要求：**任何情况都不能出现空白页面**。
 * 每种情况都必须回答两个问题：「发生了什么」「我现在能做什么」。
 */

import { LoaderCircle, RefreshCw, RotateCcw, TriangleAlert } from 'lucide-react';

import { Button } from '../components/Button';
import { Skeleton } from '../components/Skeleton';
import { StatusPill, statusLabelOf } from '../components/StatusPill';
import { WorkArea } from '../components/WorkArea';
import type { BusyAction } from '../state/useWorkflow';

/**
 * 恢复中：用与「创建内容任务」同构的骨架屏占位。
 * 尺寸固定，因此数据到达后页面不会发生高度跳动。
 */
export function RestoringState() {
  return (
    <WorkArea
      title="正在恢复会话"
      description="根据地址栏中的 thread_id 重新获取流程状态。"
      testId="screen-restoring"
    >
      <div className="skeleton-page" aria-busy="true">
        <Skeleton width="160px" height="18px" />
        <Skeleton width="100%" height="180px" radius="var(--radius-sm)" />
        <div className="skeleton-page__foot">
          <Skeleton width="120px" height="36px" radius="var(--radius-sm)" />
        </div>
      </div>

      {/* 视觉上是骨架屏，读屏软件需要一个明确的「正在加载」播报 */}
      <span className="sr-only" role="status">
        正在加载会话状态…
      </span>
    </WorkArea>
  );
}

interface ProcessingScreenProps {
  /** 后端状态字符串 */
  status: string;
  busy: BusyAction | null;
  onRefresh: () => void;
}

/**
 * 处理中：status 是运行中的中间态，或者 pending_action 为 null 但流程尚未结束。
 *
 * 注意这里**不猜**进度百分比：后端没有提供任何进度数据，
 * 界面只如实说明当前处在哪个阶段，并提供手动刷新。
 */
export function ProcessingScreen({ status, busy, onRefresh }: ProcessingScreenProps) {
  return (
    <WorkArea
      title="处理中"
      description="工作流正在自动执行，这一阶段不需要人工操作。"
      testId="screen-processing"
      meta={<StatusPill status={status} />}
    >
      <div className="state state--center" role="status">
        <LoaderCircle size={22} className="spin" aria-hidden="true" />
        <p className="state__title">{statusLabelOf(status)}</p>
        <p className="state__text">
          若长时间没有变化，可以点击「刷新状态」重新获取最新进度。
        </p>
        <Button
          variant="secondary"
          onClick={onRefresh}
          disabled={busy !== null}
          loading={busy === 'refresh'}
          icon={<RefreshCw size={16} aria-hidden="true" />}
        >
          刷新状态
        </Button>
      </div>
    </WorkArea>
  );
}

interface FailureScreenProps {
  /** 失败说明；后端没有给说明时使用兜底文案 */
  message: string | null;
  onRestart: () => void;
}

/** 失败：status === "failed"，给出错误摘要与唯一可行的出口。 */
export function FailureScreen({ message, onRestart }: FailureScreenProps) {
  return (
    <WorkArea
      title="流程失败"
      description="工作流遇到了无法继续的错误，本次内容没有产出。"
      testId="screen-failed"
    >
      <div className="state" role="alert">
        <span className="state__icon state__icon--error">
          <TriangleAlert size={22} aria-hidden="true" />
        </span>
        <p className="state__title">本次内容生产未能完成</p>
        <p className="state__text">{message ?? '后端没有返回具体错误信息，请稍后重试。'}</p>
        <Button
          variant="primary"
          onClick={onRestart}
          icon={<RotateCcw size={16} aria-hidden="true" />}
        >
          重新开始
        </Button>
      </div>
    </WorkArea>
  );
}

interface UnknownStateScreenProps {
  /** 后端返回的、前端尚不认识的状态字符串 */
  status: string;
  /** 当前 pending_action 的类型；null 表示没有中断 */
  pendingType: string | null;
  busy: BusyAction | null;
  onRefresh: () => void;
  onRestart: () => void;
}

/**
 * 状态异常：后端返回了前端不认识的 status。
 *
 * 这里刻意**原样展示原始字段**而不是只说「出错了」：
 * 排查这类问题最需要的就是「后端到底返回了什么」。
 */
export function UnknownStateScreen({
  status,
  pendingType,
  busy,
  onRefresh,
  onRestart,
}: UnknownStateScreenProps) {
  return (
    <WorkArea
      title="状态异常"
      description="后端返回了工作台尚未支持的状态，请先刷新；若持续出现，请把下面的原始字段反馈给开发。"
      testId="screen-unknown"
    >
      <div className="state" role="alert">
        <span className="state__icon state__icon--error">
          <TriangleAlert size={22} aria-hidden="true" />
        </span>
        <p className="state__title">无法识别的流程状态</p>
        <p className="state__text">
          为避免误操作，工作台不会对未知状态做任何推测，也不会自动推进流程。
        </p>
      </div>

      <dl className="kv">
        <div className="meta-row">
          <dt className="meta-row__label">status</dt>
          <dd className="meta-row__value mono">{status}</dd>
        </div>
        <div className="meta-row">
          <dt className="meta-row__label">pending_action.type</dt>
          <dd className="meta-row__value mono">{pendingType ?? 'null'}</dd>
        </div>
      </dl>

      <div className="actionbar">
        <Button variant="ghost" onClick={onRestart}>
          重新开始
        </Button>
        <div className="actionbar__actions">
          <Button
            variant="secondary"
            onClick={onRefresh}
            disabled={busy !== null}
            loading={busy === 'refresh'}
            icon={<RefreshCw size={16} aria-hidden="true" />}
          >
            刷新状态
          </Button>
        </div>
      </div>
    </WorkArea>
  );
}
