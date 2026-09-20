/**
 * 文档渲染（Markdown → 文档结构）的单元测试。
 *
 * 审稿页与结果页都依赖它把 article_content 渲染成「接近文档编辑器」的排版，
 * 因此块级元素的识别必须被单独钉住：
 *   - 标题降一级（文章里的 # → h2），保证每页只有一个 h1；
 *   - 代码块、有序/无序列表、引用都要成结构；
 *   - Markdown 标记本身不能作为可见文本残留（否则阅读体验等于没渲染）；
 *   - 输出必须是 React 元素而不是 innerHTML，HTML 片段只能当普通文字。
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DocumentView } from '../components/DocumentView';

const SAMPLE = [
  '# 一级标题',
  '',
  '正文段落，包含 `inline code` 与 **加粗**。',
  '',
  '> 引用一行',
  '',
  '## 二级标题',
  '',
  '- 第一项',
  '- 第二项',
  '',
  '1. 步骤一',
  '2. 步骤二',
  '',
  '```python',
  'print("hello")',
  '```',
].join('\n');

describe('DocumentView', () => {
  it('把 Markdown 渲染成文档结构，而不是原样输出标记', () => {
    render(<DocumentView markdown={SAMPLE} testId="doc" />);
    const doc = screen.getByTestId('doc');

    // 文章里的一级标题降级为 h2：每页只能有一个 h1（阶段标题）
    expect(screen.getByRole('heading', { level: 2, name: '一级标题' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: '二级标题' })).toBeInTheDocument();
    expect(doc.querySelectorAll('h1')).toHaveLength(0);

    expect(doc.querySelectorAll('ul li')).toHaveLength(2);
    expect(doc.querySelectorAll('ol li')).toHaveLength(2);
    expect(doc.querySelector('blockquote')).toHaveTextContent('引用一行');
    expect(doc.querySelector('pre code')).toHaveTextContent('print("hello")');
    expect(doc.querySelector('p code')).toHaveTextContent('inline code');
    expect(doc.querySelector('strong')).toHaveTextContent('加粗');

    // 标记本身不应作为可见文本出现
    expect(doc.textContent).not.toContain('#');
    expect(doc.textContent).not.toContain('**');
    expect(doc.textContent).not.toContain('```');
  });

  it('没有 Markdown 标记的纯文本也能正常显示为段落', () => {
    render(<DocumentView markdown={'第一段\n\n第二段'} testId="doc" />);

    expect(screen.getByText('第一段')).toBeInTheDocument();
    expect(screen.getByText('第二段')).toBeInTheDocument();
  });

  it('HTML 片段只会被当成普通文字，不会被解释成标签', () => {
    render(<DocumentView markdown={'<script>alert(1)</script>'} testId="doc" />);
    const doc = screen.getByTestId('doc');

    expect(doc.querySelector('script')).toBeNull();
    expect(doc).toHaveTextContent('<script>alert(1)</script>');
  });
});
