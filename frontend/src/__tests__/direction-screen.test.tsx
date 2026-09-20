/**
 * 验收用例 1：初始输入与校验。
 *
 * DirectionScreen 是纯展示组件（提交行为由 props 传入），
 * 因此这里不需要任何 fetch 替身，直接把 onSubmit 换成一个 spy 即可。
 */

import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { DirectionScreen } from '../screens/DirectionScreen';

describe('输入内容方向', () => {
  it('初始状态下提交按钮禁用，并显示字数提示', () => {
    render(<DirectionScreen submitting={false} onSubmit={vi.fn()} />);

    expect(screen.getByRole('button', { name: /生成选题/ })).toBeDisabled();
    expect(screen.getByText('0 / 200')).toBeInTheDocument();
    // 输入框必须可聚焦、可编辑（键盘用户才有办法开始）
    expect(screen.getByLabelText('内容方向')).toBeEnabled();
  });

  it('只有 1 个字时禁用提交并给出明确提示', async () => {
    const user = userEvent.setup();
    render(<DirectionScreen submitting={false} onSubmit={vi.fn()} />);

    const onSubmit = vi.fn();
    expect(onSubmit).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText('内容方向'), 'A');

    expect(screen.getByRole('button', { name: /生成选题/ })).toBeDisabled();
    expect(screen.getByText('内容方向至少需要 2 个字')).toBeInTheDocument();
  });

  it('输入 2 个字即可提交，提交时去掉首尾空白', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<DirectionScreen submitting={false} onSubmit={onSubmit} />);

    const textarea = screen.getByLabelText('内容方向');
    await user.type(textarea, '  检查点机制  ');
    expect(screen.getByRole('button', { name: /生成选题/ })).toBeEnabled();

    await user.click(screen.getByRole('button', { name: /生成选题/ }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith('检查点机制');
  });

  it('超过 200 字会被截断，计数不会超过上限', () => {
    render(<DirectionScreen submitting={false} onSubmit={vi.fn()} />);

    const textarea = screen.getByLabelText('内容方向');
    fireEvent.change(textarea, { target: { value: 'A'.repeat(300) } });

    expect(screen.getByText('200 / 200')).toBeInTheDocument();
    expect((textarea as HTMLTextAreaElement).value).toHaveLength(200);
  });

  it('提交过程中按钮禁用并显示加载文案（防止重复点击）', () => {
    render(<DirectionScreen submitting onSubmit={vi.fn()} />);

    const button = screen.getByRole('button', { name: /正在生成选题/ });
    expect(button).toBeDisabled();
    // 提交期间输入框也应锁定，避免用户以为改了内容
    expect(screen.getByLabelText('内容方向')).toBeDisabled();
  });
});
