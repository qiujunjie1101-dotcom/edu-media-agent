"""检查点（Checkpoint）存储的创建。

============================================================================
检查点是干什么的？
============================================================================
LangGraph 每执行完一个「超级步」就把状态快照写进检查点存储，于是：

- ``interrupt()`` 才能生效——暂停时靠检查点记住「停在哪、状态是什么」；
- 恢复时才能从终点继续，而不是从头再来；
- ``aget_state_history()`` 才能回溯每一步。

============================================================================
为什么 S2 只用内存实现？
============================================================================
``InMemorySaver`` 把检查点存在进程内存里：无需数据库、开箱即用，
非常适合 S2–S4 阶段的开发与测试。它的局限是**进程重启即丢失**，
因此 S5 阶段会换成 PostgreSQL 实现（``AsyncPostgresSaver``）。

重要：InMemorySaver 必须与编译后的图**同生命周期**。
如果每次调用都新建一个 saver，历史检查点就没了，中断将无法恢复。
所以这里只在构图时创建一次，并由 ``CompiledWorkflow`` 持有引用。
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver


def create_in_memory_checkpointer() -> InMemorySaver:
    """创建一个进程内检查点存储。

    返回:
        InMemorySaver: 供 ``graph.compile(checkpointer=...)`` 使用

    """
    return InMemorySaver()
