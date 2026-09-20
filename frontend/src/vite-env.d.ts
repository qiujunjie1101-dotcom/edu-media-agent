/// <reference types="vite/client" />

/**
 * 让 TypeScript 认识我们自定义的 VITE_ 环境变量。
 *
 * 为什么需要显式声明？
 *   不加声明时 `import.meta.env.VITE_API_BASE_URL` 在类型上是不存在的，
 *   IDE 会标红，`tsc` 也会报错。这里补上声明，把「环境变量的名字」
 *   也变成契约的一部分——改名时编译期就会发现问题。
 */
interface ImportMetaEnv {
  /** 后端 API 基础地址，例如 http://localhost:8000/api/v1 */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
