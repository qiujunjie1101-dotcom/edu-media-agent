-- ============================================================================
-- 给 LangGraph 的检查点表加上中文注释
-- ============================================================================
-- 用途
--   在 Navicat / psql 里直接看到每张表、每个字段是干什么的，不用回来翻代码。
--
-- 用法
--   psql -d agent_dev -f scripts/annotate_checkpoint_tables.sql
--
-- ⚠️ 三点须知
--   1. 这四张表**由 LangGraph 创建和维护**，不是本项目建的。本脚本只加 COMMENT，
--      不改变任何字段、类型、索引或数据，对 LangGraph 的运行没有任何影响。
--   2. COMMENT 是纯元数据。它**不会**影响 setup() 的迁移逻辑，
--      也不会被日常读写覆盖。
--   3. 但如果将来 LangGraph 升级时用「重建表」的方式改结构，注释可能丢失。
--      那种情况下把本脚本重跑一遍即可恢复。
--
-- 边界提醒
--   这些表存的是 LangGraph 的「运行时状态」，用于断点续传与回溯，
--   **不是业务数据源**。不要拿它们做查询、统计或对外接口——
--   业务历史属于 S6，会用独立的表承载。
-- ============================================================================

-- ---------------------------------------------------------------------------
-- checkpoints —— 每个超级步的状态快照（主表，只存元信息与结构）
-- ---------------------------------------------------------------------------
COMMENT ON TABLE checkpoints IS
'会话状态快照。LangGraph 每执行完一个"超级步"就往这里写一条。
一条会话(thread_id)会有多条，靠 parent_checkpoint_id 串成链，因此可以回溯到任意历史步骤。
注意：大块的状态数据不在这里，在 checkpoint_blobs。';

COMMENT ON COLUMN checkpoints.thread_id IS
'会话标识。一条工作流 = 一个 thread_id，也是前端地址栏里那个 UUID。';

COMMENT ON COLUMN checkpoints.checkpoint_ns IS
'命名空间，用于子图隔离。本项目没有子图，恒为空字符串，可以忽略。';

COMMENT ON COLUMN checkpoints.checkpoint_id IS
'这一步检查点的唯一 ID。按生成时间递增排序，所以按它排序就是执行顺序。';

COMMENT ON COLUMN checkpoints.parent_checkpoint_id IS
'上一步检查点的 ID。指向空值表示这是这条会话的第一条。这列构成了回溯链。';

COMMENT ON COLUMN checkpoints.type IS
'序列化器标记(LangGraph 内部使用)。排查问题时用不到。';

COMMENT ON COLUMN checkpoints.checkpoint IS
'该超级步的状态结构：记录每个通道当前的版本号，以及待执行任务、中断信息等。
是结构化 JSON，可以直接在 Navicat 里展开看。';

COMMENT ON COLUMN checkpoints.metadata IS
'运行元信息：来源(source)、本步序号(step)、写入者等。排查"这一步是谁触发的"时有用。';

-- ---------------------------------------------------------------------------
-- checkpoint_blobs —— 实际的状态数据（按通道分块存储）
-- ---------------------------------------------------------------------------
COMMENT ON TABLE checkpoint_blobs IS
'状态数据的实际存放处。按"通道"拆开存，每个通道的值序列化后放在 blob 列里。
为什么单独一张表：状态值可能很大，而且只有变化过的通道才需要重存。
⚠️ blob 是 msgpack 二进制，不是给人读的——想看内容请用 API 的 GET /workflows/{thread_id}。';

COMMENT ON COLUMN checkpoint_blobs.thread_id IS
'会话标识，与 checkpoints.thread_id 对应。';

COMMENT ON COLUMN checkpoint_blobs.checkpoint_ns IS
'命名空间，本项目恒为空字符串。';

COMMENT ON COLUMN checkpoint_blobs.channel IS
'状态通道名，对应工作流状态(MediaWorkflowState)里的字段名，
例如 generated_topics / selected_topic / article_content / visual_points / image_assets。
想找"文章存在哪"就查这个列。';

COMMENT ON COLUMN checkpoint_blobs.version IS
'该通道值的版本号。LangGraph 内部据此判断是否需要重新传输，不用手工维护。';

COMMENT ON COLUMN checkpoint_blobs.type IS
'序列化格式标记(如 msgpack)。看到这个就知道 blob 为什么不是可读文本。';

COMMENT ON COLUMN checkpoint_blobs.blob IS
'序列化后的二进制数据。表示"空值"时只有 1 个字节，属正常现象。';

-- ---------------------------------------------------------------------------
-- checkpoint_writes —— 各节点写入的中间结果
-- ---------------------------------------------------------------------------
COMMENT ON TABLE checkpoint_writes IS
'节点执行过程中的写入记录。一个节点可能多次写同一个通道，
这里逐次记下来，用于崩溃后精确恢复到"写了一半"的状态。
数据量通常是四张表里最大的。';

COMMENT ON COLUMN checkpoint_writes.thread_id IS
'会话标识。';

COMMENT ON COLUMN checkpoint_writes.checkpoint_ns IS
'命名空间，本项目恒为空字符串。';

COMMENT ON COLUMN checkpoint_writes.checkpoint_id IS
'该写入属于哪一步检查点。';

COMMENT ON COLUMN checkpoint_writes.task_id IS
'任务标识，对应"某个节点的一次执行"。重试会让同一个节点产生新的 task_id。';

COMMENT ON COLUMN checkpoint_writes.idx IS
'同一任务内多次写入的序号，从 0 开始。';

COMMENT ON COLUMN checkpoint_writes.channel IS
'被写入的通道名，含义同 checkpoint_blobs.channel。';

COMMENT ON COLUMN checkpoint_writes.type IS
'序列化格式标记。';

COMMENT ON COLUMN checkpoint_writes.blob IS
'写入的二进制数据(非空)。';

COMMENT ON COLUMN checkpoint_writes.task_path IS
'任务路径，用于子图定位。本项目没有子图，恒为空字符串。';

-- ---------------------------------------------------------------------------
-- checkpoint_migrations —— 迁移版本记录
-- ---------------------------------------------------------------------------
COMMENT ON TABLE checkpoint_migrations IS
'表结构迁移的版本记录。LangGraph 每次启动执行 setup() 时，
先读这里的最大版本号，只补跑之后的增量迁移——这就是"重复启动不会清空已有检查点"的原因。
本表即使在没有会话的空库里也有固定若干行，属正常现象。';

COMMENT ON COLUMN checkpoint_migrations.v IS
'已应用的迁移版本号，从 0 开始递增。';
