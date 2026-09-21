"""应用配置：从环境变量 / .env 文件读取配置，并做类型校验。

============================================================================
为什么要有这一层？
============================================================================
如果代码各处直接写 ``os.environ.get("APP_NAME")``，会带来三个问题：

1. **类型不安全**：环境变量永远是字符串，``MAX_REVISIONS`` 拿到的是 "3" 而不是 3。
2. **分散难查**：到底支持哪些配置项，只能靠全局搜索。
3. **缺少校验**：写错了配置名，程序不会报错，只会静默使用默认值。

使用 pydantic-settings 之后，所有配置集中在一个类里声明：

- 字段名自动映射为大写的环境变量名（``app_name`` ← ``APP_NAME``）
- 自动完成类型转换（"3" → 3）
- 非法值直接抛错，启动即失败，不会带到线上

============================================================================
优先级（从高到低）
============================================================================
    初始化参数 > 环境变量 > .env 文件 > 字段默认值
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Final

from pydantic import Field, model_validator

# BaseSettings 是 pydantic-settings 提供的基础类：在普通 BaseModel 之上
# 增加了「从环境变量 / .env 文件读取值」的能力。
# SettingsConfigDict 用来声明配置行为（读哪个文件、编码、未知字段怎么办等）。
from pydantic_settings import BaseSettings, SettingsConfigDict

# 当前支持的检查点后端。定义在这里而不是 checkpointer.py，
# 是为了让「配置合法性校验」与「后端实现」互不依赖（后者会 import Settings，
# 反向 import 会形成环）。
SUPPORTED_CHECKPOINTER_BACKENDS: Final[tuple[str, ...]] = ("memory", "postgres")


class Settings(BaseSettings):
    """应用配置。

    所有字段都给了默认值，因此：

    - 只跑 Mock 服务时，**不需要任何密钥，也不需要数据库连接**；
    - 缺参数不会导致启动失败，本地开箱即用。
    """

    # model_config 是 Pydantic v2 的写法（v1 里叫 class Config）。
    # 它只影响「模型如何被构建」，不会成为一个字段。
    model_config = SettingsConfigDict(
        # 从当前工作目录下的 .env 文件读取变量；文件不存在也不会报错
        env_file=".env",
        env_file_encoding="utf-8",
        # 大小写不敏感：.env 里的 APP_NAME 和 app_name 都能映射到 app_name 字段
        case_sensitive=False,
        # 忽略 .env 里存在但本类没声明的变量。
        # 这样以后往 .env 里加新变量，旧代码不会因为「多出来一个字段」而启动失败。
        extra="ignore",
    )

    # ---------------- 应用基础信息 ----------------
    app_name: str = Field(
        default="自媒体内容运营 AI 智能体",
        description="应用名称，用于 /health 响应与 FastAPI 文档标题",
    )
    app_env: str = Field(
        default="local",
        description="运行环境标识，例如 local / test / prod",
    )

    # ---------------- AI 服务提供方 ----------------
    # 注意：这里声明为 str 而不是 Literal["mock"]，是为了让「不支持的取值」
    # 在服务容器装配时给出**中文的清晰错误**（见 app/services/container.py），
    # 而不是抛出难懂的英文校验错误。
    llm_provider: str = Field(
        default="mock",
        description="文本模型提供方；S1 阶段仅支持 mock，真实模型在 S7 阶段接入",
    )
    image_provider: str = Field(
        default="mock",
        description="图片模型提供方；S1 阶段仅支持 mock，真实模型在 S8 阶段接入",
    )

    # ---------------- 业务参数 ----------------
    max_revisions: int = Field(
        default=3,
        ge=0,  # ge = greater than or equal，大于等于 0
        le=10,  # le = less than or equal，小于等于 10
        description="文章最多允许被人工驳回重写的次数；达到上限后只能人工通过",
    )

    # ---------------- 跨源访问（S4 前端联调） ----------------
    cors_allow_origins: str = Field(
        default="http://localhost:5173",
        description=(
            "允许跨源调用本服务的前端来源，多个来源用英文逗号分隔。"
            "默认只放行 Vite 开发服务器；留空字符串表示完全不启用 CORS。"
            "不要填 *：本服务允许携带凭证，浏览器禁止二者同时使用。"
        ),
    )

    @property
    def cors_allow_origins_list(self) -> list[str]:
        """把逗号分隔的来源字符串解析成列表。

        为什么用 str + 属性，而不是直接声明 ``list[str]``？
            pydantic-settings 对 ``list[str]`` 字段会把环境变量当成 **JSON** 解析，
            写成 ``A,B`` 会直接启动失败，对运维很不友好。
            用字符串声明、再用本属性切分，既保留配置灵活性，
            又给出「逗号分隔」这种最容易理解的书写方式。

        返回:
            list[str]: 去空白、去空项后的来源列表；配置为空时返回空列表
                （main.py 据此**完全不注册** CORS 中间件）。
        """
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    # ---------------- 检查点存储（S5） ----------------
    # 同样声明为 str 而非 Literal，理由见上方 llm_provider 的注释：
    # 非法取值要在校验器里给出中文的清晰错误，而不是英文的类型错误。
    checkpointer_backend: str = Field(
        default="memory",
        description=(
            "检查点存储后端：memory（进程内，重启即丢）或 postgres（持久化）。"
            "默认 memory，因此本地开发与跑测试都不需要数据库。"
        ),
    )
    postgres_uri: str = Field(
        default="",
        description=(
            "PostgreSQL 连接串，仅 checkpointer_backend=postgres 时必填。"
            "格式：postgresql://用户:口令@主机:端口/库名。"
            "**不要把真实口令写进代码或提交到仓库**，本地填入 .env 即可（.env 已被忽略）。"
        ),
    )
    postgres_pool_min_size: int = Field(
        default=1,
        ge=1,
        le=50,
        description="连接池最小连接数；启动时会立即建立这么多连接，因此配大了会拖慢启动",
    )
    postgres_pool_max_size: int = Field(
        default=10,
        ge=1,
        le=50,
        description="连接池最大连接数；并发会话数超过它时，后来的请求会在池上排队等待",
    )

    @property
    def resolved_checkpointer_backend(self) -> str:
        """归一化后的后端名（去空白、转小写）。

        容忍 ``"Postgres"`` / ``" memory "`` 这类写法，
        避免因为大小写或空格导致启动失败。
        """
        return self.checkpointer_backend.strip().lower()

    @property
    def redacted_postgres_uri(self) -> str:
        """用于**日志输出**的连接串，口令已替换为 ``***``。

        连接串里通常含有数据库口令。启动日志、错误信息一旦原样打印它，
        口令就会进日志文件、进 CI 输出、进截图。因此对外只暴露本属性，
        不直接使用 ``postgres_uri``。

        返回:
            str: 形如 ``postgresql://user:***@host:5432/db``；
                未配置时返回空字符串。
        """
        if not self.postgres_uri:
            return ""
        # 匹配 URI 里 "口令@" 之前的部分：scheme://user:password@
        # 只替换口令段，保留用户名/主机/库名，方便排查「连错库」这类问题。
        # 用户名用 * 而非 +：postgresql://:口令@主机 这种「只有口令没有用户名」
        # 的写法也要能脱敏（libpq 允许省略用户名）。
        return re.sub(r"(://[^:/@]*:)[^@]*(@)", r"\1***\2", self.postgres_uri)

    @model_validator(mode="after")
    def _validate_checkpointer(self) -> Settings:
        """校验检查点相关配置的组合合法性。

        为什么放在校验器里而不是等到创建 Checkpointer 时再判断？
            这是**配置本身的矛盾**（说要用 postgres 却没给连接串），
            属于「启动即失败」的范畴。放在这里，进程在读完配置的那一刻就报错，
            不会出现「服务已经起来了，第一个请求进来才发现连不上库」。

        为什么要求 model_validator(mode="after")？
            要同时看多个字段（backend + uri + 池大小），
            只有 after 模式才能拿到已经填好默认值的完整对象。

        异常:
            ValueError: 后端取值不支持、postgres 模式缺 URI、或池大小区间颠倒
        """
        backend = self.resolved_checkpointer_backend

        if backend not in SUPPORTED_CHECKPOINTER_BACKENDS:
            raise ValueError(
                f"不支持的 checkpointer_backend：{self.checkpointer_backend!r}。"
                f"可选值：{', '.join(SUPPORTED_CHECKPOINTER_BACKENDS)}。"
            )

        if backend == "postgres" and not self.postgres_uri.strip():
            # 刻意**不回退到 memory**：配置说要持久化却不给库，
            # 静默降级会让「重启后会话还在」这个承诺悄悄失效，
            # 等到线上重启才发现就太晚了。这里必须硬失败。
            raise ValueError(
                "checkpointer_backend=postgres 时必须提供 postgres_uri。"
                "请在 .env 中设置 POSTGRES_URI=postgresql://用户:口令@主机:端口/库名"
                "（注意不要把真实口令写进代码或提交到仓库）。"
            )

        if self.postgres_pool_min_size > self.postgres_pool_max_size:
            raise ValueError(
                f"postgres_pool_min_size（{self.postgres_pool_min_size}）"
                f"不能大于 postgres_pool_max_size（{self.postgres_pool_max_size}）。"
            )

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局唯一的配置对象（单例）。

    ``@lru_cache(maxsize=1)`` 是 Python 标准库 functools 提供的装饰器，
    作用是「缓存函数返回值」：第一次调用会真正执行函数体，
    之后所有调用都直接返回缓存结果。

    为什么需要单例？
        每次请求都重新读文件、解析环境变量是浪费；
        而且单例能保证整个进程用的是同一份配置。

    为什么不用模块级全局变量？
        模块级变量在「导入时」就执行，测试里想替换配置会非常麻烦；
        用函数 + 缓存则可以在测试中通过 ``get_settings.cache_clear()`` 重置。

    返回:
        Settings: 配置对象实例

    """
    return Settings()
