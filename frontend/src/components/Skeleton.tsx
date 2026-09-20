/**
 * 骨架屏占位块。
 *
 * 唯一的硬要求：**尺寸必须稳定**。
 * 加载态与真实内容的高度差越小，数据到达时的跳动就越小。
 * 因此这里强制要求传入 width / height，不允许「自适应高度」。
 */

interface SkeletonProps {
  /** CSS 宽度值，例如 '100%' / '180px' */
  width: string;
  /** CSS 高度值 */
  height: string;
  /** 圆角，默认与控件一致 */
  radius?: string;
}

export function Skeleton({ width, height, radius = 'var(--radius-xs)' }: SkeletonProps) {
  return (
    <span
      className="skeleton"
      style={{ width, height, borderRadius: radius }}
      // 纯装饰：读屏软件只需要听到外层容器上的「正在加载」提示
      aria-hidden="true"
    />
  );
}
