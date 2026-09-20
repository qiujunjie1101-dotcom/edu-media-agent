/**
 * 应用根组件。
 *
 * 职责极小：把 useWorkflow 的状态机接到 Workbench 上。
 * 之所以拆成两层，是为了让「状态逻辑」与「展示逻辑」互不干扰：
 *   - useWorkflow：请求、防重复、错误分流、thread_id 持久化；
 *   - Workbench ：按 status / pending_action 决定渲染哪一屏。
 */

import { Workbench } from './components/Workbench';
import { useWorkflow } from './state/useWorkflow';

export default function App() {
  const controller = useWorkflow();
  return <Workbench controller={controller} />;
}
