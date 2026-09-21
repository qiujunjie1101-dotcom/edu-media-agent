"""检查点（Checkpoint）存储的创建与生命周期管理。

============================================================================
检查点是干什么的？
============================================================================
LangGraph 每执行完一个「超级步」就把状态快照写进检查点存储，于是：

- ``interrupt()`` 才能生效——暂停时靠检查点记住「停在哪、状态是什么」；
- 恢复时才能从终点继续，而不是从头再来；
- ``aget_state_history()`` 才能回溯每一步。

============================================================================
两种后端
============================================================================

``InMemorySaver``（默认）
    检查点存在进程内存里：无需数据库、开箱即用，适合开发与单元测试。
    局限是**进程重启即丢失**——这正是 S5 要解决的问题。

``AsyncPostgresSaver``
    检查点写进 PostgreSQL，重启后凭 ``thread_id`` 仍能恢复现场。

由 ``CHECKPOINTER_BACKEND`` 环境变量二选一。

============================================================================
为什么把「存储」和「连接池」打包成一个资源对象？
============================================================================
``AsyncPostgresSaver`` 自己不持有连接池，它只是在每次读写时从**外部传进来的**
池里借一条连接。池的生命周期必须比图更长——它要在应用启动时创建、
在应用关闭时释放，而不是每个请求建一个。把这个归属关系写进
``CheckpointerResource`` 之后，调用方只有一条规则要守：

    **创建一次，随应用一起关闭。**

如果只返回 saver 而把池藏在闭包里，关闭时机就没人负责了。

============================================================================
本模块不做什么
============================================================================
只做「存储介质」的装配。检查点表的表结构由 ``AsyncPostgresSaver.setup()``
用 LangGraph 自带的迁移维护，**不要**在这里建业务表——
``workflow_session`` / ``content_artifact`` / ``review_log`` 属于 S6。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import SUPPORTED_CHECKPOINTER_BACKENDS, Settings

# ---------------------------------------------------------------------------
# PostgreSQL 连接参数
# ---------------------------------------------------------------------------

# 启动时等待连接池就绪的上限。等不到就启动失败——这是刻意的：
# 「库连不上」必须在启动阶段暴露，而不是等第一个请求进来才发现。
POOL_OPEN_TIMEOUT_SECONDS: Final[float] = 15.0

# 关闭连接池时等待现有连接归还的上限，超时则强制断开。
POOL_CLOSE_TIMEOUT_SECONDS: Final[float] = 5.0


def _postgres_connection_kwargs() -> dict[str, Any]:
    """每条池连接都要带的参数。

    这里的取值不是猜的，而是**照抄库自己的实现**：
    langgraph-checkpoint-postgres 3.1.2 的 ``AsyncPostgresSaver.from_conn_string``
    内部就是::

        AsyncConnection.connect(conn_string, autocommit=True,
                                prepare_threshold=0, row_factory=dict_row)

    用连接池时这些参数**不会自动继承**，必须在池的 ``kwargs`` 里显式声明，
    否则行为会与被库自身测试过的单连接路径不一致。

        autocommit=True
            saver 的写入依赖自动提交。关掉的话，连接归还到池时事务会被回滚，
            检查点看起来写成功了，实际没落库。
        prepare_threshold=0
            与库自身保持一致（控制何时把语句转为服务端预编译语句）。
        row_factory=dict_row
            ``setup()`` 里有 ``row["v"]`` 这种按键取值，用默认的元组行会抛
            TypeError。

    为什么写成函数而不是模块级常量？
        延迟导入 psycopg，让 memory 模式（本地开发与绝大多数单元测试）
        **完全不依赖 psycopg 是否安装**。这样即便有人只装了最小依赖集，
        应用也能以 memory 模式正常导入和启动。
    """
    from psycopg.rows import dict_row

    return {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
    }


@dataclass
class CheckpointerResource:
    """检查点存储，以及它需要随应用一起关闭的外部资源。

    字段:
        saver: 传给 ``graph.compile(checkpointer=...)`` 的检查点存储
        backend: 实际生效的后端名（``memory`` / ``postgres``），
            供 ``/health`` 等对外展示，**不含任何连接信息**
        pool: PostgreSQL 连接池；memory 模式下为 ``None``

    """

    saver: BaseCheckpointSaver
    backend: str
    pool: Any | None = None

    @property
    def holds_pool(self) -> bool:
        """是否持有需要显式关闭的连接池。"""
        return self.pool is not None

    async def aclose(self) -> None:
        """释放连接池。可重复调用，重复调用是安全的。

        memory 模式下是空操作；postgres 模式下关闭池并把引用置空，
        这样再次调用不会去关一个已经关掉的池。
        """
        if self.pool is None:
            return
        pool, self.pool = self.pool, None
        await pool.close(timeout=POOL_CLOSE_TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------


async def create_checkpointer(settings: Settings) -> CheckpointerResource:
    """按配置创建检查点存储。

    这是本模块**唯一**对外的入口。配置文件里 ``CHECKPOINTER_BACKEND``
    写什么，这里就装配什么，不做任何静默回退。

    参数:
        settings: 应用配置（其中的 ``postgres_pool_*`` 等决定池的行为）

    返回:
        CheckpointerResource: 已就绪的存储；postgres 模式下其连接池已打开、
            表结构已迁移完毕，可以直接用于构图

    异常:
        ValueError: 后端取值不在支持列表内
        RuntimeError: postgres 模式下连接失败或迁移失败（消息中的连接串已脱敏）

    """
    backend = settings.resolved_checkpointer_backend

    if backend == "memory":
        return CheckpointerResource(saver=InMemorySaver(), backend="memory")

    if backend == "postgres":
        return await _create_postgres_checkpointer(settings)

    # 配置校验（Settings 的 model_validator）已经拦过一道，
    # 这里再判一次是防御性的：万一有人绕过校验直接构造 Settings，
    # 也不该拿到一个「不知道什么后端」的存储。
    raise ValueError(
        f"不支持的 checkpointer_backend：{settings.checkpointer_backend!r}。"
        f"可选值：{', '.join(SUPPORTED_CHECKPOINTER_BACKENDS)}。"
    )


async def _create_postgres_checkpointer(settings: Settings) -> CheckpointerResource:
    """创建 PostgreSQL 检查点存储：开池 → 迁移表结构 → 交付。

    三个关键点:

    1. **池只创建一次**。本函数在应用 lifespan 里被调用一次，
       返回的对象由应用持有；任何路径都不该在每个请求里重新调它。
    2. **迁移可重复执行**。``setup()`` 内部读 ``checkpoint_migrations``
       的最大版本号，只补跑增量迁移；已存在的检查点不会被清空或重建。
       因此每次启动都调它是安全且必要的（版本升级后要靠它补表结构）。
    3. **失败即启动失败**。连不上库或迁移出错时，先关掉半开着的池再抛出，
       绝不退回 memory——静默降级会让「重启后会话还在」这个承诺
       悄悄失效，等线上重启才发现就太晚了。
    """
    # 延迟导入：memory 模式（本地开发与绝大多数单元测试）完全不需要
    # psycopg / psycopg_pool，只在真的要用 postgres 时才付出这个导入成本。
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    redacted = settings.redacted_postgres_uri

    pool = AsyncConnectionPool(
        conninfo=settings.postgres_uri,
        min_size=settings.postgres_pool_min_size,
        max_size=settings.postgres_pool_max_size,
        kwargs=_postgres_connection_kwargs(),
        # open=False 是刻意的：构造时不建立任何连接，
        # 由下面显式 open(wait=True) 完成，这样「哪一步可能失败」是明确的。
        open=False,
    )

    try:
        await pool.open(wait=True, timeout=POOL_OPEN_TIMEOUT_SECONDS)

        saver = AsyncPostgresSaver(conn=pool)
        # 表结构迁移。幂等：已存在的表与检查点都不受影响。
        await saver.setup()
    except Exception as exc:  # noqa: BLE001 —— 任何失败都归为「启动失败」
        # 半开的池必须先释放，否则会留下后台连接与工作线程
        await pool.close(timeout=POOL_CLOSE_TIMEOUT_SECONDS)
        raise RuntimeError(
            f"初始化 PostgreSQL 检查点存储失败（{redacted}，"
            f"池大小 {settings.postgres_pool_min_size}-{settings.postgres_pool_max_size}）："
            f"{type(exc).__name__}。"
            "请确认 PostgreSQL 已启动、库已创建、连接串与口令正确；"
            "本服务不会回退到 memory 模式。"
        ) from exc

    return CheckpointerResource(saver=saver, backend="postgres", pool=pool)
