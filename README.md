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
| **S4** | 前端工作台（React + Vite）：四个界面、状态恢复、最小 CORS | ✅ 已完成 |
| **S5** | PostgreSQL Checkpointer：会话跨重启持久化、`CHECKPOINTER_BACKEND` 开关 | ✅ 已完成 |
| S6–S10 | 业务历史、真实模型、SSE、可观测性 | 未开始 |

> S1 交付「可导入、可启动、可测试」的地基；S2 交付「可暂停、可恢复、可驳回重写」的
> 工作流内核；S3 交付「能被前端调用」的 HTTP 契约；S5 交付「重启不丢会话」的持久化。
> **S5 只持久化 LangGraph 的运行时状态，不建任何业务表**——业务历史属于 S6。

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

当前全部使用 Mock 服务，`.env` 保持默认值即可，**不需要任何 API Key，也不需要数据库**
（检查点默认存在进程内存里，重启即丢；要跨重启持久化见下文「检查点持久化（S5）」）。

## 启动服务

```bash
python -m uvicorn app.main:app --reload
```

启动后访问：

- 健康检查：<http://127.0.0.1:8000/health>
- 接口文档：<http://127.0.0.1:8000/docs>

健康检查返回示例：

```json
{
  "status": "healthy",
  "app": "自媒体内容运营 AI 智能体",
  "environment": "local",
  "checkpointer": "memory"
}
```

`checkpointer` 是 S5 新增的字段，只暴露后端**名称**（`memory` / `postgres`），
不含任何连接信息。想换成重启不丢会话的模式，见下文「检查点持久化（S5）」。

## 运行测试

必须使用 `python -m pytest`（而不是直接 `pytest`），这样项目根目录才会被加入
模块搜索路径，测试里才能 `import app`：

```bash
python -m pytest -v
```

默认**不需要任何数据库**：检查点存在进程内存里，所有测试开箱即绿。
需要真实 PostgreSQL 的用例单独打了标记，没配测试库时会自动跳过（见下文）。

## 检查点持久化（S5）

### 它解决什么问题

默认的 `InMemorySaver` 把会话状态存在**进程内存**里，后端一重启就全没了 ——
你正看着「审核文章」页面，服务重启一下，刷新就是 `THREAD_NOT_FOUND`。
开发时 `uvicorn --reload` 每改一次代码就丢一次会话。

换成 PostgreSQL Checkpointer 之后，会话状态的寿命从「一次进程」延长到「永久」：
关掉服务、重启机器，只要 `thread_id` 还在，就能凭它恢复现场。

### 先用哪种？

| 后端 | 适用场景 |
|---|---|
| `memory`（**默认**） | 本地开发、跑测试。零依赖，重启即丢 |
| `postgres` | 想验证「重启后会话还在」、或准备长期保留会话时 |

### 1. 创建本地数据库

```bash
# macOS（Homebrew 装的 PostgreSQL）
brew install postgresql@17
brew services start postgresql@17
createdb langgraph_db
```

不需要手动建表 —— 应用启动时会自动执行 LangGraph 自带的表结构迁移。

### 2. 配置环境变量

```bash
cp .env.example .env
```

`memory` 模式保持默认即可。要用 `postgres` 模式，改 `.env`：

```bash
CHECKPOINTER_BACKEND=postgres
POSTGRES_URI=postgresql://你的用户:你的口令@localhost:5432/langgraph_db
```

> ⚠️ `.env` 已被 `.gitignore` 忽略，**真实口令只填在这里**，不要写进 `.env.example`
> 或任何会被提交的文件。服务日志与错误信息里，连接串的口令一律显示为 `***`。

### 3. 启动

```bash
# memory 模式（默认，不需要数据库）
python -m uvicorn app.main:app --reload

# postgres 模式
CHECKPOINTER_BACKEND=postgres \
POSTGRES_URI='postgresql://用户:口令@localhost:5432/langgraph_db' \
python -m uvicorn app.main:app --reload
```

启动后看一眼 `http://127.0.0.1:8000/health`，`checkpointer` 字段会告诉你当前用的是哪个后端：

```json
{"status":"healthy","app":"...","environment":"local","checkpointer":"postgres"}
```

看到 `memory` 就说明重启必丢，不该去翻代码找原因。

**配置写错会直接启动失败**，不会静默退回 memory：

- 选了 `postgres` 却没给 `POSTGRES_URI` → 拒绝启动
- `POSTGRES_URI` 连不上、库不存在 → 拒绝启动，并给出脱敏后的错误
- `CHECKPOINTER_BACKEND` 写了 `sqlite` 之类的值 → 拒绝启动，并列出可选值

这是刻意的。静默降级会让「重启后会话还在」这个承诺悄悄失效，
等到线上重启才发现就太晚了。

### 4. 怎么验证重启恢复

```bash
# ① 启动（postgres 模式），创建一个会话并推进到审核中断
curl -X POST http://127.0.0.1:8000/api/v1/workflows/start \
  -H 'Content-Type: application/json' -d '{"topic_direction":"测试重启恢复"}'
# 记下返回的 thread_id，然后选题
curl -X POST http://127.0.0.1:8000/api/v1/workflows/<thread_id>/resume \
  -H 'Content-Type: application/json' -d '{"action":"select_topic","topic_id":"t1"}'

# ② 完全停掉后端进程（Ctrl-C，或者 kill -9），再重新启动

# ③ 凭 thread_id 查询 —— 文章与待办动作都还在
curl http://127.0.0.1:8000/api/v1/workflows/<thread_id>
# → status=awaiting_review，article_content 非空，pending_action.type=article_review
```

换成 `memory` 模式重做一遍，第 ③ 步会返回 `THREAD_NOT_FOUND` —— 这就是两者的区别。

### 5. 跑 PostgreSQL 集成测试

```bash
createdb langgraph_test
export TEST_POSTGRES_URI='postgresql://用户:口令@localhost:5432/langgraph_test'
python -m pytest tests/integration/test_postgres_checkpointer.py -v

# 或者只跑全部测试里的 postgres 那一组
python -m pytest -m postgres -v
```

不设 `TEST_POSTGRES_URI` 时这组用例会**明确 skip**（报告里显示 SKIPPED），
不会伪装成通过。

### 6. ⚠️ Checkpointer 不是业务数据库

这是最容易误解的一点。检查点表（`checkpoints` / `checkpoint_blobs` /
`checkpoint_writes` / `checkpoint_migrations`）里存的是：

- LangGraph 的**框架内部状态**：每个超级步的快照、待执行任务、中断信息、通道版本号
- 格式是**框架私有的序列化编码**，版本升级可能变化，**不能当作对外契约**
- 没有外键、唯一键、字段级校验，也没有任何按业务维度的索引

所以它**不能**用来做这些事：按状态/时间检索会话列表、统计、审计、对外提供数据。

那些属于**业务数据**，会由 S6 用独立的表（`workflow_session` /
`content_artifact` / `review_log`）承载，与检查点表通过 `thread_id` 关联。
两者的生命周期也不同：检查点会因为回溯、重试而频繁增长，可以按策略清理；
业务数据需要长期留存。

一句话：**检查点负责「流程能不能接着跑」，业务表负责「发生了什么」。**

### 7. 给检查点表加中文注释（可选，但强烈建议）

这四张表由 LangGraph 创建，默认没有任何注释，在 Navicat / psql 里看是一头雾水。
仓库里带了一个只加注释、不动结构的脚本：

```bash
psql -d agent_dev -f scripts/annotate_checkpoint_tables.sql
```

跑完再 `\d+ checkpoints`（或 Navicat 里点开表设计），每张表每个字段都能看到中文说明，
比如 `checkpoint_blobs.channel` 会告诉你「这里存的是 generated_topics / article_content 这些通道名」。

两点说明：

- 脚本只执行 `COMMENT ON`，**不改变字段、类型、索引和数据**，对 LangGraph 的运行没有影响；
- 如果将来 LangGraph 升级时用「重建表」的方式改结构，注释可能丢失，重跑一次即可恢复。

## 前端工作台（S4）

前端位于 `frontend/`（不放进 Python 的 `app/`），只调用上面那三个已有接口，
**不修改任何 LangGraph 语义**。技术栈：React + TypeScript + Vite + Vitest +
React Testing Library + lucide-react + Tailwind CSS v4 + shadcn/ui（Radix）。

> **样式迁移进行中**：工作台外壳（顶栏 / 步骤栏 / 标题区）与「生成结果」一屏
> 已迁到 Tailwind + shadcn；「内容方向 / 选择题目 / 审核文章」三屏仍走
> `styles/app.css` 的旧样式体系。两套并存是刻意的——Tailwind 入口
> （`styles/index.css`）**不加载 preflight**，避免它的全局重置冲掉旧样式。
> 剩余三屏迁完后，`app.css` 与 `tokens.css` 即可整体删除。

```bash
cd frontend
npm install
cp .env.example .env      # 配置 VITE_API_BASE_URL，默认指向本机 8000 端口
npm run dev               # 开发服务器：http://localhost:5173
npm test                  # 组件与流程测试（Vitest）
npm run typecheck         # TypeScript 类型检查
npm run build             # 生产构建
```

联调要求两个服务同时运行：后端默认 8000 端口，前端默认 5173 端口。
后端通过 `CORS_ALLOW_ORIGINS` 放行前端来源（默认 `http://localhost:5173`），
因此**不要把前端端口改成别的值**，否则会被浏览器拦截。

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

## 目录结构（S1–S5 范围）

```text
yy_agent/
├── requirements.txt          # 依赖清单（langgraph 已锁定 1.2.11）
├── pytest.ini                # pytest 配置：注册 postgres 标记（S5）
├── .env.example              # 环境变量模板（复制为 .env 使用）
├── .gitignore                # 忽略 .env、缓存、虚拟环境等
├── README.md                 # 本文件
├── docs/
│   └── 技术方案设计.md       # 完整技术方案 v2
├── scripts/
│   ├── demo_workflow.py      # 演示脚本：直接驱动 Graph 走完整流程（S2）
│   └── annotate_checkpoint_tables.sql  # 给 LangGraph 检查点表加中文注释（S5，可选）
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
│   │   ├── checkpointer.py   # 检查点工厂：memory / postgres 两种后端 + 连接池生命周期（S5）
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
