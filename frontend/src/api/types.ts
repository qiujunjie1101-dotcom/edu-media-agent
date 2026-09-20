/**
 * 后端接口契约的 TypeScript 版本。
 *
 * ============================================================================
 * 这个文件的唯一职责：把 app/schemas/workflow.py + app/schemas/domain.py
 * 的定义「逐字段照搬」过来，让前端不再靠记忆猜字段名。
 * ============================================================================
 *
 * 三条纪律：
 *   1. 字段名必须与后端**完全一致**（后端用 snake_case，这里也一律 snake_case，
 *      不做驼峰转换——转换层是「两套真相」的温床，改一个忘一个必然出错）；
 *   2. 后端没有的字段绝不在这里新增（不伪造数据）；
 *   3. 后端新增字段时，这里要同步补上。
 *
 * 关键事实（来自后端实际代码，不是猜测）：
 *   - 候选选题列表在顶层 `generated_topics`，不在 pending_action 里；
 *   - `pending_action` 只有两个字段形状，判别字段是 `type`；
 *   - 图片资产用 `visual_point_id` 关联视觉要点，字段是 `error` 而不是 `message`；
 *   - 没有 errors / warnings 数组，只有一个可空的 `error_message` 字符串。
 */

/** 候选选题（后端 app/schemas/domain.py: TopicCandidate）。 */
export interface TopicCandidate {
  /** 选题唯一标识，例如 t1 / t2；人工选题时回传这个 id */
  id: string;
  /** 选题标题 */
  title: string;
  /** 写作角度，例如「原理拆解」 */
  angle: string;
  /** 推荐理由 */
  reason: string;
}

/** 小红书视觉要点（后端 app/schemas/domain.py: VisualPoint）。 */
export interface VisualPoint {
  /** 要点唯一标识，例如 vp1；用于与 image_assets 对齐 */
  id: string;
  /** 展示顺序，从 1 开始连续递增 */
  order: number;
  /** 卡片标题 */
  title: string;
  /** 卡片正文 */
  point: string;
  /** 生图提示词（前端只展示，不参与生图） */
  prompt: string;
}

/** 图片生成状态，只有两个字面量。 */
export type ImageAssetStatus = 'success' | 'failed';

/** 一张图片的生成结果（后端 app/schemas/domain.py: ImageAsset）。 */
export interface ImageAsset {
  /** 对应的视觉要点 id，与 VisualPoint.id 一一对应 */
  visual_point_id: string;
  status: ImageAssetStatus;
  /** 图片地址；成功时应有值，失败时为 null */
  url: string | null;
  /** 失败原因；成功时为 null */
  error: string | null;
}

/** 等待人工选题（后端 app/schemas/workflow.py: TopicSelectionPending）。 */
export interface TopicSelectionPending {
  type: 'topic_selection';
  allowed_actions: Array<'select_topic'>;
}

/** 等待人工审稿（后端 app/schemas/workflow.py: ArticleReviewPending）。 */
export interface ArticleReviewPending {
  type: 'article_review';
  /**
   * 允许的动作白名单。
   * 达到重写上限时后端只会返回 ['approve']——前端据此禁用驳回入口，
   * 但**不能只依赖它**做安全判断（后端会独立再校验一次）。
   */
  allowed_actions: Array<'approve' | 'revise'>;
  /** 已按人工意见重写的次数 */
  revision_count: number;
  /** 是否已达重写上限 */
  revision_limit_reached: boolean;
}

/** 当前等待人工完成的动作；null 表示没有中断（流程在跑或已结束）。 */
export type PendingAction = TopicSelectionPending | ArticleReviewPending;

/** 三个接口共用的成功响应结构（后端 app/schemas/workflow.py: WorkflowResponse）。 */
export interface WorkflowResponse {
  thread_id: string;
  status: string;
  topic_direction: string;
  generated_topics: TopicCandidate[];
  selected_topic: TopicCandidate | null;
  article_content: string | null;
  review_action: 'approve' | 'revise' | null;
  review_feedback: string | null;
  visual_points: VisualPoint[];
  image_assets: ImageAsset[];
  revision_count: number;
  error_message: string | null;
  pending_action: PendingAction | null;
}

/** 请求体：启动工作流。 */
export interface WorkflowStartRequest {
  topic_direction: string;
}

/** 请求体：人工选题。 */
export interface SelectTopicRequest {
  action: 'select_topic';
  topic_id: string;
}

/** 请求体：人工通过。 */
export interface ApproveRequest {
  action: 'approve';
  /** 可选备注，后端仅留痕、不参与生成 */
  comment?: string;
}

/** 请求体：人工驳回并要求重写（feedback 至少 5 个字符）。 */
export interface ReviseRequest {
  action: 'revise';
  feedback: string;
}

/** 三种恢复动作的联合类型，判别字段是 action。 */
export type ResumeRequest = SelectTopicRequest | ApproveRequest | ReviseRequest;

/**
 * 后端 WorkflowStatus 的全部取值（app/graph/state.py）。
 *
 * 为什么在这里列全？
 *   界面必须能区分「已知但还在跑」和「完全不认识」这两种情况：
 *   后者要显示明确异常，而不是空白页面。
 */
export const WORKFLOW_STATUSES = [
  'planning',
  'awaiting_topic_selection',
  'drafting',
  'awaiting_review',
  'revising',
  'extracting_visuals',
  'generating_images',
  'completed',
  'completed_with_warnings',
  'failed',
] as const;

export type WorkflowStatus = (typeof WORKFLOW_STATUSES)[number];

/** 运行中的中间态：此时没有人工中断，界面显示「处理中」。 */
export const IN_PROGRESS_STATUSES: readonly string[] = [
  'planning',
  'drafting',
  'revising',
  'extracting_visuals',
  'generating_images',
];

/** 终态：流程已经跑完（不管有没有警告）。 */
export const COMPLETED_STATUSES: readonly string[] = ['completed', 'completed_with_warnings'];

/** 中文状态名，用于顶部状态展示（仅做展示，不参与任何判断）。 */
export const STATUS_LABELS: Record<string, string> = {
  planning: '正在生成选题',
  awaiting_topic_selection: '等待选择题目',
  drafting: '正在撰写文章',
  awaiting_review: '等待审核文章',
  revising: '正在按意见重写',
  extracting_visuals: '正在提炼视觉要点',
  generating_images: '正在生成图片',
  completed: '已完成',
  completed_with_warnings: '已完成（有警告）',
  failed: '失败',
};

/** 重写意见的最小长度，必须与后端 human_review.py 的 MIN_FEEDBACK_LENGTH 一致。 */
export const MIN_FEEDBACK_LENGTH = 5;

/** 内容方向的最小 / 最大长度，必须与后端 WorkflowStartRequest 的约束一致。 */
export const MIN_TOPIC_DIRECTION_LENGTH = 2;
export const MAX_TOPIC_DIRECTION_LENGTH = 200;
