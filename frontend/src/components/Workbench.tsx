/**
 * 工作台骨架：顶栏 + 左侧步骤栏 + 主工作区，并负责「决定渲染哪一屏」。
 *
 * ============================================================================
 * 界面路由的唯一依据
 * ============================================================================
 * 判定顺序（自上而下，命中即返回）：
 *   1. restoring（正在按 thread_id 恢复）        → 骨架屏
 *   2. 还没有会话数据（data === null）           → 创建内容任务
 *   3. status 不在后端已知取值内                 → 状态异常（原样展示原始字段）
 *   4. status === "failed"                      → 失败 + 重新开始
 *   5. status 属于 completed*                    → 生成结果（两个标签页）
 *   6. pending_action.type === "topic_selection" → 选择题目
 *   7. pending_action.type === "article_review"  → 审核文章
 *   8. 其余（运行中的中间态，或 pending_action 为 null 且未完成）→ 处理中
 *
 * ⚠️ 这里没有任何「猜」的成分：既不数用户点了几次，也不根据本地时间推断进度，
 * 全部判断都来自后端返回的 status 与 pending_action。
 */

import { useCallback, useState } from 'react';

import {
  COMPLETED_STATUSES,
  IN_PROGRESS_STATUSES,
  WORKFLOW_STATUSES,
  type PendingAction,
} from '../api/types';
import type { WorkflowController } from '../state/useWorkflow';
import { ArticleReviewScreen } from '../screens/ArticleReviewScreen';
import { DirectionScreen } from '../screens/DirectionScreen';
import { ResultScreen } from '../screens/ResultScreen';
import {
  FailureScreen,
  ProcessingScreen,
  RestoringState,
  UnknownStateScreen,
} from '../screens/StatusScreens';
import { TopicSelectionScreen } from '../screens/TopicSelectionScreen';
import { AppHeader } from './AppHeader';
import { ErrorBanner } from './ErrorBanner';
import { StepNav, resolveStepIndex } from './StepNav';

/** status 是否是后端定义过的取值。 */
function isKnownStatus(status: string): boolean {
  return (WORKFLOW_STATUSES as readonly string[]).includes(status);
}

/**
 * 读取 pending_action 的原始 type 字符串。
 *
 * 为什么不直接用 `pending.type`？
 *   PendingAction 是**封闭联合类型**，两个分支都被前面的 if 处理掉之后，
 *   TypeScript 会把 pending 收窄成 never，此处再访问 .type 会编译报错。
 *   而运行期仍有「后端将来新增第三种中断类型」的可能——那时必须走
 *   「状态异常」界面而不是空白页，所以这里保留一次防御式读取。
 */
function readPendingType(pending: PendingAction | null): string | null {
  if (pending === null || typeof pending !== 'object') {
    return null;
  }
  const value = (pending as { type?: unknown }).type;
  return typeof value === 'string' ? value : null;
}

/** 界面之间的附加动作（纯展示层状态，不参与工作流语义）。 */
interface ScreenActions {
  /** 「返回修改方向」：放弃当前会话回到第一屏，并带回上一次填写的内容方向 */
  onBackToDirection: () => void;
  /** 需要回填给第一屏的内容方向 */
  prefillDirection: string | null;
}

/** 根据控制器状态决定渲染哪一屏。抽成函数是为了让判定顺序一目了然。 */
function renderScreen(controller: WorkflowController, actions: ScreenActions) {
  const { data, busy } = controller;

  // 2. 还没有会话：创建内容任务
  if (data === null) {
    return (
      <DirectionScreen
        submitting={busy === 'start'}
        onSubmit={controller.start}
        initialDirection={actions.prefillDirection ?? ''}
      />
    );
  }

  const { status } = data;

  // 3. 未知状态：明确报异常，绝不显示空白页
  if (!isKnownStatus(status)) {
    return (
      <UnknownStateScreen
        status={status}
        pendingType={readPendingType(data.pending_action)}
        busy={busy}
        onRefresh={controller.refresh}
        onRestart={controller.restart}
      />
    );
  }

  // 4. 失败
  if (status === 'failed') {
    return <FailureScreen message={data.error_message} onRestart={controller.restart} />;
  }

  // 5. 完成（含部分图片失败的降级完成）
  if (COMPLETED_STATUSES.includes(status)) {
    return (
      <ResultScreen
        status={status}
        warningMessage={data.error_message}
        article={data.article_content}
        visualPoints={data.visual_points}
        imageAssets={data.image_assets}
      />
    );
  }

  const pending = data.pending_action;
  const pendingType = readPendingType(pending);

  // 6. 等待人工选题
  if (pending?.type === 'topic_selection') {
    return (
      <TopicSelectionScreen
        topics={data.generated_topics}
        submitting={busy === 'select_topic'}
        onConfirm={controller.selectTopic}
        onBack={actions.onBackToDirection}
      />
    );
  }

  // 7. 等待人工审稿
  if (pending?.type === 'article_review') {
    return (
      <ArticleReviewScreen
        topic={data.selected_topic}
        article={data.article_content}
        revisionCount={pending.revision_count}
        limitReached={pending.revision_limit_reached}
        // 是否允许驳回：以后端的 allowed_actions 为准，前端不自行计算次数上限
        allowRevise={pending.allowed_actions.includes('revise')}
        busy={busy}
        onApprove={controller.approveArticle}
        onRevise={controller.reviseArticle}
      />
    );
  }

  // 8. 运行中的中间态，或「没有待办动作但尚未完成」
  if (IN_PROGRESS_STATUSES.includes(status) || pendingType === null) {
    return <ProcessingScreen status={status} busy={busy} onRefresh={controller.refresh} />;
  }

  // 兜底：状态已知但中断类型不认识（后端新增类型时才会走到这里）
  return (
    <UnknownStateScreen
      status={status}
      pendingType={pendingType}
      busy={busy}
      onRefresh={controller.refresh}
      onRestart={controller.restart}
    />
  );
}

export function Workbench({ controller }: { controller: WorkflowController }) {
  const { restoring, data, error, notice, dismissError, dismissNotice } = controller;

  /** 「返回修改方向」时要把上一次的内容方向带回第一屏，避免用户重新打字 */
  const [prefillDirection, setPrefillDirection] = useState<string | null>(null);

  const handleBackToDirection = useCallback((): void => {
    setPrefillDirection(data?.topic_direction ?? null);
    controller.restart();
  }, [controller, data]);

  const handleRestart = useCallback((): void => {
    setPrefillDirection(null);
    controller.restart();
  }, [controller]);

  return (
    <div className="app">
      <AppHeader
        restoring={restoring}
        status={data?.status ?? null}
        canRestart={data !== null}
        onRestart={handleRestart}
      />

      <div className="container">
        <div className="layout">
          <StepNav currentIndex={resolveStepIndex(data)} />

          <main className="workarea">
            {/*
              提示条固定在内容之上、且不遮挡内容：
              请求失败时当前文章仍然留在屏幕上，用户关掉提示就能继续工作。
            */}
            {notice !== null ? (
              <ErrorBanner variant="info" message={notice} onDismiss={dismissNotice} />
            ) : null}
            {error !== null ? (
              <ErrorBanner
                variant="error"
                message={error.message}
                code={error.code}
                onDismiss={dismissError}
              />
            ) : null}

            {restoring ? (
              <RestoringState />
            ) : (
              renderScreen(controller, {
                onBackToDirection: handleBackToDirection,
                prefillDirection,
              })
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
