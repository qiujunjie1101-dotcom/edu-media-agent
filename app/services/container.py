"""服务容器：根据配置装配具体的外部能力实现。

============================================================================
什么是「服务容器」？
============================================================================
它就是一个「按配置把各个服务实例组装好」的地方。可以把它理解成一个插线板：

- 配置说 ``LLM_PROVIDER=mock``  → 插上 MockLLMService
- 将来配置说 ``LLM_PROVIDER=openai`` → 插上真实实现（S7 阶段）

好处：整个项目里只有**这一处**知道「哪些实现是存在的」，
业务代码只跟抽象接口打交道，替换实现不会波及节点代码。

============================================================================
使用方式
============================================================================
应用启动时（``app/main.py`` 的 lifespan 钩子）构建一次，挂到 ``app.state`` 上：

    container = ServiceContainer.build(settings)
    app.state.container = container

将来工作流节点通过「构图时闭包注入」拿到 ``container`` 里的服务实例，
**不会**自己 new 客户端，也不会把服务实例写进工作流状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.core.config import Settings
from app.services.image.base import ImageService
from app.services.image.mock import MockImageService
from app.services.llm.base import LLMService
from app.services.llm.mock import MockLLMService

# 当前各能力支持的提供方清单。
# 用 Final 标注表示「这是一个常量，不应被重新赋值」。
# 后续阶段接入真实模型时，在这里追加 "openai" / "real" 即可。
SUPPORTED_LLM_PROVIDERS: Final[tuple[str, ...]] = ("mock",)
SUPPORTED_IMAGE_PROVIDERS: Final[tuple[str, ...]] = ("mock",)


@dataclass(frozen=True)
class ServiceContainer:
    """一次性装配好的服务集合。

    ``@dataclass`` 让 Python 自动生成 ``__init__`` / ``__eq__`` / ``__repr__``；
    ``frozen=True`` 表示实例创建后不可修改，避免运行中被意外替换掉某个服务。

    字段:
        settings: 本次装配使用的配置对象
        llm_service: 文本模型服务（抽象接口类型，调用方不关心具体实现）
        image_service: 图片模型服务

    """

    settings: Settings
    llm_service: LLMService
    image_service: ImageService

    @classmethod
    def build(cls, settings: Settings) -> ServiceContainer:
        """按配置装配服务容器。

        参数:
            settings: 应用配置

        返回:
            ServiceContainer: 装配好的容器

        异常:
            ValueError: 配置了当前阶段尚不支持的提供方时抛出，并给出中文提示

        """
        return cls(
            settings=settings,
            llm_service=_build_llm_service(settings),
            image_service=_build_image_service(settings),
        )


def _build_llm_service(settings: Settings) -> LLMService:
    """根据 ``settings.llm_provider`` 创建文本模型服务。

    这里只认识 "mock"；其它取值一律抛出**清晰的中文错误**。
    之所以要显式报错而不是静默回退到 mock：
    配置写错了却悄悄降级成假数据，会让问题一路潜伏到线上，非常危险。
    """
    # strip() + lower() 做一点归一化，容忍 "Mock" / " mock " 这类写法
    provider = settings.llm_provider.strip().lower()

    if provider in SUPPORTED_LLM_PROVIDERS:
        return MockLLMService()

    raise ValueError(
        f"暂不支持的 llm_provider：{settings.llm_provider!r}。"
        f"当前阶段（S1）可选值：{', '.join(SUPPORTED_LLM_PROVIDERS)}；"
        f"真实文本模型将在 S7 阶段接入。"
    )


def _build_image_service(settings: Settings) -> ImageService:
    """根据 ``settings.image_provider`` 创建图片模型服务。"""
    provider = settings.image_provider.strip().lower()

    if provider in SUPPORTED_IMAGE_PROVIDERS:
        return MockImageService()

    raise ValueError(
        f"暂不支持的 image_provider：{settings.image_provider!r}。"
        f"当前阶段（S1）可选值：{', '.join(SUPPORTED_IMAGE_PROVIDERS)}；"
        f"真实图片模型将在 S8 阶段接入。"
    )
