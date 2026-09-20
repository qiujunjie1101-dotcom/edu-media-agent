/**
 * 第 2 屏：选择题目（对应 pending_action.type === "topic_selection"）。
 *
 * 视觉要点：
 *   - 用纵向可选列表而不是大块装饰卡片；每项只有单选控件、标题、角度与推荐理由；
 *   - 默认浅边框，hover 变背景与描边，选中后主色边框 + 浅绿背景 + Check 图标；
 *   - 选中标记槽宽度恒定（只切透明度），因此切换选择不会让列表跳动；
 *   - 底部操作区：次操作「返回修改方向」在左，主操作「使用此选题」在右。
 */

import { useState } from 'react';
import { Check } from 'lucide-react';

import type { TopicCandidate } from '../api/types';
import { Button } from '../components/Button';
import { classNames } from '../components/classNames';
import { WorkArea } from '../components/WorkArea';

interface TopicSelectionScreenProps {
  /** 候选选题，来自顶层 generated_topics */
  topics: TopicCandidate[];
  /** 是否正在提交 */
  submitting: boolean;
  onConfirm: (topicId: string) => void;
  /** 返回修改内容方向（放弃本次会话，回到第一屏并保留原方向） */
  onBack: () => void;
}

export function TopicSelectionScreen({
  topics,
  submitting,
  onConfirm,
  onBack,
}: TopicSelectionScreenProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const handleConfirm = (): void => {
    if (selectedId === null || submitting) {
      return;
    }
    onConfirm(selectedId);
  };

  return (
    <WorkArea
      title="选择题目"
      description="选一个题目作为本次内容的主线，系统会据此撰写公众号长文。"
      testId="screen-topic-selection"
      meta={<span className="badge">共 {topics.length} 个候选</span>}
    >
      {topics.length === 0 ? (
        <p className="empty">后端没有返回候选选题，请点击「重新开始」重试。</p>
      ) : (
        <fieldset className="option-list">
          <legend className="sr-only">候选选题</legend>

          {topics.map((topic) => {
            const selected = selectedId === topic.id;

            return (
              <label
                key={topic.id}
                className={classNames('option', selected && 'option--selected')}
              >
                <input
                  type="radio"
                  name="topic"
                  className="option__input"
                  value={topic.id}
                  checked={selected}
                  disabled={submitting}
                  onChange={() => setSelectedId(topic.id)}
                />

                <span className="option__main">
                  <span className="option__title">{topic.title}</span>
                  <span className="option__meta">
                    <span className="badge">{topic.angle}</span>
                    <span className="mono option__desc">{topic.id}</span>
                  </span>
                  <span className="option__desc">{topic.reason}</span>
                </span>

                {/* 选中标记：槽位恒定，只切换透明度，保证列表不跳动 */}
                <span className="option__check" aria-hidden="true">
                  <Check size={18} strokeWidth={3} />
                </span>
              </label>
            );
          })}
        </fieldset>
      )}

      <div className="actionbar">
        <Button variant="ghost" onClick={onBack} disabled={submitting}>
          返回修改方向
        </Button>

        <div className="actionbar__actions">
          {selectedId === null ? <span className="actionbar__note">请先选择一个题目</span> : null}
          <Button
            variant="primary"
            onClick={handleConfirm}
            disabled={selectedId === null}
            loading={submitting}
            loadingLabel="正在生成文章…"
            icon={<Check size={16} aria-hidden="true" />}
          >
            使用此选题
          </Button>
        </div>
      </div>
    </WorkArea>
  );
}
