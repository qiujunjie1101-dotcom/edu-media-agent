"""v1 路由聚合：把各资源的端点挂到统一前缀下。

============================================================================
为什么要有这一层「聚合」？
============================================================================
如果没有它，``app/main.py`` 就得逐个 import 每个端点模块并自己拼前缀：

    app.include_router(workflows.router, prefix="/api/v1")

端点一多，前缀就会在多个地方重复出现，改动时容易漏。
聚合层把「版本前缀 + 有哪些资源」集中到一处：

    app.include_router(v1_router)          # main.py 只认这一个入口
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import workflows

# APIRouter 是 FastAPI 的「路由分组」工具：
# 可以在它上面统一声明前缀与标签，再整体挂载到应用上。
router = APIRouter(prefix="/api/v1")

# 各资源的路由在这里登记。新增资源时只加一行。
router.include_router(workflows.router)
