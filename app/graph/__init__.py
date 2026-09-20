"""graph 子包：LangGraph 工作流相关代码。

S1 阶段只包含「状态定义」``state.py``。
后续阶段（S2）会加入 ``builder.py``（构图）、``routing.py``（条件路由）、
``checkpointer.py``（检查点）以及 ``nodes/``（各节点实现）。

注意：本子包**不得**读写业务数据库，也**不得**感知 HTTP —— 它只负责流程编排。
"""
