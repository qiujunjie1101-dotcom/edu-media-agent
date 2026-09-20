/**
 * thread_id 的持久化：URL 查询参数 + localStorage 双写。
 *
 * ============================================================================
 * 为什么要存两份？
 * ============================================================================
 *   - URL（?thread_id=xxx）：可分享、可直接刷新、可用浏览器前进后退；
 *   - localStorage：用户手动清掉查询参数后仍能恢复上次会话。
 *
 * 读取优先级是「URL 优先」：URL 代表用户当前明确想看的那条会话，
 * 而 localStorage 只是兜底的记忆。
 *
 * ============================================================================
 * 一个重要的边界：localStorage 可能不可用
 * ============================================================================
 * 浏览器的隐私模式、或用户禁用了站点数据时，访问 localStorage 会**直接抛异常**
 * （而不是返回 null）。因此每次读写都必须包在 try/catch 里——
 * 否则整个工作台会因为「存不了 id」而白屏，这是不可接受的降级。
 */

/** localStorage 的键名。加前缀避免与同域下其它应用冲突。 */
export const THREAD_ID_STORAGE_KEY = 'yy_agent.thread_id';

/** URL 查询参数的键名，与后端字段名保持一致。 */
export const THREAD_ID_QUERY_KEY = 'thread_id';

/** 读取 localStorage 中的 thread_id。不可用或无值时返回 null。 */
export function readThreadIdFromStorage(): string | null {
  try {
    const value = window.localStorage.getItem(THREAD_ID_STORAGE_KEY);
    return value !== null && value.trim() !== '' ? value.trim() : null;
  } catch {
    // 隐私模式 / 被禁用：当作「没有记住任何会话」，不影响其它功能
    return null;
  }
}

/** 读取当前 URL 查询参数里的 thread_id。不存在时返回 null。 */
export function readThreadIdFromUrl(): string | null {
  const params = new URLSearchParams(window.location.search);
  const value = params.get(THREAD_ID_QUERY_KEY);
  return value !== null && value.trim() !== '' ? value.trim() : null;
}

/** 把 thread_id 写进 URL 查询参数（不产生新的历史记录）。 */
function writeThreadIdToUrl(threadId: string | null): void {
  const url = new URL(window.location.href);
  if (threadId === null) {
    url.searchParams.delete(THREAD_ID_QUERY_KEY);
  } else {
    url.searchParams.set(THREAD_ID_QUERY_KEY, threadId);
  }
  // replaceState 而不是 pushState：恢复会话属于「修正当前地址」，
  // 不应该在浏览器历史里堆出一串只差一个参数的记录。
  window.history.replaceState({}, '', url.toString());
}

/** 同时写入 URL 与 localStorage，保证两份记录一致。 */
export function persistThreadId(threadId: string): void {
  writeThreadIdToUrl(threadId);
  try {
    window.localStorage.setItem(THREAD_ID_STORAGE_KEY, threadId);
  } catch {
    // 存不进去也没关系：URL 里已经有 id，刷新后仍可恢复
  }
}

/** 清除两份记录（「重新开始」以及会话失效时调用）。 */
export function clearThreadId(): void {
  writeThreadIdToUrl(null);
  try {
    window.localStorage.removeItem(THREAD_ID_STORAGE_KEY);
  } catch {
    // 忽略：清不掉也不影响本次会话的使用
  }
}

/**
 * 计算页面初始化时应该恢复哪个会话。
 *
 * 顺序：URL → localStorage。
 * 命中后会把 id **回填到另一处**，让两份记录重新一致
 * （例如用户从 localStorage 恢复时，地址栏也应该出现 thread_id）。
 *
 * 返回 null 表示「没有可恢复的会话」，界面直接进入初始输入界面。
 */
export function resolveInitialThreadId(): string | null {
  const fromUrl = readThreadIdFromUrl();
  if (fromUrl !== null) {
    try {
      window.localStorage.setItem(THREAD_ID_STORAGE_KEY, fromUrl);
    } catch {
      // 忽略：URL 已经够用了
    }
    return fromUrl;
  }

  const fromStorage = readThreadIdFromStorage();
  if (fromStorage !== null) {
    writeThreadIdToUrl(fromStorage);
    return fromStorage;
  }

  return null;
}
