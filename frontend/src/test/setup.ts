/**
 * Vitest 全局设置：在每个测试文件执行前自动运行一次。
 *
 * 三件事：
 *   1. 注册 jest-dom 的额外断言（toBeDisabled / toHaveTextContent / toBeInTheDocument 等）；
 *   2. 每个用例结束后清理 DOM、还原被替换的全局方法、清空 localStorage；
 *   3. 每个用例开始前把 URL 重置为根路径，避免上一个用例残留的 ?thread_id= 影响下一个。
 */

import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';

beforeEach(() => {
  // 会话恢复相关用例会改写 URL 查询参数，必须逐条隔离
  window.history.replaceState({}, '', '/');
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  // 还原 test 里用 vi.stubGlobal 替换掉的 fetch
  vi.unstubAllGlobals();
  window.localStorage.clear();
});
