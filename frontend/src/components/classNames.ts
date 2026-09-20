/**
 * 拼接 className 的小工具。
 *
 * 为什么需要它？
 *   `class={`btn ${variant ? `btn--${variant}` : ''}`}` 这种写法很容易漏掉空格、
 *   或者把 `false` 拼进类名。这个函数只保留「有值的字符串」，把这类低级错误一次性消除。
 */
export function classNames(...parts: Array<string | false | null | undefined>): string {
  return parts.filter((part): part is string => Boolean(part)).join(' ');
}
