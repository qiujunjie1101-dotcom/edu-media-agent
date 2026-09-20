/**
 * 文档视图：把后端返回的 Markdown 原文渲染成接近文档编辑器的排版。
 *
 * ============================================================================
 * 为什么自己写而不是引入 markdown 库？
 * ============================================================================
 * 需求只覆盖「标题 / 代码块 / 列表 / 引用 / 段落」这几类块级元素，
 * 为此引入一个解析库（及其一整棵依赖树）并不划算，也不符合「不增加大型依赖」的约束。
 *
 * 安全说明：这里**完全不用 innerHTML**，一切通过 React 元素输出，
 * 因此即使文章里出现 `<script>` 之类的文本，也只会被当成普通文字显示。
 *
 * ============================================================================
 * 标题层级为什么要「降一级」？
 * ============================================================================
 * 每个页面已经有一个 h1（阶段标题）。文章里的一级标题（#）若再输出 h1，
 * 页面就会出现多个 h1，破坏文档大纲。因此文章里的 # → h2、## → h3，以此类推。
 */

import { Fragment, useMemo, type ReactNode } from 'react';

import { classNames } from './classNames';

/** 解析后的块级元素。 */
type Block =
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'code'; lang: string; text: string }
  | { kind: 'quote'; lines: string[] }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; items: string[] }
  | { kind: 'hr' };

const HEADING = /^(#{1,6})\s+(.*)$/;
const FENCE = /^```(.*)$/;
const QUOTE = /^>\s?(.*)$/;
const BULLET = /^[-*+]\s+(.*)$/;
const ORDERED = /^\d+[.)]\s+(.*)$/;
const RULE = /^(-{3,}|\*{3,}|_{3,})$/;

/** 把 Markdown 原文切成块级元素。 */
export function parseBlocks(markdown: string): Block[] {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];

  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    // 空行：仅用于分隔块
    if (trimmed === '') {
      index += 1;
      continue;
    }

    // 代码围栏：一直读到下一个围栏为止（内部内容原样保留，不做行内解析）
    const fence = FENCE.exec(trimmed);
    if (fence !== null) {
      const lang = fence[1].trim();
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        body.push(lines[index]);
        index += 1;
      }
      // 跳过收尾围栏（如果存在）
      if (index < lines.length) {
        index += 1;
      }
      blocks.push({ kind: 'code', lang, text: body.join('\n') });
      continue;
    }

    // 分隔线
    if (RULE.test(trimmed)) {
      blocks.push({ kind: 'hr' });
      index += 1;
      continue;
    }

    // 标题
    const heading = HEADING.exec(trimmed);
    if (heading !== null) {
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2].trim() });
      index += 1;
      continue;
    }

    // 引用：连续的 > 行合并为同一个引用块
    if (QUOTE.test(trimmed)) {
      const quoteLines: string[] = [];
      while (index < lines.length && QUOTE.test(lines[index].trim())) {
        quoteLines.push(QUOTE.exec(lines[index].trim())![1].trim());
        index += 1;
      }
      blocks.push({ kind: 'quote', lines: quoteLines });
      continue;
    }

    // 无序列表
    if (BULLET.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && BULLET.test(lines[index].trim())) {
        items.push(BULLET.exec(lines[index].trim())![1].trim());
        index += 1;
      }
      blocks.push({ kind: 'ul', items });
      continue;
    }

    // 有序列表
    if (ORDERED.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && ORDERED.test(lines[index].trim())) {
        items.push(ORDERED.exec(lines[index].trim())![1].trim());
        index += 1;
      }
      blocks.push({ kind: 'ol', items });
      continue;
    }

    // 普通段落：连续的非空、非块起始行合并成一个段落
    const paragraph: string[] = [];
    while (index < lines.length) {
      const current = lines[index].trim();
      if (
        current === '' ||
        HEADING.test(current) ||
        current.startsWith('```') ||
        QUOTE.test(current) ||
        BULLET.test(current) ||
        ORDERED.test(current) ||
        RULE.test(current)
      ) {
        break;
      }
      paragraph.push(current);
      index += 1;
    }
    blocks.push({ kind: 'paragraph', text: paragraph.join(' ') });
  }

  return blocks;
}

/** 行内标记：`代码` 与 **加粗** 两种，其余一律按纯文本渲染。 */
const INLINE = /(`[^`]+`|\*\*[^*]+\*\*)/g;

function renderInline(text: string, keyPrefix: string): ReactNode {
  const parts = text.split(INLINE);

  return parts.map((part, partIndex) => {
    const key = `${keyPrefix}-${partIndex}`;

    if (part.length > 2 && part.startsWith('`') && part.endsWith('`')) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    if (part.length > 4 && part.startsWith('**') && part.endsWith('**')) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    return <Fragment key={key}>{part}</Fragment>;
  });
}

function renderBlock(block: Block, index: number): ReactNode {
  const key = `block-${index}`;

  switch (block.kind) {
    case 'heading': {
      // 降一级：文章里的 # 渲染成 h2，保证每页只有一个 h1
      const Tag = `h${Math.min(block.level + 1, 5)}` as 'h2' | 'h3' | 'h4' | 'h5';
      return <Tag key={key}>{renderInline(block.text, key)}</Tag>;
    }
    case 'paragraph':
      return <p key={key}>{renderInline(block.text, key)}</p>;
    case 'code':
      return (
        <pre key={key}>
          <code>{block.text}</code>
        </pre>
      );
    case 'quote':
      return (
        <blockquote key={key}>
          {block.lines.map((line, lineIndex) => (
            <p key={`${key}-${lineIndex}`}>{renderInline(line, `${key}-${lineIndex}`)}</p>
          ))}
        </blockquote>
      );
    case 'ul':
      return (
        <ul key={key}>
          {block.items.map((item, itemIndex) => (
            <li key={`${key}-${itemIndex}`}>{renderInline(item, `${key}-${itemIndex}`)}</li>
          ))}
        </ul>
      );
    case 'ol':
      return (
        <ol key={key}>
          {block.items.map((item, itemIndex) => (
            <li key={`${key}-${itemIndex}`}>{renderInline(item, `${key}-${itemIndex}`)}</li>
          ))}
        </ol>
      );
    case 'hr':
      return <hr key={key} />;
    default:
      return null;
  }
}

interface DocumentViewProps {
  /** Markdown 原文（与后端返回的 article_content 完全一致） */
  markdown: string;
  /** 供测试定位 */
  testId?: string;
  className?: string;
}

export function DocumentView({ markdown, testId, className }: DocumentViewProps) {
  const blocks = useMemo(() => parseBlocks(markdown), [markdown]);

  return (
    <div className={classNames('doc__body', className)} data-testid={testId}>
      {blocks.map((block, index) => renderBlock(block, index))}
    </div>
  );
}
