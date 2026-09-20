"""MockImageService：图片服务的假实现。

S1 阶段**不创建真实图片**，只返回结构合法、内容稳定的模拟地址：

    https://mock.local/images/{visual_point_id}.png

为什么地址要以 ``visual_point_id`` 结尾？
    因为多张图片是并发生成的，返回顺序不确定。把 id 编进地址之后，
    人工核对时一眼就能看出「这张图对应哪个视觉要点」，
    测试里也能直接断言图片与要点是否对齐。
"""

from __future__ import annotations

from app.schemas.domain import ImageAsset, ImageAssetStatus
from app.services.image.base import ImageService

# 模拟图片地址的前缀。抽成常量，便于将来统一替换成真实图床域名。
MOCK_IMAGE_BASE_URL = "https://mock.local/images"


class MockImageService(ImageService):
    """确定性的假图片服务。

    参数:
        base_url: 模拟地址前缀，默认使用 MOCK_IMAGE_BASE_URL。
                  允许注入，方便测试或后续切换到本地静态目录。

    """

    def __init__(self, base_url: str = MOCK_IMAGE_BASE_URL) -> None:
        # rstrip("/") 去掉结尾多余的斜杠，避免拼出 "https://mock.local/images//vp1.png"
        self._base_url = base_url.rstrip("/")

    async def generate(self, prompt: str, size: str, visual_point_id: str) -> ImageAsset:
        """返回一张「假装生成好了」的图片资产。

        S1 阶段永远返回成功态：``status=success``、``url`` 稳定、``error`` 为空。

        注意：这里**故意不使用 prompt 与 size**——它们只影响真实模型出图内容，
        不影响本阶段的结果形状。保留参数是为了让签名与真实实现完全一致。
        """
        # 用下划线前缀标记「本阶段暂未使用」的参数，避免被误读成遗漏
        _ = (prompt, size)

        return ImageAsset(
            visual_point_id=visual_point_id,
            status=ImageAssetStatus.SUCCESS,
            url=f"{self._base_url}/{visual_point_id}.png",
            error=None,
        )
