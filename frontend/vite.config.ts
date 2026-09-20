// Vite 配置：既负责开发服务器，也承载 Vitest 的测试配置。
//
// 为什么从 'vitest/config' 而不是 'vite' 导入 defineConfig？
//   因为只有 vitest 导出的类型里才包含 `test` 字段，
//   否则 TypeScript 会因为「对象字面量里有未知属性」而报错。
import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

/** shadcn 约定用 @/ 指向 src，这里与 tsconfig.json 的 paths 保持一致。 */
const srcDir = fileURLToPath(new URL('./src', import.meta.url));

export default defineConfig({
  plugins: [react(), tailwindcss()],

  resolve: {
    alias: { '@': srcDir },
  },

  server: {
    // 必须与后端 CORS_ALLOW_ORIGINS 中登记的来源完全一致。
    // strictPort：端口被占用时直接失败，而不是悄悄换到 5174——
    // 换端口会导致跨源校验失败，报错信息很难指向真正原因。
    port: 5173,
    strictPort: true,
  },

  test: {
    // jsdom 提供浏览器 DOM 的实现，让组件可以在 Node 里渲染
    environment: 'jsdom',
    // globals: true 让测试文件可直接使用 describe / it / expect
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // 组件测试不关心 CSS 产物，关掉可以省去样式解析开销
    css: false,
    // 每个用例前后自动还原被替换的全局方法（例如 fetch）
    restoreMocks: true,
  },
});
