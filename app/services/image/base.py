"""ImageService 抽象接口：图片生成能力的统一契约。

接口设计要点：``generate`` 必须接收 ``visual_point_id``。
因为多张图片是**并发**生成的，返回顺序无法保证；只有显式带上 id，
调用方才能把「图片结果」与「视觉要点」准确对应起来。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.domain import ImageAsset


class ImageService(ABC):
    """图片生成服务接口。"""

    @abstractmethod
    async def generate(self, prompt: str, size: str, visual_point_id: str) -> ImageAsset:
        """根据提示词生成一张图片。

        参数:
            prompt: 生图提示词
            size: 图片尺寸，例如 "1024x1024"
            visual_point_id: 该图片对应的视觉要点 id，用于结果对齐

        返回:
            ImageAsset: 结构化结果。成功时 ``status=success`` 且 ``url`` 有值；
            失败时 ``status=failed`` 且 ``error`` 说明原因（**不抛异常**，
            因为部分失败属于可降级场景，需要把失败信息如实返回给上层）。

        """
        ...
