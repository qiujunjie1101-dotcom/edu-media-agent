"""文本模型适配层。

本子包包含：

- ``base.py``：``LLMService`` 抽象接口（所有实现必须遵守的契约）
- ``mock.py``：确定性 Mock 实现，S1–S6 阶段使用，不联网
- （S7 阶段将加入真实实现，例如 openai_client.py）
"""
