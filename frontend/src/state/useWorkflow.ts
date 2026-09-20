/**
 * useWorkflow：整个前端唯一的「工作流状态机」。
 *
 * ============================================================================
 * 一条硬规则：界面状态只来自后端响应
 * ============================================================================
 * 这个 Hook 里没有任何一行「根据用户点了什么去推测现在是第几步」的代码。
 * 每次请求成功后，直接用后端返回的 WorkflowResponse 覆盖本地状态，
 * 再由界面根据 `status` 与 `pending_action` 决定渲染哪一屏。
 *
 * 这样做的好处是刷新页面、换设备、甚至后端重启（会话丢失）之后，
 * 界面与后端的认知永远不会分叉。
 *
 * ============================================================================
 * 三件必须处理好的事
 * ============================================================================
 * 1. **防重复提交**：React 的 setState 是异步的，连点两次时第二次事件触发时
 *    DOM 上的 disabled 可能还没生效。所以除了禁用按钮，还额外用一个
 *    **同步的 ref 标记**在函数入口直接拦截。
 * 2. **错误不清空现场**：请求失败时保留 data 不变，只追加一条可关闭的提示，
 *    这样运营人员不会因为一次网络抖动丢掉正在审核的文章。
 * 3. **会话失效要善后**：收到 THREAD_NOT_FOUND 说明这个 thread_id 已经没用了，
 *    必须清掉 URL + localStorage，并回到初始界面，否则用户会反复刷新反复失败。
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getWorkflow, resumeWorkflow, startWorkflow } from '../api/client';
import { ApiError, THREAD_NOT_FOUND_CODE, toApiError } from '../api/errors';
import type { WorkflowResponse } from '../api/types';
import { clearThreadId, persistThreadId, resolveInitialThreadId } from './storage';

/** 可能正在进行的动作，用于单独描述按钮的 loading 文案。 */
export type BusyAction = 'start' | 'select_topic' | 'approve' | 'revise' | 'refresh';

/** 交给界面的完整控制器。 */
export interface WorkflowController {
  /** 页面初始化时是否正在按 thread_id 恢复会话 */
  restoring: boolean;
  /** 当前会话数据；null 表示还没有任何会话（显示初始输入界面） */
  data: WorkflowResponse | null;
  /** 当前会话标识；null 表示还没有会话 */
  threadId: string | null;
  /** 正在进行的动作；null 表示空闲 */
  busy: BusyAction | null;
  /** 可关闭的错误提示；请求失败时设置，**不会**清掉 data */
  error: ApiError | null;
  /** 可关闭的中性提示（例如「上次会话已失效，已重置」） */
  notice: string | null;
  dismissError: () => void;
  dismissNotice: () => void;
  /** 启动新会话（输入内容方向） */
  start: (topicDirection: string) => Promise<void>;
  /** 重新拉取当前会话状态（只读，不推进流程） */
  refresh: () => Promise<void>;
  /** 人工选题 */
  selectTopic: (topicId: string) => Promise<void>;
  /** 人工通过 */
  approveArticle: () => Promise<void>;
  /** 人工驳回并要求重写 */
  reviseArticle: (feedback: string) => Promise<void>;
  /** 重新开始：清掉会话记录与全部界面状态 */
  restart: () => void;
}

export function useWorkflow(): WorkflowController {
  const [data, setData] = useState<WorkflowResponse | null>(null);
  const [restoring, setRestoring] = useState<boolean>(true);
  const [busy, setBusy] = useState<BusyAction | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  /** 同步的在途标记：用于在 React 重渲染之前挡住第二次点击。 */
  const inFlightRef = useRef<boolean>(false);
  /**
   * 会话「代号」。每次重新开始都会 +1。
   * 在途请求回来后若发现代号已变，就直接丢弃结果——
   * 否则「点了重新开始，2 秒后旧响应把界面又拉回旧会话」这个经典 bug 必然出现。
   */
  const generationRef = useRef<number>(0);

  // ---------------------------------------------------------------------------
  // 初始化：按 URL / localStorage 里的 thread_id 恢复界面
  // ---------------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const threadId = resolveInitialThreadId();

    if (threadId === null) {
      setRestoring(false);
      return;
    }

    void (async () => {
      try {
        const restored = await getWorkflow(threadId);
        if (cancelled) {
          return;
        }
        setData(restored);
        // 后端可能返回规范化后的 id，以响应为准写回两份记录
        persistThreadId(restored.thread_id);
      } catch (caught) {
        if (cancelled) {
          return;
        }
        const apiError = toApiError(caught);
        if (apiError.code === THREAD_NOT_FOUND_CODE) {
          // 会话已失效：清掉本地记录，回到初始界面（不当作错误弹窗）
          clearThreadId();
          setNotice('上次的会话已失效（后端重启会丢失内存中的会话），已为你重置工作台。');
        } else {
          // 其它错误（后端没启动等）：提示可关闭，同时回到初始界面让用户能重试
          setError(apiError);
        }
      } finally {
        if (!cancelled) {
          setRestoring(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // ---------------------------------------------------------------------------
  // 公共请求外壳：统一处理「防重复 / 覆盖状态 / 错误分流」
  // ---------------------------------------------------------------------------
  const run = useCallback(
    async (action: BusyAction, task: () => Promise<WorkflowResponse>): Promise<void> => {
      if (inFlightRef.current) {
        // 已有一个请求在途：直接忽略本次触发（这就是防重复提交的兜底）
        return;
      }
      inFlightRef.current = true;
      const generation = generationRef.current;
      setBusy(action);
      setError(null);

      try {
        const next = await task();
        if (generation !== generationRef.current) {
          return; // 用户已经点了「重新开始」，丢弃这条过期响应
        }
        setData(next);
        persistThreadId(next.thread_id);
      } catch (caught) {
        if (generation !== generationRef.current) {
          return;
        }
        const apiError = toApiError(caught);
        if (apiError.code === THREAD_NOT_FOUND_CODE) {
          clearThreadId();
          setData(null);
          setNotice('该会话不存在或已过期，已为你重置工作台。');
        } else {
          // 关键：只设置错误提示，**不动 data**，当前文章与题目全部留在屏幕上
          setError(apiError);
        }
      } finally {
        inFlightRef.current = false;
        if (generation === generationRef.current) {
          setBusy(null);
        }
      }
    },
    [],
  );

  // ---------------------------------------------------------------------------
  // 对外动作
  // ---------------------------------------------------------------------------

  const start = useCallback(
    (topicDirection: string) => run('start', () => startWorkflow(topicDirection)),
    [run],
  );

  const threadId = data?.thread_id ?? null;

  const refresh = useCallback((): Promise<void> => {
    if (threadId === null) {
      return Promise.resolve();
    }
    return run('refresh', () => getWorkflow(threadId));
  }, [run, threadId]);

  const selectTopic = useCallback(
    (topicId: string): Promise<void> => {
      if (threadId === null) {
        return Promise.resolve();
      }
      return run('select_topic', () =>
        resumeWorkflow(threadId, { action: 'select_topic', topic_id: topicId }),
      );
    },
    [run, threadId],
  );

  const approveArticle = useCallback((): Promise<void> => {
    if (threadId === null) {
      return Promise.resolve();
    }
    return run('approve', () => resumeWorkflow(threadId, { action: 'approve' }));
  }, [run, threadId]);

  const reviseArticle = useCallback(
    (feedback: string): Promise<void> => {
      if (threadId === null) {
        return Promise.resolve();
      }
      return run('revise', () => resumeWorkflow(threadId, { action: 'revise', feedback }));
    },
    [run, threadId],
  );

  const restart = useCallback((): void => {
    // 代号 +1：让所有在途请求的结果作废
    generationRef.current += 1;
    inFlightRef.current = false;
    clearThreadId();
    setData(null);
    setError(null);
    setNotice(null);
    setBusy(null);
  }, []);

  const dismissError = useCallback((): void => setError(null), []);
  const dismissNotice = useCallback((): void => setNotice(null), []);

  return {
    restoring,
    data,
    threadId,
    busy,
    error,
    notice,
    dismissError,
    dismissNotice,
    start,
    refresh,
    selectTopic,
    approveArticle,
    reviseArticle,
    restart,
  };
}
