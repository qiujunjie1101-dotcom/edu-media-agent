/**
 * 按钮与图标按钮：全站统一的交互控件。
 *
 * 为什么集中成组件？
 *   视觉重构最怕「十处按钮十个样」。把「主/次/弱/强调描边」四种变体、加载态、
 *   禁用态收在一个文件里，样式与可访问性只需要维护一次。
 *
 * 两个关键约定：
 *   1. **加载中必须保持布局不变**：加载时只替换图标并保留原宽度（按钮不改变 padding），
 *      否则点击瞬间按钮会抽动一下。
 *   2. **图标一律 aria-hidden**：图标的语义由文字表达；纯图标按钮则必须用
 *      `IconButton` + `label`（同时提供 aria-label 与 tooltip）。
 */

import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { LoaderCircle } from 'lucide-react';

import { classNames } from './classNames';

/** 按钮变体。 */
export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'ghost';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** 视觉层级：primary 用于每屏唯一的主操作 */
  variant?: ButtonVariant;
  /** 是否处于请求中：自动禁用并显示 Spinner */
  loading?: boolean;
  /** 请求中替代显示的文案（默认沿用 children） */
  loadingLabel?: ReactNode;
  /** 左侧图标 */
  icon?: ReactNode;
  /** 是否占满整行 */
  block?: boolean;
}

export function Button({
  variant = 'secondary',
  loading = false,
  loadingLabel,
  icon,
  block = false,
  disabled,
  className,
  children,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      className={classNames('btn', `btn--${variant}`, block && 'btn--block', className)}
      // 加载中同样禁用：这是「防止重复提交」的第一层（第二层在 state 层的同步守卫）
      disabled={disabled === true || loading}
    >
      {loading ? (
        <LoaderCircle size={16} className="spin" aria-hidden="true" />
      ) : (
        icon ?? null
      )}
      <span>{loading ? (loadingLabel ?? children) : children}</span>
    </button>
  );
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** 无障碍名称：读屏软件与测试都依赖它 */
  label: string;
  /** 悬停/聚焦时显示的工具提示文案（默认与 label 相同） */
  tooltip?: string;
  icon: ReactNode;
}

/**
 * 纯图标按钮。
 *
 * 规范要求：图标按钮必须有 aria-label 和 tooltip。
 *   - aria-label 给读屏软件与自动化测试；
 *   - tooltip 给鼠标用户（原生 title 之外，另用 CSS tooltip，这样键盘聚焦时也能看到）。
 */
export function IconButton({ label, tooltip, icon, className, type = 'button', ...rest }: IconButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      className={classNames('iconbtn', className)}
      aria-label={label}
      title={tooltip ?? label}
      data-tooltip={tooltip ?? label}
    >
      {icon}
    </button>
  );
}
