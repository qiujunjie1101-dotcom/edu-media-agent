"""MockLLMService：确定性的假文本模型，用于 S1–S6 阶段开发与测试。

============================================================================
为什么需要 Mock？
============================================================================
真实大模型有三个特点：要花钱、有网络延迟、每次输出都不一样。
在流程尚未跑通时，这三个特点都会成为干扰。Mock 的目标是：

1. **确定性**：同样的输入永远得到同样的输出，测试才能写断言。
2. **不联网**：本地即可开发，无需 API Key。
3. **结构真实**：返回的数据形状与真实模型完全一致，将来替换时上层无感。

实现方式：用 ``zlib.crc32`` 把输入字符串算成一个稳定的整数「种子」，
再用它来选择模板。crc32 是纯计算、无随机、跨进程稳定，
所以「同输入 → 同输出」这条性质可以被测试严格验证。
"""

from __future__ import annotations

import zlib

from app.schemas.domain import TopicCandidate, VisualPoint
from app.services.llm.base import LLMService

# ---------------------------------------------------------------------------
# 选题生成用的模板
# ---------------------------------------------------------------------------

# 候选选题的数量在 3–5 之间变化，由种子决定，从而模拟「模型有时给 3 个、有时给 5 个」
_TOPIC_COUNT_CHOICES = (3, 4, 5)

# 写作角度模板（与领域模型 TopicCandidate.angle 的语义对应）
_TOPIC_ANGLES = (
    "原理拆解",
    "实战演练",
    "避坑指南",
    "对比选型",
    "学习路线",
)

# 标题模板：与角度一一对应，凑成一个完整、可读的选题
_TOPIC_TITLE_TEMPLATES = (
    "先搞懂它到底解决什么问题",
    "一次完整的动手实践",
    "新手最容易踩的 3 个坑",
    "和其它方案比到底差在哪",
    "一条可以直接照做的学习路线",
)

# ---------------------------------------------------------------------------
# 视觉要点生成用的模板
# ---------------------------------------------------------------------------

_VISUAL_POINT_COUNT_CHOICES = (3, 4, 5)

_VISUAL_POINT_TITLES = (
    "核心结论",
    "关键概念",
    "动手步骤",
    "常见误区",
    "一句话总结",
)


def _stable_seed(text: str, salt: str) -> int:
    """把任意字符串转换成稳定的整数种子。

    参数:
        text: 原始文本（例如内容方向或文章正文）
        salt: 盐值，用来让不同用途的种子互不干扰
              （同一段文字用于选题和用于视觉要点时，应该得到不同结果）

    返回:
        int: 非负整数种子，直接用于取模挑选模板

    说明:
        使用 ``zlib.crc32`` 而不是内置的 ``hash()``：
        Python 为了安全，会给字符串的 hash 加随机盐（PYTHONHASHSEED），
        导致同一个字符串在两次运行中 hash 值不同，破坏「确定性」这条要求。
        crc32 则是纯函数，跨进程、跨机器结果一致。
    """
    return zlib.crc32(f"{salt}::{text}".encode())


def _first_heading(text: str) -> str:
    """取出 Markdown 文本中的第一个标题，用作其它生成的上下文。

    例如 "# 检查点到底存了什么\\n\\n正文……" → "检查点到底存了什么"。
    找不到标题时退化为正文前 20 个字符，保证返回值不为空。
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            # lstrip("# ") 会去掉开头所有的 # 和空格
            heading = stripped.lstrip("# ").strip()
            if heading:
                return heading

    fallback = text.strip()[:20]
    return fallback or "未命名主题"


class MockLLMService(LLMService):
    """确定性的假文本模型实现。

    它不持有任何网络客户端，因此天然满足「Mock 模式不需要密钥、不联网」的约束。
    """

    async def plan_topics(self, direction: str) -> list[TopicCandidate]:
        """生成 3–5 个候选选题，标题中会带上内容方向，便于人工判断相关性。"""
        seed = _stable_seed(direction, salt="topics")
        count = _TOPIC_COUNT_CHOICES[seed % len(_TOPIC_COUNT_CHOICES)]

        topics: list[TopicCandidate] = []
        for index in range(count):
            # 用 (seed + index) 取模，保证同一批选题里的角度与模板不重复
            position = seed + index
            title_template = _TOPIC_TITLE_TEMPLATES[position % len(_TOPIC_TITLE_TEMPLATES)]
            angle = _TOPIC_ANGLES[position % len(_TOPIC_ANGLES)]

            topics.append(
                TopicCandidate(
                    # id 采用 t1、t2 …… 稳定且可读，人工选题时回传这个 id 即可
                    id=f"t{index + 1}",
                    title=f"{direction}：{title_template}",
                    angle=angle,
                    reason=(
                        f"围绕「{direction}」，用「{title_template}」这个角度切入，"
                        f"适合培训机构的学员，也便于后续拆成小红书知识卡片。"
                    ),
                )
            )

        return topics

    async def write_article(self, topic: TopicCandidate, feedback: str | None = None) -> str:
        """生成结构清晰的技术文章；带 feedback 时按其重写。

        文章固定包含：一级标题、导语、五个二级小节、一个代码块。
        """
        sections: list[str] = [
            f"# {topic.title}",
            "",
            f"> 写作角度：{topic.angle} ｜ 选题理由：{topic.reason}",
            "",
        ]

        # 有修改意见时，在正文最前面插入一段透明的「修订说明」。
        # 这样测试可以断言「feedback 确实影响了输出」，运营人员也能一眼看到本轮改了什么。
        if feedback:
            sections.extend(
                [
                    "## 修订说明",
                    "",
                    "本文为根据人工审核意见重写的版本，本轮需要落实的修改要求是：",
                    "",
                    f"> {feedback}",
                    "",
                ]
            )

        sections.extend(
            [
                "## 一、为什么值得先搞懂这件事",
                "",
                f"很多同学第一次接触「{topic.title}」时，会直接跳到命令行操作，"
                "结果遇到报错就不知道从哪查起。先建立整体图景，再动手，效率会高很多。",
                "",
                "## 二、核心概念速览",
                "",
                "用三句话概括：",
                "",
                "1. 它解决的是「中途失败怎么办」的问题；",
                "2. 关键动作是「把每一步的状态保存下来」；",
                "3. 恢复时从最近一次保存点继续，而不是从头再来。",
                "",
                "## 三、动手实践",
                "",
                "下面是一个最小可运行示例：",
                "",
                "```python",
                "# 示意代码：演示最小可运行结构",
                "def run(task: str) -> str:",
                '    """执行任务并返回结果（示例）。"""',
                '    print(f"开始处理：{task}")',
                '    return "done"',
                "",
                'if __name__ == "__main__":',
                '    print(run("示例任务"))',
                "```",
                "",
                "## 四、常见误区",
                "",
                "- 误区一：以为保存点越频繁越好。实际上过密会拖慢主流程；",
                "- 误区二：把不可序列化的对象塞进状态里；",
                "- 误区三：失败后只看日志，不检查保存点是否真正写入。",
                "",
                "## 五、小结与练习",
                "",
                f"小结：理解「{topic.title}」的关键是抓住「状态 + 恢复」这条主线。",
                "",
                "练习：把上面的示例改造成可以中断并继续的版本，观察两次运行输出的差异。",
                "",
            ]
        )

        return "\n".join(sections)

    async def extract_visual_points(self, article: str) -> list[VisualPoint]:
        """把文章提炼成 3–5 个视觉要点，每条都附带生图提示词。"""
        heading = _first_heading(article)
        seed = _stable_seed(article, salt="visuals")
        count = _VISUAL_POINT_COUNT_CHOICES[seed % len(_VISUAL_POINT_COUNT_CHOICES)]

        points: list[VisualPoint] = []
        for index in range(count):
            position = seed + index
            title = _VISUAL_POINT_TITLES[position % len(_VISUAL_POINT_TITLES)]

            points.append(
                VisualPoint(
                    id=f"vp{index + 1}",
                    # order 从 1 开始连续递增，对应小红书图文里的第几张卡片
                    order=index + 1,
                    title=title,
                    point=f"{title}：关于「{heading}」，这一张卡片只讲清一个要点。",
                    prompt=(
                        f"小红书知识卡片，竖版 3:4，主题「{heading}」，"
                        f"核心要点「{title}」，扁平插画风格，浅色背景，中文标题清晰可读"
                    ),
                )
            )

        return points
