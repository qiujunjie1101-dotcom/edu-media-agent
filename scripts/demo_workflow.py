"""直接驱动 LangGraph 工作流的演示脚本（不涉及任何 HTTP 接口）。

用途：在没有 FastAPI 业务接口（S3 才做）的情况下，直观看到整条流程的推进过程，
以及两个人工中断点返回的真实载荷。

运行方式（在项目根目录）:

    python -m scripts.demo_workflow

脚本做两件事：

1. 场景一：选题 → 驳回两次 → 通过 → 生成图片，打印每一步关键状态；
2. 场景二：连续驳回三次后再次驳回，演示 RevisionLimitReachedError 拦截。

全部使用 Mock 服务，不联网、不需要任何密钥。
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.types import Command

from app.core.exceptions import RevisionLimitReachedError
from app.graph.builder import CompiledWorkflow, build_workflow
from app.graph.state import MediaWorkflowState, WorkflowStatus
from app.services.image.mock import MockImageService
from app.services.llm.mock import MockLLMService

DIRECTION = "面向零基础学员讲清楚 LangGraph 的检查点机制"
FEEDBACK_1 = "请补充一个最小可运行示例"
FEEDBACK_2 = "第二段太啰嗦，请压缩到三句话以内"
FEEDBACK_3 = "请把代码示例换成伪代码"


def _initial_state(direction: str = DIRECTION) -> MediaWorkflowState:
    """工作流启动时的初始状态。"""
    return {
        "topic_direction": direction,
        "generated_topics": [],
        "selected_topic": None,
        "article_content": None,
        "review_action": None,
        "review_feedback": None,
        "visual_points": [],
        "image_assets": [],
        "status": WorkflowStatus.PLANNING.value,
        "error_message": None,
        "revision_count": 0,
    }


def _print_interrupt(result: dict[str, Any], title: str) -> dict[str, Any]:
    """打印中断载荷的关键字段，并返回该载荷。"""
    payload = result["__interrupt__"][0].value
    print(f"\n=== {title} ===")
    print(f"  中断类型     : {payload['type']}")
    print(f"  允许的动作   : {payload['allowed_actions']}")

    if payload["type"] == "topic_selection":
        print(f"  候选选题数量 : {len(payload['topics'])}")
        for topic in payload["topics"]:
            print(f"    - {topic['id']} {topic['title']}（{topic['angle']}）")
    else:
        print(f"  当前重写次数 : {payload['revision_count']} / {payload['max_revisions']}")
        print(f"  是否已达上限 : {payload['revision_limit_reached']}")
        article = payload["article"]
        print(f"  文章首行     : {article.splitlines()[0]}")
        print(f"  文章字数     : {len(article)}")

    return payload


async def scenario_full_flow() -> None:
    """场景一：完整闭环（含两次驳回）。"""
    workflow: CompiledWorkflow = build_workflow(
        llm_service=MockLLMService(),
        image_service=MockImageService(),
        max_revisions=3,
    )
    config = workflow.build_config("demo-full-flow")

    print("=" * 72)
    print("场景一：选题 → 驳回两次 → 通过 → 生成图片")
    print("=" * 72)

    result = await workflow.graph.ainvoke(_initial_state(), config)
    print(f"\n[启动] status={result['status']}，文章={result['article_content']}")
    payload = _print_interrupt(result, "中断点 #1：人工选题")

    # 人工选题（挑第一个候选）
    chosen_id = payload["topics"][0]["id"]
    print(f"\n[人工操作] 选择 {chosen_id}")
    result = await workflow.graph.ainvoke(
        Command(resume={"action": "select_topic", "topic_id": chosen_id}), config
    )
    print(f"[初稿完成] status={result['status']}，revision_count={result['revision_count']}")
    _print_interrupt(result, "中断点 #2：人工审稿（初稿）")

    # 连续驳回两次
    for index, feedback in enumerate((FEEDBACK_1, FEEDBACK_2), start=1):
        print(f"\n[人工操作] 第 {index} 次驳回，意见：{feedback}")
        result = await workflow.graph.ainvoke(
            Command(resume={"action": "revise", "feedback": feedback}), config
        )
        print(
            f"[重写完成] revision_count={result['revision_count']}，"
            f"意见是否体现在新稿中={feedback in result['article_content']}"
        )

    _print_interrupt(result, "中断点 #2：人工审稿（第二次重写后）")

    # 人工通过 → 提炼要点 → 生成图片
    print("\n[人工操作] 通过")
    final = await workflow.graph.ainvoke(Command(resume={"action": "approve"}), config)

    print("\n=== 最终结果 ===")
    print(f"  status            : {final['status']}")
    print(f"  revision_count    : {final['revision_count']}")
    print(f"  error_message     : {final['error_message']}")
    print(f"  视觉要点数量      : {len(final['visual_points'])}")
    for point in final["visual_points"]:
        print(f"    - [{point['order']}] {point['title']}：{point['point'][:28]}……")
    print(f"  图片资产数量      : {len(final['image_assets'])}")
    for asset in final["image_assets"]:
        print(f"    - {asset['visual_point_id']} → {asset['status']} | {asset['url']}")

    snapshot = await workflow.graph.aget_state(config)
    print(f"\n  检查点中的待执行节点: {snapshot.next}（空元组表示流程已到 END）")


async def scenario_revision_limit() -> None:
    """场景二：驳回次数用尽后，再驳回会被拒绝。"""
    workflow = build_workflow(
        llm_service=MockLLMService(),
        image_service=MockImageService(),
        max_revisions=3,
    )
    config = workflow.build_config("demo-revision-limit")

    print("\n" + "=" * 72)
    print("场景二：连续驳回三次后，再次驳回被拒绝")
    print("=" * 72)

    await workflow.graph.ainvoke(_initial_state(), config)
    await workflow.graph.ainvoke(
        Command(resume={"action": "select_topic", "topic_id": "t1"}), config
    )

    for index, feedback in enumerate((FEEDBACK_1, FEEDBACK_2, FEEDBACK_3), start=1):
        result = await workflow.graph.ainvoke(
            Command(resume={"action": "revise", "feedback": feedback}), config
        )
        print(f"\n[第 {index} 次驳回后] revision_count={result['revision_count']}")

    payload = _print_interrupt(result, "中断点 #2：已达驳回上限")
    print("  → 注意 allowed_actions 只剩下 approve")

    try:
        await workflow.graph.ainvoke(
            Command(resume={"action": "revise", "feedback": FEEDBACK_1}), config
        )
    except RevisionLimitReachedError as exc:
        print(f"\n[第四次驳回] 被拒绝：{type(exc).__name__}（code={exc.code}）")
        print(f"             {exc.message}")

    snapshot = await workflow.graph.aget_state(config)
    print(
        f"\n  被拒后检查点状态: status={snapshot.values['status']}，"
        f"revision_count={snapshot.values['revision_count']}，"
        f"visual_points={snapshot.values['visual_points']}"
    )
    print("  → 未通过人工 approve，因此从未进入 extract_visuals / generate_images")


async def main() -> None:
    await scenario_full_flow()
    await scenario_revision_limit()


if __name__ == "__main__":
    asyncio.run(main())
