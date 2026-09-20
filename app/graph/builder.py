"""构图函数：把节点、边组装成可运行的工作流，并一次性编译。

============================================================================
整条流程
============================================================================
    START
      │
    plan_topics               生成 3–5 个候选选题
      │
    human_select_topic        ← 人工中断点 #1（interrupt）
      │
    write_draft               写初稿 / 按意见重写（revision_count 只在重写时 +1）
      │
    human_review              ← 人工中断点 #2（interrupt）
      ├── approve ──▶ extract_visuals ──▶ generate_images ──▶ END
      └── revise  ──▶ write_draft（形成可重复的审核循环）

============================================================================
两条设计红线
============================================================================
1. **extract_visuals 只有一个入口**：approve。图结构本身就是
   「未经人工通过绝不生图」这条业务约束的硬保证；
2. **human_review 没有自循环**：达到驳回上限后再收到 revise，
   由节点抛 ``RevisionLimitReachedError``，而不是靠「回到自己」来消化。

============================================================================
依赖注入
============================================================================
服务实例（LLMService / ImageService）在这里通过节点工厂函数注入，
节点内部不会创建任何客户端；服务也不会进入状态，因此检查点里只有纯数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.checkpointer import create_in_memory_checkpointer
from app.graph.nodes.extract_visuals import build_extract_visuals_node
from app.graph.nodes.generate_images import build_generate_images_node
from app.graph.nodes.human_review import build_human_review_node
from app.graph.nodes.human_select_topic import human_select_topic
from app.graph.nodes.plan_topics import build_plan_topics_node
from app.graph.nodes.write_draft import build_write_draft_node
from app.graph.routing import (
    EXTRACT_VISUALS_NODE,
    GENERATE_IMAGES_NODE,
    HUMAN_REVIEW_NODE,
    HUMAN_SELECT_TOPIC_NODE,
    PLAN_TOPICS_NODE,
    WRITE_DRAFT_NODE,
    route_after_review,
)
from app.graph.state import MediaWorkflowState
from app.services.image.base import ImageService
from app.services.llm.base import LLMService


@dataclass(frozen=True)
class CompiledWorkflow:
    """编译后的工作流 + 它的检查点存储。

    把两者放在同一个对象里，是为了保证「图活着，检查点就活着」：
    ``InMemorySaver`` 里的会话记录会随着这个对象的生命周期存在，
    不会因为某处又 new 了一个 saver 而丢失。

    字段:
        graph: 编译后的 LangGraph 图（可 ``ainvoke``）
        checkpointer: 检查点存储（S2 为内存实现）
        max_revisions: 本图使用的驳回上限，便于调用方回显给前端

    """

    graph: CompiledStateGraph
    checkpointer: InMemorySaver
    max_revisions: int

    def build_config(self, thread_id: str) -> dict[str, Any]:
        """生成一次会话的调用配置。

        参数:
            thread_id: 会话标识，由服务端生成（S3 起由业务层传入）

        返回:
            dict: 传给 ``ainvoke`` / ``aget_state`` 的 config

        说明:
            ``thread_id`` 是 LangGraph 区分会话的唯一依据——同一个图、
            不同 thread_id 之间状态完全隔离；同一个 thread_id 会续上之前的检查点。
        """
        return {"configurable": {"thread_id": thread_id}}


def build_workflow(
    *,
    llm_service: LLMService,
    image_service: ImageService,
    max_revisions: int,
    checkpointer: InMemorySaver | None = None,
) -> CompiledWorkflow:
    """组装并编译工作流。

    参数:
        llm_service: 文本模型服务
        image_service: 图片服务
        max_revisions: 允许的最大重写次数
        checkpointer: 可选的检查点存储。不传则新建一个内存实现；
                      传入同一个实例即可让多条会话共享既有历史。

    返回:
        CompiledWorkflow: 编译后的图与检查点的组合体

    """
    # 检查点只创建一次，并与返回的 CompiledWorkflow 绑定
    saver = checkpointer if checkpointer is not None else create_in_memory_checkpointer()

    builder: StateGraph = StateGraph(MediaWorkflowState)

    # ---------------- 注册节点 ----------------
    # 需要外部能力的节点用「工厂 + 闭包注入」的方式创建
    builder.add_node(PLAN_TOPICS_NODE, build_plan_topics_node(llm_service))
    builder.add_node(HUMAN_SELECT_TOPIC_NODE, human_select_topic)
    builder.add_node(WRITE_DRAFT_NODE, build_write_draft_node(llm_service))
    builder.add_node(HUMAN_REVIEW_NODE, build_human_review_node(max_revisions))
    builder.add_node(EXTRACT_VISUALS_NODE, build_extract_visuals_node(llm_service))
    builder.add_node(GENERATE_IMAGES_NODE, build_generate_images_node(image_service))

    # ---------------- 连接固定边 ----------------
    builder.add_edge(START, PLAN_TOPICS_NODE)
    builder.add_edge(PLAN_TOPICS_NODE, HUMAN_SELECT_TOPIC_NODE)
    builder.add_edge(HUMAN_SELECT_TOPIC_NODE, WRITE_DRAFT_NODE)
    builder.add_edge(WRITE_DRAFT_NODE, HUMAN_REVIEW_NODE)
    builder.add_edge(EXTRACT_VISUALS_NODE, GENERATE_IMAGES_NODE)
    builder.add_edge(GENERATE_IMAGES_NODE, END)

    # ---------------- 连接条件边 ----------------
    # 第二个参数是「纯函数路由」，第三个参数声明 返回值 → 节点名 的映射关系。
    # 映射表里只出现这两个目标，意味着路由不可能把流程带到别处。
    builder.add_conditional_edges(
        HUMAN_REVIEW_NODE,
        route_after_review,
        {
            EXTRACT_VISUALS_NODE: EXTRACT_VISUALS_NODE,
            WRITE_DRAFT_NODE: WRITE_DRAFT_NODE,
        },
    )

    # 编译：把 checkpointer 绑定进来，interrupt / 恢复 / 历史查询才能工作
    compiled = builder.compile(checkpointer=saver)

    return CompiledWorkflow(graph=compiled, checkpointer=saver, max_revisions=max_revisions)
