"""LLMService 抽象接口：文本模型能力的统一契约。

============================================================================
为什么要先定义抽象接口？
============================================================================
调用方（工作流节点）只依赖这个接口，不关心背后是 Mock 还是真实模型：

    节点 ──依赖──▶ LLMService（抽象）
                        ▲
                        │ 实现
                ┌───────┴────────┐
        MockLLMService      真实实现（S7）

这样「把 Mock 换成真实模型」只需要改一处装配代码，节点一行都不用动。

============================================================================
为什么方法都是 async？
============================================================================
调用大模型本质是「等网络 I/O」，耗时以秒计。如果用同步函数，一个请求就会
把整个线程卡住；写成 ``async def`` 之后，等待期间事件循环可以去处理其他请求，
并发能力显著提升。

注意：抽象方法里不写具体逻辑（用 ``...`` 占位），因此它们只定义「长什么样」。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.domain import TopicCandidate, VisualPoint


class LLMService(ABC):
    """文本模型服务接口。

    继承 ``ABC``（Abstract Base Class，抽象基类）后：

    - 带 ``@abstractmethod`` 的方法必须在子类里全部实现，否则实例化时直接报错；
    - 可以用 ``isinstance(obj, LLMService)`` 判断某个对象是否符合本契约。
    """

    @abstractmethod
    async def plan_topics(self, direction: str) -> list[TopicCandidate]:
        """根据内容方向生成 3–5 个候选选题。

        参数:
            direction: 运营人员输入的内容方向

        返回:
            list[TopicCandidate]: 候选选题列表，数量应为 3–5 个

        """
        ...

    @abstractmethod
    async def write_article(self, topic: TopicCandidate, feedback: str | None = None) -> str:
        """根据选题撰写技术文章；有修改意见时按其重写。

        参数:
            topic: 人工选中的选题
            feedback: 人工驳回时填写的修改意见；初稿时为 None

        返回:
            str: 文章正文（Markdown 格式）

        """
        ...

    @abstractmethod
    async def extract_visual_points(self, article: str) -> list[VisualPoint]:
        """把终稿提炼成 3–5 个适合小红书知识卡片的视觉要点。

        参数:
            article: 已通过人工审核的文章正文

        返回:
            list[VisualPoint]: 视觉要点列表，``order`` 从 1 起连续递增

        """
        ...
