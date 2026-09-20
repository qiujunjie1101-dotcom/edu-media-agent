/**
 * 小红书素材卡片：把一个视觉要点和它对应的图片资产配成一张卡片。
 *
 * ============================================================================
 * 为什么需要「配对」这一步？
 * ============================================================================
 * 后端返回的是两个平行数组：
 *   visual_points: [{id: "vp1", order: 1, title, point, prompt}, ...]
 *   image_assets:  [{visual_point_id: "vp1", status, url, error}, ...]
 * 它们靠 visual_point_id ↔ id 关联，而且**顺序不保证一致**（图片并发生成），
 * 所以必须用 id 做 join，绝不能按下标取。
 *
 * ============================================================================
 * 媒体区区分「业务状态」与「渲染状态」——这是两类完全不同的东西
 * ============================================================================
 *
 *   业务状态（后端明确告诉我们的结果）：
 *     status=failed   → 「图片生成失败」+失败原因，需要人工介入
 *     没有对应资产     → 「未生成图片」
 *   这两种必须显示文案，因为它们是要人处理的事实。
 *
 *   渲染状态（图片能不能显示出来，与业务无关）：
 *     加载中           → 骨架屏流光
 *     地址拿不到/404   → 回落到灰阶预览位，**不显示技术性错误文案**
 *
 * 最后一条是刻意的：地址打不开是渲染层的事，把它写成「图片无法加载（地址不可访问）」
 * 只会让运营人员看到一屏技术黑话，却仍然不知道该做什么。
 * 统一落成安静的灰阶预览位，既不误导成「加载中」，也不吓人。
 *
 * 五种情况共用同一个 3:4 容器，所以无论哪张卡片走到哪个分支，
 * 网格的行高与列宽都不会变，不会因为一张图挂了就整片错位。
 */

import { useState } from 'react';
import { ImageOff, TriangleAlert } from 'lucide-react';

import type { ImageAsset, VisualPoint } from '../api/types';
import { cn } from '@/lib/utils';
import { Badge } from './ui/badge';
import { Skeleton } from './ui/skeleton';

interface AssetCardProps {
  /** 对应的视觉要点；为 null 表示这条资产找不到要点（异常数据，仍要能显示） */
  point: VisualPoint | null;
  /** 对应的图片资产；为 undefined 表示该要点没有生成结果 */
  asset: ImageAsset | undefined;
}

export function AssetCard({ point, asset }: AssetCardProps) {
  /** 图片元素自身的加载状态；地址不可达 / 404 / 跨域都会走到 error */
  const [loadState, setLoadState] = useState<'loading' | 'loaded' | 'error'>('loading');

  const title = point?.title ?? '未匹配到视觉要点';
  const order = point?.order ?? null;
  const pointId = point?.id ?? asset?.visual_point_id ?? '未知要点';

  const isFailedAsset = asset?.status === 'failed';
  const isMissingAsset = asset === undefined;
  /** 业务层面的异常：这两种要显示文案和失败原因 */
  const isBusinessState = isFailedAsset || isMissingAsset;

  const hasUrl = asset?.url != null && asset.url !== '';
  /** 地址存在且尚未加载失败，才真的渲染 <img> */
  const showImage = hasUrl && loadState !== 'error';

  /** 业务状态的文案；渲染失败不在此列（它走灰阶预览位，不显示文字）。 */
  const businessText = isFailedAsset ? '图片生成失败' : '未生成图片';

  return (
    <article
      data-testid={`asset-card-${pointId}`}
      className={cn(
        'card-hover group flex flex-col overflow-hidden rounded-card border border-line bg-surface',
        // 极轻的常驻阴影：卡片「浮」在浅灰底上，但没有明显的投影边缘
        'shadow-[0_1px_2px_rgba(11,11,13,0.035)]',
        'animate-rise',
      )}
      style={{ animationDelay: `${Math.max(0, (order ?? 1) - 1) * 90}ms` }}
    >
      {/* 3:4 固定比例媒体区：五种状态共用，保证网格不错位 */}
      <div className="asset-card__media relative aspect-[3/4] w-full overflow-hidden">
        {showImage ? (
          <>
            <img
              src={asset.url ?? ''}
              alt={`视觉要点 ${order ?? ''}：${title}`}
              loading="lazy"
              onLoad={() => setLoadState('loaded')}
              onError={() => setLoadState('error')}
              className={cn(
                'h-full w-full object-cover transition-opacity duration-500 ease-out',
                // 加载完成前完全透明，与下方骨架屏做交叉淡入
                loadState === 'loaded' ? 'opacity-100' : 'opacity-0',
                // hover 时图片极轻微放大，让「上浮」有内容层的呼应
                'group-hover:scale-[1.03]',
              )}
            />

            {/* 骨架屏覆盖在图片之上，加载完成后淡出 */}
            {loadState === 'loading' ? (
              <Skeleton
                label={`正在加载第 ${order ?? ''} 张图片`}
                className="absolute inset-0"
              />
            ) : null}
          </>
        ) : isBusinessState ? (
          // 后端明确说了「没生成 / 生成失败」：这是要人处理的事实，必须给文案
          <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-sunken px-5 text-center">
            <span className="flex size-11 items-center justify-center rounded-full border border-line-strong bg-surface text-ink-soft">
              <TriangleAlert size={17} strokeWidth={1.75} aria-hidden="true" />
            </span>
            <span className="max-w-[15ch] text-[12px] leading-snug text-ink-mute">
              {businessText}
            </span>
          </div>
        ) : (
          // 渲染不出来（地址拿不到）：安静地落成灰阶预览位，不显示技术错误文案
          <div
            data-testid={`asset-placeholder-${pointId}`}
            className="media-placeholder flex h-full w-full items-center justify-center"
          >
            <ImageOff
              size={18}
              strokeWidth={1.5}
              aria-hidden="true"
              className="text-ink-faint/60"
            />
          </div>
        )}

        {/* 序号角标：浮在图片左上角，替代原来正文里的一行「第 N 张」 */}
        <span
          className={cn(
            'absolute left-2.5 top-2.5 inline-flex h-5 items-center rounded-full px-2',
            'border border-white/20 bg-ink/50 text-[11px] font-medium leading-none text-white',
            'backdrop-blur-sm',
          )}
        >
          {order === null ? '—' : `第 ${order} 张`}
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex items-center justify-end">
          {isFailedAsset ? (
            <Badge variant="solid">生成失败</Badge>
          ) : isMissingAsset ? (
            <Badge variant="muted">无结果</Badge>
          ) : (
            <Badge variant="steel">已生成</Badge>
          )}
        </div>

        <h3 className="text-[14px] font-semibold leading-snug text-ink">{title}</h3>

        {point !== null ? (
          <p className="text-[12.5px] leading-relaxed text-ink-mute">{point.point}</p>
        ) : null}

        {isFailedAsset && asset?.error != null ? (
          <p className="rounded-control bg-sunken px-2.5 py-2 text-[12px] leading-relaxed text-ink-soft">
            <span className="font-medium text-ink">失败原因：</span>
            {asset.error}
          </p>
        ) : null}

        <p className="mt-auto pt-1 text-[11px] text-ink-faint">
          要点 ID：<span className="font-mono">{pointId}</span>
        </p>
      </div>
    </article>
  );
}
