"""自媒体内容运营 AI 智能体 —— 应用包。

本包目录结构（S1 阶段）：

- ``core``     ：基础设施（配置读取）
- ``schemas``  ：领域模型与接口数据结构
- ``graph``    ：LangGraph 工作流相关（S1 只有状态定义）
- ``services`` ：外部能力适配层（LLM / 图片）与服务容器

依赖方向约定：``services`` 可以依赖 ``schemas``；``schemas`` 不依赖任何其他包。
"""
