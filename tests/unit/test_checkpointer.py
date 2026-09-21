"""检查点存储的配置校验与工厂行为（S5）。

============================================================================
本文件不接触 PostgreSQL
============================================================================
这里只验证「配置怎么说、工厂就怎么装配」以及各种非法组合是否被拦住。
真正连库的行为在 ``tests/integration/test_postgres_checkpointer.py``，
那一组需要 ``TEST_POSTGRES_URI``，没有就 skip。

这样切分的原因：默认（memory）路径必须是**零依赖**的——
任何人 clone 下来跑 ``pytest`` 都该全绿，不需要先装一个数据库。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import SUPPORTED_CHECKPOINTER_BACKENDS, Settings
from app.graph.checkpointer import CheckpointerResource, create_checkpointer

# 注意：这里**不设全局 pytestmark**——本文件多数用例是同步的配置校验，
# 全局打上 asyncio 标记会让它们全部报 PytestWarning。
# 异步用例各自按需标记。


# ---------------------------------------------------------------------------
# 配置校验
# ---------------------------------------------------------------------------


def test_default_backend_is_memory() -> None:
    """不配置时默认 memory——本地开发与跑测试都不该被迫准备数据库。"""
    settings = Settings(_env_file=None)

    assert settings.resolved_checkpointer_backend == "memory"
    assert settings.postgres_uri == ""
    assert (settings.postgres_pool_min_size, settings.postgres_pool_max_size) == (1, 10)


def test_memory_mode_does_not_require_uri() -> None:
    """memory 模式不要求 postgres_uri，且**完全不去读它**。

    用一个明显非法的连接串来证明「没读」：
    如果实现里任何一处提前校验或解析了它，这里就会失败。
    """
    settings = Settings(
        _env_file=None,
        checkpointer_backend="memory",
        postgres_uri="这不是一个合法的连接串://随便写的",
    )

    assert settings.resolved_checkpointer_backend == "memory"


@pytest.mark.parametrize("backend", ["memory", " MEMORY ", "Memory"])
def test_backend_name_is_normalized(backend: str) -> None:
    """后端名容忍大小写与首尾空格，避免因为这些细节导致启动失败。"""
    settings = Settings(_env_file=None, checkpointer_backend=backend)

    assert settings.resolved_checkpointer_backend == "memory"


def test_postgres_mode_requires_uri() -> None:
    """选了 postgres 却不给连接串 → 构建配置时就要失败。

    这是刻意的**硬失败**：静默退回 memory 会让「重启后会话还在」
    这个承诺悄悄失效，等到线上重启才发现就太晚了。
    """
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, checkpointer_backend="postgres")

    assert "postgres_uri" in str(excinfo.value)
    assert "不会回退到 memory" in str(excinfo.value) or "必须提供" in str(excinfo.value)


def test_postgres_mode_with_blank_uri_also_fails() -> None:
    """只写了空白字符不算「提供了连接串」。"""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, checkpointer_backend="postgres", postgres_uri="   ")


def test_unsupported_backend_is_rejected() -> None:
    """不支持的取值必须被拒绝，并列出可选值。"""
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, checkpointer_backend="sqlite")

    message = str(excinfo.value)
    assert "sqlite" in message
    for supported in SUPPORTED_CHECKPOINTER_BACKENDS:
        assert supported in message


def test_pool_min_greater_than_max_is_rejected() -> None:
    """池大小区间颠倒属于配置矛盾，应在启动前拦下。"""
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, postgres_pool_min_size=20, postgres_pool_max_size=5)

    assert "postgres_pool_max_size" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 连接串脱敏
# ---------------------------------------------------------------------------


def test_redacted_uri_hides_password() -> None:
    """对外输出的连接串必须把口令换成 ``***``，其余部分保留以便排查。"""
    settings = Settings(
        _env_file=None,
        postgres_uri="postgresql://appuser:sup3r-s3cret@db.internal:5432/langgraph",
    )

    redacted = settings.redacted_postgres_uri

    assert "sup3r-s3cret" not in redacted
    assert redacted == "postgresql://appuser:***@db.internal:5432/langgraph"


def test_redacted_uri_is_empty_when_unset() -> None:
    """没配连接串时返回空串，不要造出一个看起来像样的假地址。"""
    assert Settings(_env_file=None).redacted_postgres_uri == ""


def test_redacted_uri_handles_password_without_username() -> None:
    """没有用户名、只有口令的写法也要能脱敏。"""
    settings = Settings(_env_file=None, postgres_uri="postgresql://:onlypass@host:5432/db")

    assert "onlypass" not in settings.redacted_postgres_uri


# ---------------------------------------------------------------------------
# 工厂（memory 路径）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_factory_builds_in_memory_saver_without_pool() -> None:
    """memory 模式产出 InMemorySaver，且不持有任何需要关闭的资源。"""
    resource = await create_checkpointer(Settings(_env_file=None))

    assert isinstance(resource, CheckpointerResource)
    assert resource.backend == "memory"
    assert type(resource.saver).__name__ == "InMemorySaver"
    assert resource.holds_pool is False
    assert resource.pool is None


@pytest.mark.asyncio
async def test_memory_resource_close_is_safe_to_repeat() -> None:
    """memory 模式的 aclose 必须是空操作，且重复调用不出错。

    应用可能因为启动中途异常而先关一次、再由 finally 关一次，
    重复关闭不能抛异常。
    """
    resource = await create_checkpointer(Settings(_env_file=None))

    await resource.aclose()
    await resource.aclose()


@pytest.mark.asyncio
async def test_factory_rejects_unsupported_backend() -> None:
    """工厂自己也拦一道（防御性）：不依赖调用方一定走过了配置校验。

    Settings 的校验器已经拦过，但绕过校验构造出的对象
    也不该拿到一个「不知道什么后端」的存储。
    """
    # model_construct 绕过校验，模拟「有人绕过 Settings 校验」的情况
    bypassed = Settings.model_construct(checkpointer_backend="sqlite", postgres_uri="")

    with pytest.raises(ValueError, match="sqlite"):
        await create_checkpointer(bypassed)
