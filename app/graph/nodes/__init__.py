"""工作流节点集合包。

每个节点单独一个模块，便于「一个节点 = 一个职责」地独立测试与复用。

依赖注入约定
------------
需要外部能力的节点一律写成**工厂函数**：

    def build_xxx_node(llm_service: LLMService) -> NodeFunc:
        async def xxx(state): ...          # 内部使用 llm_service
        return xxx

构图时（``app/graph/builder.py``）调用工厂把服务「闭包注入」进去。
这样做的好处：

- 节点自己没有机会 ``new`` 一个客户端出来（想 new 也没地方拿配置）；
- 服务实例不会进入状态，检查点里不会出现不可序列化的对象；
- 单元测试可以传入测试替身，无需启动整条图。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.graph.state import MediaWorkflowState

NodeResult = dict[str, Any]
"""节点返回值。

节点**只返回要更新的字段**，框架会把它们合并回状态；
不需要（也不应该）返回完整状态。
"""

NodeFunc = Callable[[MediaWorkflowState], Awaitable[NodeResult]]
"""节点函数的统一签名：接收状态，返回「要更新的字段」。"""
