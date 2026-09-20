/**
 * fetch 测试替身。
 *
 * 前端测试不应该依赖真实后端：既慢，又不可控（没办法让某一次请求恰好失败）。
 * 这里把全局 fetch 换成一个「按请求返回预设响应」的函数，并记录下每一次调用，
 * 于是测试既能断言界面表现，也能断言「到底发了几次请求、发的是什么」。
 */

import { vi } from 'vitest';

/** 一次被记录的请求。 */
export interface RecordedRequest {
  method: string;
  /** 完整 URL */
  url: string;
  /** 去掉域名后的路径，例如 /api/v1/workflows/start */
  path: string;
  /** 已解析的 JSON 请求体；没有请求体时为 null */
  body: Record<string, unknown> | null;
}

export interface FakeResponseInit {
  status?: number;
  body?: unknown;
}

/** 处理函数：可以同步返回，也可以返回 Promise（用于模拟「请求在途」）。 */
export type FetchHandler = (request: RecordedRequest) => FakeResponseInit | Promise<FakeResponseInit>;

/**
 * 构造一个「够用」的响应对象。
 *
 * 为什么不用真实的 Response？
 *   jsdom 环境里并没有实现 fetch/Response，即使有也可以省掉一层不确定性。
 *   api/client.ts 只用到 ok / status / json 三个成员，这里按需提供即可。
 */
export function fakeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

/** 把 fetch 替换成按 handler 应答的假实现，并返回调用记录。 */
export function stubFetch(handler: FetchHandler) {
  const requests: RecordedRequest[] = [];

  const fetchMock = vi.fn(async (input: unknown, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : String(input);
    const method = (init?.method ?? 'GET').toUpperCase();

    let body: Record<string, unknown> | null = null;
    if (typeof init?.body === 'string' && init.body !== '') {
      try {
        body = JSON.parse(init.body) as Record<string, unknown>;
      } catch {
        body = null;
      }
    }

    const request: RecordedRequest = {
      method,
      url,
      // 用固定基址解析，即使传进来的是相对地址也不会抛错
      path: new URL(url, 'http://localhost').pathname,
      body,
    };
    requests.push(request);

    const result = await handler(request);
    return fakeResponse(result.status ?? 200, result.body);
  });

  vi.stubGlobal('fetch', fetchMock);

  return { fetchMock, requests };
}
