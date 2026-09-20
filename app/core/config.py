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

from functools import lru_cache

from pydantic import Field

# BaseSettings 是 pydantic-settings 提供的基础类：在普通 BaseModel 之上
# 增加了「从环境变量 / .env 文件读取值」的能力。
# SettingsConfigDict 用来声明配置行为（读哪个文件、编码、未知字段怎么办等）。
from pydantic_settings import BaseSettings, SettingsConfigDict


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
