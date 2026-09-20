# 自媒体内容运营 AI 智能体

面向 AI 编程培训机构的自媒体内容运营 AI 智能体：输入一个内容方向，自动产出
**微信公众号长文**、**小红书视觉要点** 与 **知识卡片图片**，并在「人工选题」与
「人工审稿」两个环节强制暂停等待人工决策。

完整技术方案见 [docs/技术方案设计.md](docs/技术方案设计.md)（v2）。

---

## 当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| **S1** | 项目骨架、配置、领域模型、State、Mock 服务、`/health` | ✅ 已完成 |
| **S2** | 完整 LangGraph 工作流、两个人工中断、驳回循环、内存 Checkpointer | ✅ 已完成 |
| **S3** | `start` / `get` / `resume` 三个 HTTP 接口、WorkflowService、统一错误码 | ✅ 已完成 |
| S4–S10 | 前端、PostgreSQL Checkpointer、业务历史、真实模型、SSE、可观测性 | 未开始 |

> S1 交付「可导入、可启动、可测试」的地基；S2 交付「可暂停、可恢复、可驳回重写」的
> 工作流内核；S3 交付「能被前端调用」的 HTTP 契约。三者都**不含**数据库、真实模型与鉴权。

---

## 环境准备

- Python 3.11+
- 依赖管理：`requirements.txt`

本项目在 conda 环境 `yy_agent` 下开发，可直接使用该环境的解释器：

```bash
# 查看可用环境
conda env list

# 激活环境（若尚未创建，可执行：conda create -n yy_agent python=3.11 -y）
conda activate yy_agent
```

## 安装依赖

```bash
python -m pip install -r requirements.txt
```

## 配置环境变量

```bash
cp .env.example .env
```

S1 阶段全部使用 Mock 服务，`.env` 保持默认值即可，**不需要任何 API Key，也不需要数据库**。

## 启动服务

```bash
python -m uvicorn app.main:app --reload
```

启动后访问：

- 健康检查：<http://127.0.0.1:8000/health>
- 接口文档：<http://127.0.0.1:8000/docs>

健康检查返回示例：

```json
{"status": "healthy", "app": "自媒体内容运营 AI 智能体", "environment": "local"}
```

## 运行测试

必须使用 `python -m pytest`（而不是直接 `pytest`），这样项目根目录才会被加入
模块搜索路径，测试里才能 `import app`：

```bash
python -m pytest -v
```

## 演示：直接驱动工作流（S2）

S3 之前没有 HTTP 接口，用演示脚本可以直接观察整条流程与两个人工中断点的真实载荷：

```bash
python -m scripts.demo_workflow
```

脚本会跑两个场景：

1. 选题 → 驳回两次 → 通过 → 提炼视觉要点 → 并发生成图片；
2. 连续驳回三次后再次驳回，演示 `RevisionLimitReachedError` 如何拦截。

## 工作流（S2）

```text
START
  │
plan_topics                生成 3–5 个候选选题
  │
human_select_topic         ← 人工中断点 #1（interrupt）
  │
write_draft                写初稿 / 按意见重写（revision_count 只在重写时 +1）
  │
human_review               ← 人工中断点 #2（interrupt）
  ├── approve ──▶ extract_visuals ──▶ generate_images ──▶ END
  └── revise  ──▶ write_draft（可重复执行的审核循环）
```

两条硬约束：

- `extract_visuals` **只有一个入口**：人工 approve。图结构本身保证「未经人工通过绝不生图」；
- 驳回次数达到 `MAX_REVISIONS`（默认 3）后只允许 approve，此时再驳回会抛
  `RevisionLimitReachedError`，**不做自循环、不做自动放行**。

---

## HTTP 接口（S3）

基础路径 `/api/v1`，请求与响应均为 `application/json`。

| 方法 | 路径 | 说明 | 成功状态码 |
|---|---|---|---|
| GET | `/health` | 健康检查 | 200 |
| POST | `/api/v1/workflows/start` | 启动会话，停在人工选题中断 | 201 |
| GET | `/api/v1/workflows/{thread_id}` | 查询最新状态与待办动作 | 200 |
| POST | `/api/v1/workflows/{thread_id}/resume` | 提交人工动作（选题 / 通过 / 驳回） | 200 |

### 完整闭环示例

```bash
# 1) 启动
curl -X POST http://127.0.0.1:8000/api/v1/workflows/start \
  -H 'Content-Type: application/json' \
  -d '{"topic_direction":"LangGraph 人工审核教程"}'
# → {"thread_id":"<uuid>","status":"awaiting_topic_selection", ... ,
#    "pending_action":{"type":"topic_selection","allowed_actions":["select_topic"]}}

# 2) 选题（把 <uuid> 换成上一步返回的 thread_id）
curl -X POST http://127.0.0.1:8000/api/v1/workflows/<uuid>/resume \
  -H 'Content-Type: application/json' -d '{"action":"select_topic","topic_id":"t1"}'
# → status=awaiting_review，pending_action.type=article_review

# 3a) 驳回重写（feedback 至少 5 个字符）
curl -X POST http://127.0.0.1:8000/api/v1/workflows/<uuid>/resume \
  -H 'Content-Type: application/json' \
  -d '{"action":"revise","feedback":"请补充一个最小可运行代码示例"}'

# 3b) 或直接通过 → 提炼视觉要点 → 生成图片
curl -X POST http://127.0.0.1:8000/api/v1/workflows/<uuid>/resume \
  -H 'Content-Type: application/json' -d '{"action":"approve"}'
# → status=completed，image_assets 非空，pending_action=null
```

### 统一错误响应

```json
{"detail": {"code": "ACTION_NOT_ALLOWED", "message": "当前阶段不允许该操作", "thread_id": "..."}}
```

| 错误码 | HTTP | 触发条件 |
|---|---|---|
| `THREAD_NOT_FOUND` | 404 | `thread_id` 不存在（含进程重启后内存检查点丢失） |
| `WORKFLOW_NOT_INTERRUPTED` | 409 | 当前不处于人工中断点（运行中或已结束） |
| `ACTION_NOT_ALLOWED` | 409 | 动作与当前中断类型不匹配（如待选题时传 `approve`） |
| `REVISION_LIMIT_REACHED` | 409 | 已达 `MAX_REVISIONS` 仍提交 `revise` |
| `VALIDATION_ERROR` | 422 | 请求体不满足约束（长度、必填、未知动作等） |
| `TOPIC_NOT_FOUND` | 422 | `topic_id` 不在候选选题中 |
| `CONTENT_VALIDATION_ERROR` | 502 | 生成内容不符合业务规则 |
| `IMAGE_GENERATION_FAILED` | 502 | 图片全部生成失败 |
| `LLM_UNAVAILABLE` | 503 | 文本模型上游不可用 |
| `INTERNAL_ERROR` | 500 | 未预期异常（不泄露堆栈与内部对象） |

### 恢复前的强制前置校验

LangGraph 1.2.11 已实测：一次非法的 `Command(resume=...)` 会让该 thread 的任务进入
error 状态，**之后即使换成合法恢复值也推不动**。因此 `WorkflowService.resume` 在调用
Graph 之前会依次校验：

1. `thread_id` 是否存在；2. 当前是否处于人工中断；3. 读取并归一化 `pending_action`；
4. 动作与中断类型是否匹配；5. `select_topic` 的 `topic_id` 是否存在于 `generated_topics`；
6. `revise` 是否未达上限；7. `revise` 的 `feedback` 是否合法；8. 动作是否在 `allowed_actions` 内。

任何一步失败都**不会调用 Graph**，原 thread 保持可用。

---

## 目录结构（S1–S3 范围）

```text
yy_agent/
├── requirements.txt          # 依赖清单（langgraph 已锁定 1.2.11）
├── .env.example              # 环境变量模板（复制为 .env 使用）
├── .gitignore                # 忽略 .env、缓存、虚拟环境等
├── README.md                 # 本文件
├── docs/
│   └── 技术方案设计.md       # 完整技术方案 v2
├── scripts/
│   └── demo_workflow.py      # 演示脚本：直接驱动 Graph 走完整流程（S2）
├── app/
│   ├── main.py               # FastAPI 应用工厂 + lifespan 单例装配 + 全局异常处理器
│   ├── api/                  # HTTP 边界层（S3）：只做校验/转发/响应，不碰 Graph
│   │   ├── deps.py           # 依赖注入：从 app.state 取 WorkflowService
│   │   └── v1/
│   │       ├── router.py     # /api/v1 路由聚合
│   │       └── endpoints/
│   │           └── workflows.py  # start / get / resume 三个端点
│   ├── core/
│   │   ├── config.py         # Settings：从环境变量/.env 读取配置（含单例缓存）
│   │   └── exceptions.py     # 领域异常 + 错误码→HTTP 状态码映射表
│   ├── schemas/
│   │   ├── domain.py         # 领域模型：TopicCandidate / VisualPoint / ImageAsset
│   │   └── workflow.py       # 接口契约：请求/响应模型、判别联合、pending_action（S3）
│   ├── graph/
│   │   ├── state.py          # MediaWorkflowState（TypedDict，JSON 可序列化）
│   │   ├── builder.py        # 构图 + 编译；CompiledWorkflow 持有 checkpointer（S2）
│   │   ├── routing.py        # 节点名常量 + route_after_review 纯函数（S2）
│   │   ├── checkpointer.py   # 创建 InMemorySaver（S2；S5 换成 PostgreSQL）
│   │   └── nodes/            # 6 个节点，一一对应（S2）
│   │       ├── plan_topics.py          # 生成候选选题
│   │       ├── human_select_topic.py   # 人工中断点 #1
│   │       ├── write_draft.py          # 初稿 / 按意见重写
│   │       ├── human_review.py         # 人工中断点 #2（通过 / 驳回）
│   │       ├── extract_visuals.py      # 提炼视觉要点（只有 approve 能到达）
│   │       └── generate_images.py      # 并发生成图片 + 部分失败降级
│   └── services/
│       ├── container.py      # 服务容器：按配置装配 Mock / 真实适配器
│       ├── workflow_service.py # 工作流唯一业务入口：图调用、中断归一化、前置校验（S3）
│       ├── llm/
│       │   ├── base.py       # LLMService 抽象接口（3 个异步方法）
│       │   └── mock.py       # MockLLMService：确定性假数据，不联网
│       └── image/
│           ├── base.py       # ImageService 抽象接口
│           └── mock.py       # MockImageService：返回稳定的模拟图片地址
└── tests/
    ├── conftest.py           # 公共 fixture（settings / container / app / client / workflow）
    ├── test_health.py        # 应用可导入、可启动、/health 返回正确、路由清单守卫
    ├── test_domain_models.py # 领域模型校验与 JSON 转换
    ├── test_state_serialization.py # State 全字段 JSON 往返
    ├── test_mock_services.py # Mock 服务的确定性、数量、无网络访问
    ├── unit/
    │   ├── test_routing.py   # 路由纯函数：映射正确、无副作用、非法动作报错
    │   ├── test_nodes.py     # 非中断节点：写入字段、计数、降级与报错
    │   └── test_workflow_schemas.py # 请求/响应模型与判别联合（S3）
    ├── integration/
    │   └── test_workflow.py  # 直接驱动 Graph：两个中断点、驳回循环、上限、隔离
    └── api/
        └── test_workflows.py # 三个端点的契约、错误码、状态隔离、非法请求不损坏 thread（S3）
```

## 设计要点

1. **依赖方向单向**：`api → services → (adapters / graph)`，适配层与工作流层互不依赖。
   节点通过「构图时闭包注入」获取服务实例，绝不自己 `new` 客户端。
2. **领域模型是唯一契约**：`app/schemas/domain.py` 是节点与适配器之间的交换格式，
   第三方 SDK 的原始结构不得越界。
3. **State 只存 JSON 数据**：`MediaWorkflowState` 里不能放 Pydantic 实例、HTTP 客户端、
   数据库对象或 Logger，否则检查点无法序列化；`status` 写的是枚举的 `.value`（纯字符串），
   避免检查点出现自定义类型。
4. **Mock 与真实实现同签名**：切换提供方只改 `.env` + `container.py` 的装配分支，
   节点代码零改动。
5. **中断用 `interrupt()`，不用旧式写法**：`interrupt_before` + `update_state` 属于
   LangGraph 旧范式，语义不同且容易写出「看起来能跑」的假人工审核。
6. **`route_after_review` 是纯函数**：只决定下一个节点，不写状态、不抛业务规则；
   超限驳回这类判断放在 `human_review` 节点里做（要么改状态、要么抛错）。
7. **异常不吞**：节点出错直接向上抛，检查点保留最后一个有效状态，由 `WorkflowService`
   统一映射成 HTTP 错误码。注意：一次非法的恢复调用会让该 thread 的任务进入 error 状态，
   因此**必须**在接口层做前置校验（见上文「恢复前的强制前置校验」）。
8. **Graph 只有一个入口、只有一份实例**：`WorkflowService` 是唯一调用 `ainvoke` /
   `aget_state` 的地方；编译后的图、`InMemorySaver` 与服务本身都在 lifespan 里创建一次，
   由依赖注入分发。任何「每次请求重新构图」的写法都会让历史会话瞬间失效。
9. **LangGraph 版本适配只有一处**：中断载荷在 `ainvoke` 返回值里是
   `result["__interrupt__"][0].value`，在 `aget_state` 快照里是
   `snapshot.tasks[*].interrupts[*].value`——这两种读法都收口在
   `workflow_service._read_interrupt` 一个函数里，升级 LangGraph 只需改它。
