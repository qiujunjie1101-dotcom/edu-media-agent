/**
 * 第 4 屏：最终结果（status 为 completed 或 completed_with_warnings）。
 *
 * 两个视图用标签页切换，而不是并排两栏：
 *   - 公众号文章很长，小红书素材是图片网格，并排会把两边都挤扁；
 *   - 真实动作是「先看/复制文章，再逐张检查图片」，一次只专注一件事更贴合使用节奏。
 *
 * 复制按钮复制的是**后端返回的 Markdown 原文**（而不是渲染后的可见文本），
 * 因为运营人员要把它直接粘进公众号编辑器。
 *
 * 小红书素材部分做了一次 join：visual_points 与 image_assets 是后端返回的两个平行数组，
 * 只能通过 visual_point_id ↔ id 关联（图片并发产生，顺序不保证一致）。
 *
 * 标签页由 Radix 承载（键盘方向键、roving tabindex 都交给它），
 * 面板内容在切换时走 animate-fade，避免生硬地「啪」一下换掉。
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Copy, FileText, Images } from 'lucide-react';

import type { ImageAsset, VisualPoint } from '../api/types';
import { cn } from '@/lib/utils';
import { AssetCard } from '../components/AssetCard';
import { DocumentView } from '../components/DocumentView';
import { ErrorBanner } from '../components/ErrorBanner';
import { WorkArea } from '../components/WorkArea';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';

interface ResultScreenProps {
  /** 后端 status，用于区分「完全成功」与「有警告地完成」 */
  status: string;
  /** 后端 error_message：图片部分失败时是失败明细 */
  warningMessage: string | null;
  article: string | null;
  visualPoints: VisualPoint[];
  imageAssets: ImageAsset[];
}

/** 把两个平行数组合并成「要点 + 资产」的行，供卡片渲染。 */
interface AssetRow {
  key: string;
  point: VisualPoint | null;
  asset: ImageAsset | undefined;
}

export function joinAssets(visualPoints: VisualPoint[], imageAssets: ImageAsset[]): AssetRow[] {
  const assetByPointId = new Map<string, ImageAsset>();
  for (const asset of imageAssets) {
    assetByPointId.set(asset.visual_point_id, asset);
  }

  const rows: AssetRow[] = visualPoints.map((point) => ({
    key: point.id,
    point,
    asset: assetByPointId.get(point.id),
  }));

  // 兜底：万一后端返回了找不到对应要点的资产，也要显示出来（宁可多显示，不可静默丢弃）
  const knownPointIds = new Set(visualPoints.map((point) => point.id));
  for (const asset of imageAssets) {
    if (!knownPointIds.has(asset.visual_point_id)) {
      rows.push({ key: `orphan-${asset.visual_point_id}`, point: null, asset });
    }
  }

  return rows;
}

type ResultTab = 'article' | 'xiaohongshu';

/** 复制按钮的瞬时反馈状态。 */
type CopyState = 'idle' | 'done' | 'error';

/** 降级方案：剪贴板 API 不可用（非安全上下文/旧浏览器）时的兜底复制。 */
function copyBySelection(text: string): boolean {
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', 'true');
    area.style.position = 'fixed';
    area.style.top = '-1000px';
    document.body.appendChild(area);
    area.select();
    const succeeded = document.execCommand('copy');
    document.body.removeChild(area);
    return succeeded;
  } catch {
    return false;
  }
}

export function ResultScreen({
  status,
  warningMessage,
  article,
  visualPoints,
  imageAssets,
}: ResultScreenProps) {
  const [activeTab, setActiveTab] = useState<ResultTab>('article');
  const [warningDismissed, setWarningDismissed] = useState<boolean>(false);
  const [copyState, setCopyState] = useState<CopyState>('idle');

  /** 反馈文案 2 秒后自动消失；用 ref 存定时器，卸载时必须清掉 */
  const copyTimerRef = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (copyTimerRef.current !== null) {
        window.clearTimeout(copyTimerRef.current);
      }
    },
    [],
  );

  const rows = useMemo(() => joinAssets(visualPoints, imageAssets), [visualPoints, imageAssets]);
  const successCount = imageAssets.filter((asset) => asset.status === 'success').length;
  const failedCount = imageAssets.filter((asset) => asset.status === 'failed').length;

  // 警告内容变化时（例如换了一次会话）重新展示，避免上一次的关闭动作把新警告也吃掉
  useEffect(() => {
    setWarningDismissed(false);
  }, [warningMessage, status]);

  const showWarning = status === 'completed_with_warnings' && !warningDismissed;
  const hasArticle = article !== null && article.trim() !== '';

  const handleCopy = async (): Promise<void> => {
    const text = article ?? '';
    let succeeded = false;

    const clipboard = navigator.clipboard as Clipboard | undefined;
    if (clipboard !== undefined && typeof clipboard.writeText === 'function') {
      try {
        await clipboard.writeText(text);
        succeeded = true;
      } catch {
        succeeded = copyBySelection(text);
      }
    } else {
      succeeded = copyBySelection(text);
    }

    setCopyState(succeeded ? 'done' : 'error');
    if (copyTimerRef.current !== null) {
      window.clearTimeout(copyTimerRef.current);
    }
    copyTimerRef.current = window.setTimeout(() => setCopyState('idle'), 2000);
  };

  return (
    <WorkArea
      title="生成结果"
      description="公众号文章可直接复制发布；小红书素材按知识卡片逐张检查。"
      testId="screen-result"
      meta={
        // 右上角统计：做成一组收拾干净的小胶囊，而不是散落的文字
        <div className="flex items-center gap-1.5">
          <Badge variant="muted" size="md">
            共 {rows.length} 张卡片
          </Badge>
          <Badge variant="steel" size="md">
            成功 {successCount}
          </Badge>
          {failedCount > 0 ? (
            <Badge variant="solid" size="md">
              失败 {failedCount}
            </Badge>
          ) : null}
        </div>
      }
    >
      {showWarning ? (
        <div className="mb-5">
          <ErrorBanner
            variant="warning"
            message={warningMessage ?? '本次有部分图片生成失败，其余结果不受影响，可正常使用。'}
            onDismiss={() => setWarningDismissed(true)}
          />
        </div>
      ) : null}

      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as ResultTab)}
        className="gap-5"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <TabsList aria-label="生成结果视图">
            <TabsTrigger value="article">
              <FileText size={14} aria-hidden="true" />
              公众号文章
            </TabsTrigger>
            <TabsTrigger value="xiaohongshu">
              <Images size={14} aria-hidden="true" />
              小红书素材
            </TabsTrigger>
          </TabsList>

          {activeTab === 'article' && hasArticle ? (
            <div className="flex items-center gap-2">
              {/* 反馈文字放在按钮左侧：右侧按钮位置固定，不会因为反馈出现而移动 */}
              {copyState === 'done' ? (
                <span
                  role="status"
                  className="animate-fade text-[12px] font-medium text-steel"
                >
                  已复制
                </span>
              ) : null}
              {copyState === 'error' ? (
                <span role="alert" className="animate-fade text-[12px] font-medium text-ink">
                  复制失败，请手动选择文本
                </span>
              ) : null}

              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  void handleCopy();
                }}
                icon={
                  copyState === 'done' ? (
                    <Check size={14} aria-hidden="true" className="animate-pop" />
                  ) : (
                    <Copy size={14} aria-hidden="true" />
                  )
                }
              >
                复制文章
              </Button>
            </div>
          ) : null}
        </div>

        <TabsContent value="article">
          {hasArticle ? (
            /*
             * 必须保留 `doc` 类：代码块、行内 code、引用块、标题层级的排版
             * 都写在 app.css 的 `.doc ...` 选择器下。去掉它这些样式会整体失效。
             * 阅读宽度由 .doc 的 --reading-max（736px）决定，长文不跨满整行。
             */
            <div
              className={cn(
                'doc rounded-card border border-line bg-surface px-8 py-7',
                'shadow-[0_1px_2px_rgba(11,11,13,0.04)]',
              )}
            >
              <DocumentView markdown={article} testId="final-article" />
            </div>
          ) : (
            <p className="py-10 text-center text-[13px] text-ink-mute">后端没有返回文章内容。</p>
          )}
        </TabsContent>

        <TabsContent value="xiaohongshu">
          {rows.length === 0 ? (
            <p className="py-10 text-center text-[13px] text-ink-mute">后端没有返回视觉要点。</p>
          ) : (
            // auto-fill + minmax：列数随可用宽度自适应。
            // 下限 264px 是刻意放宽的——再窄卡片会显得密，与「低密度、轻盈」的取向相反
            <div
              data-testid="asset-grid"
              className="grid grid-cols-[repeat(auto-fill,minmax(264px,1fr))] gap-5"
            >
              {rows.map((row) => (
                <AssetCard key={row.key} point={row.point} asset={row.asset} />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </WorkArea>
  );
}
