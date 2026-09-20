/**
 * 浏览器入口：把 React 应用挂到 index.html 的 #root 上。
 *
 * 样式的引入顺序很重要：
 *   1. tokens.css —— 只定义 CSS 变量，不含具体选择器；
 *   2. app.css    —— 旧工作台样式，仍在为未迁移的三屏服务；
 *   3. index.css  —— Tailwind 入口（不含 preflight），放最后，
 *      这样迁移后的组件用 Tailwind 类时不与旧样式打架。
 */

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from './App';
import './styles/tokens.css';
import './styles/app.css';
import './styles/index.css';

const container = document.getElementById('root');
if (container === null) {
  // 正常情况下不可能发生：index.html 里一定有 #root。
  // 这里显式抛错，是为了避免 createRoot(null) 抛出难以理解的类型错误。
  throw new Error('找不到 #root 容器，请检查 index.html');
}

createRoot(container).render(
  // StrictMode 会在开发环境下故意重复执行副作用，用于提前暴露「没有正确清理」的问题。
  // 注意它只在开发模式生效，生产构建不受影响。
  <StrictMode>
    <App />
  </StrictMode>,
);
