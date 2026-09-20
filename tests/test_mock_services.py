"""验证 Mock 服务：确定性、数量正确、受 feedback 影响、不联网、不依赖密钥。

验收标准 5 ~ 8。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.schemas.domain import ImageAsset, ImageAssetStatus, TopicCandidate, VisualPoint
from app.services.container import ServiceContainer
from app.services.image.base import ImageService
from app.services.image.mock import MockImageService
from app.services.llm.base import LLMService
from app.services.llm.mock import MockLLMService

DIRECTION = "面向零基础学员讲清楚 LangGraph 的检查点机制"


# ---------------------------------------------------------------------------
# 容器装配
# ---------------------------------------------------------------------------


def test_container_assembles_mock_services(container: ServiceContainer) -> None:
    """mock 配置下，容器装配出 Mock 实现，且实现了抽象接口。"""
    assert isinstance(container.llm_service, MockLLMService)
    assert isinstance(container.image_service, MockImageService)
    assert isinstance(container.llm_service, LLMService)
    assert isinstance(container.image_service, ImageService)


def test_unsupported_provider_raises_clear_error(settings: Settings) -> None:
    """配置了暂不支持的 provider 时，给出清晰的中文错误提示而不是静默失败。"""
    unsupported = settings.model_copy(update={"llm_provider": "openai"})

    with pytest.raises(ValueError) as excinfo:
        ServiceContainer.build(unsupported)

    message = str(excinfo.value)
    assert "openai" in message
    assert "mock" in message


# ---------------------------------------------------------------------------
# MockLLMService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_topics_returns_three_to_five_topics(container: ServiceContainer) -> None:
    """选题数量必须落在 3–5 之间，且返回的是领域模型对象。"""
    topics = await container.llm_service.plan_topics(DIRECTION)

    assert 3 <= len(topics) <= 5
    assert all(isinstance(topic, TopicCandidate) for topic in topics)
    # id 必须唯一，否则人工选题时无法区分
    assert len({topic.id for topic in topics}) == len(topics)
    # 每个字段都要有内容
    assert all(topic.title and topic.angle and topic.reason for topic in topics)


@pytest.mark.asyncio
async def test_plan_topics_is_deterministic(container: ServiceContainer) -> None:
    """同一个内容方向重复调用，结果完全一致（Mock 必须可复现，不能随机）。"""
    first = await container.llm_service.plan_topics(DIRECTION)
    second = await container.llm_service.plan_topics(DIRECTION)

    assert first == second


@pytest.mark.asyncio
async def test_plan_topics_depends_on_direction(container: ServiceContainer) -> None:
    """内容方向不同，生成的选题也应不同，且方向关键词会体现在标题里。"""
    first = await container.llm_service.plan_topics(DIRECTION)
    second = await container.llm_service.plan_topics("新手如何准备 AI 训练师面试")

    assert first != second
    assert all(DIRECTION in topic.title for topic in first)
    assert all("AI 训练师" in topic.title for topic in second)


@pytest.mark.asyncio
async def test_write_article_is_structured_and_mentions_topic(container: ServiceContainer) -> None:
    """模拟文章结构清晰：有标题、有小标题、有代码块，并且引用了选题信息。"""
    topic = (await container.llm_service.plan_topics(DIRECTION))[0]

    article = await container.llm_service.write_article(topic)

    assert isinstance(article, str)
    assert topic.title in article
    assert topic.angle in article
    # 至少 3 个二级标题，保证文章是分层的
    assert article.count("\n## ") >= 3
    # 至少一个代码块围栏
    assert article.count("```") >= 2
    assert len(article) > 300


@pytest.mark.asyncio
async def test_write_article_is_deterministic(container: ServiceContainer) -> None:
    """无 feedback 时，重复调用生成同一篇文章。"""
    topic = (await container.llm_service.plan_topics(DIRECTION))[0]

    first = await container.llm_service.write_article(topic)
    second = await container.llm_service.write_article(topic)

    assert first == second


@pytest.mark.asyncio
async def test_write_article_reflects_feedback(container: ServiceContainer) -> None:
    """带 feedback 时，文章内容必须体现修改要求，且与初稿不同。"""
    topic = (await container.llm_service.plan_topics(DIRECTION))[0]
    feedback = "第二段缺少代码示例，请补充一个最小可运行例子"

    first_draft = await container.llm_service.write_article(topic)
    revised = await container.llm_service.write_article(topic, feedback=feedback)

    assert revised != first_draft
    assert feedback in revised
    assert "修订" in revised


@pytest.mark.asyncio
async def test_extract_visual_points_returns_three_to_five_ordered_points(
    container: ServiceContainer,
) -> None:
    """视觉要点数量 3–5，order 从 1 连续递增，id 唯一，prompt 非空。"""
    topic = (await container.llm_service.plan_topics(DIRECTION))[0]
    article = await container.llm_service.write_article(topic)

    points = await container.llm_service.extract_visual_points(article)

    assert 3 <= len(points) <= 5
    assert all(isinstance(point, VisualPoint) for point in points)
    assert [point.order for point in points] == list(range(1, len(points) + 1))
    assert len({point.id for point in points}) == len(points)
    assert all(point.title and point.point and point.prompt for point in points)


@pytest.mark.asyncio
async def test_extract_visual_points_is_deterministic(container: ServiceContainer) -> None:
    """同一篇文章重复提炼，结果完全一致。"""
    article = "# 测试文章\n\n正文内容……"

    first = await container.llm_service.extract_visual_points(article)
    second = await container.llm_service.extract_visual_points(article)

    assert first == second


# ---------------------------------------------------------------------------
# MockImageService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_image_service_returns_valid_asset(container: ServiceContainer) -> None:
    """生图返回结构合法的 ImageAsset：成功态、有 URL、可见 visual_point_id。"""
    asset = await container.image_service.generate(
        prompt="知识卡片：什么是检查点，扁平插画风格",
        size="1024x1024",
        visual_point_id="vp1",
    )

    assert isinstance(asset, ImageAsset)
    assert asset.status is ImageAssetStatus.SUCCESS
    assert asset.visual_point_id == "vp1"
    assert asset.url is not None and asset.url.startswith("https://")
    assert asset.url.endswith("vp1.png")
    assert asset.error is None


@pytest.mark.asyncio
async def test_mock_image_service_is_deterministic_and_addressable_by_point_id(
    container: ServiceContainer,
) -> None:
    """模拟 URL 稳定，且不同视觉要点得到不同地址（并发结果可按 id 定位）。"""
    first = await container.image_service.generate(prompt="提示词 A", size="1024x1024", visual_point_id="vp1")
    second = await container.image_service.generate(prompt="提示词 A", size="1024x1024", visual_point_id="vp1")
    other = await container.image_service.generate(prompt="提示词 B", size="1024x1024", visual_point_id="vp2")

    assert first == second
    assert first.url != other.url


# ---------------------------------------------------------------------------
# 不联网 / 不依赖密钥与数据库
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_services_never_touch_the_network(
    container: ServiceContainer, no_network: None
) -> None:
    """在禁用 socket 的情况下跑完整条 Mock 链路，证明没有任何网络访问。

    no_network 夹具会把 socket 的连接方法替换成抛错函数，
    所以只要有一行代码试图联网，这个测试就会失败。
    """
    topics = await container.llm_service.plan_topics(DIRECTION)
    article = await container.llm_service.write_article(topics[0], feedback="请补充示例")
    points = await container.llm_service.extract_visual_points(article)
    assets = [
        await container.image_service.generate(
            prompt=point.prompt, size="1024x1024", visual_point_id=point.id
        )
        for point in points
    ]

    assert len(assets) == len(points)
    assert all(asset.status is ImageAssetStatus.SUCCESS for asset in assets)


def test_mock_mode_requires_no_secrets_and_no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """在没有任何密钥/数据库环境变量的情况下，配置与容器依然可用。

    做法：先删掉可能存在的相关环境变量，再构造 Settings 并装配容器。
    如果 S1 阶段真的依赖密钥，这里就会抛错。
    """
    for variable in (
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "IMAGE_API_KEY",
        "DATABASE_URL",
        "POSTGRES_DSN",
    ):
        monkeypatch.delenv(variable, raising=False)

    safe_settings = Settings(_env_file=None)
    built = ServiceContainer.build(safe_settings)

    assert isinstance(built.llm_service, MockLLMService)
    assert isinstance(built.image_service, MockImageService)

    # Settings 里不允许存在「必填且无默认值」的字段——那通常意味着需要额外凭据
    required_fields = [
        name for name, field in Settings.model_fields.items() if field.is_required()
    ]
    assert required_fields == []

    # 也不允许出现名字里带密钥/数据库含义的字段
    forbidden_keywords = ("key", "token", "secret", "password", "database", "dsn")
    suspicious = [
        name
        for name in Settings.model_fields
        if any(keyword in name.lower() for keyword in forbidden_keywords)
    ]
    assert suspicious == []
