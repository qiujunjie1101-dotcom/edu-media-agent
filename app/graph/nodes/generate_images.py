"""generate_images 节点：并发生成图片，并把结果写入 image_assets。

============================================================================
为什么要并发？
============================================================================
生成 3–5 张图片是纯等待 I/O 的活。串行执行总耗时是各张之和，
并发执行总耗时约等于最慢的那一张。

============================================================================
结果对齐
============================================================================
并发完成顺序不确定，因此**绝不能靠返回值顺序**去对应视觉要点。
本节点在发起调用时就把每个 ``visual_point_id`` 记住，
用完 ``zip(..., strict=True)`` 与结果逐一配对，保证：

    len(image_assets) == len(visual_points) 且 id 集合完全一致

============================================================================
降级策略（唯一允许「带着问题继续」的地方）
============================================================================
- 全部成功 → ``completed``
- 部分失败 → ``completed_with_warnings``，成功与失败的结果都保留，
  并在 ``error_message`` 里列出失败项
- 全部失败 → 抛 ``ImageGenerationFailedError``（不返回假成功）

单张失败既可能是「服务返回 status=failed」，也可能是「服务直接抛异常」，
两种都按失败处理。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.exceptions import ContentValidationError, ImageGenerationFailedError
from app.graph.nodes import NodeFunc, NodeResult
from app.graph.state import MediaWorkflowState, WorkflowStatus
from app.schemas.domain import ImageAsset, ImageAssetStatus
from app.services.image.base import ImageService

# 图片尺寸。技术方案里尺寸风格仍待确认，这里先固定一个默认值，
# 将来做成配置项时只需改这一处。
IMAGE_SIZE = "1024x1024"


def build_generate_images_node(image_service: ImageService) -> NodeFunc:
    """创建 generate_images 节点。

    参数:
        image_service: 图片服务（构图时注入）

    返回:
        NodeFunc: 可注册到 StateGraph 的异步节点函数

    """

    async def generate_images(state: MediaWorkflowState) -> NodeResult:
        """并发生成全部图片，汇总为结构化结果。"""
        points = state["visual_points"]
        if not points:
            raise ContentValidationError("视觉要点为空，无法生成图片")

        # 先建好 (visual_point_id, 提示词) 的配对，再并发调用。
        # return_exceptions=True 让「某一张抛异常」不会打断其它图片的生成。
        tasks = [
            _generate_one(image_service, point_id=point["id"], prompt=point["prompt"])
            for point in points
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assets: list[dict[str, Any]] = []
        failed_ids: list[str] = []

        # strict=True：长度不一致会直接报错，避免出现「错位配对」这种最难查的 bug
        for point, result in zip(points, results, strict=True):
            point_id = point["id"]

            if isinstance(result, BaseException):
                # 服务直接抛异常 → 也记为该要点失败
                assets.append(
                    ImageAsset(
                        visual_point_id=point_id,
                        status=ImageAssetStatus.FAILED,
                        url=None,
                        error=f"{type(result).__name__}: {result}",
                    ).model_dump(mode="json")
                )
                failed_ids.append(point_id)
                continue

            asset = result.model_dump(mode="json")
            assets.append(asset)
            if asset["status"] != ImageAssetStatus.SUCCESS.value:
                failed_ids.append(point_id)

        succeeded_count = len(assets) - len(failed_ids)
        if succeeded_count == 0:
            raise ImageGenerationFailedError(
                f"{len(assets)} 张图片全部生成失败，失败明细："
                + "; ".join(f"{asset['visual_point_id']} → {asset['error']}" for asset in assets)
            )

        if failed_ids:
            return {
                "image_assets": assets,
                "status": WorkflowStatus.COMPLETED_WITH_WARNINGS.value,
                "error_message": (
                    f"共 {len(failed_ids)} 张图片生成失败：{', '.join(failed_ids)}；"
                    "其余图片已正常生成"
                ),
            }

        return {
            "image_assets": assets,
            "status": WorkflowStatus.COMPLETED.value,
            "error_message": None,
        }

    return generate_images


async def _generate_one(image_service: ImageService, *, point_id: str, prompt: str) -> ImageAsset:
    """生成单张图片的小包装，纯粹为了让上面的并发表达式更短。"""
    return await image_service.generate(prompt=prompt, size=IMAGE_SIZE, visual_point_id=point_id)
