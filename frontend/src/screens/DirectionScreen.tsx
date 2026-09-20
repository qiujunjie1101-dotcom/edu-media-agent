/**
 * 第 1 屏：创建内容任务（输入内容方向）。
 *
 * 视觉要点：
 *   - 页面标题是「创建内容任务」，下面就一句说明；不再出现「输入内容方向 / 内容方向」这种重复层级；
 *   - 输入框高度固定在 180px，首屏内完整可见，不会占满整屏；
 *   - 表单宽度收敛到 640px，避免输入框横跨整页造成的松散感；
 *   - 主操作「生成选题」放在操作区右侧，是全屏唯一的高饱和度按钮。
 *
 * 校验规则与后端完全对齐（2–200 字）：前端校验是为了让用户少走弯路，
 * 后端校验才是底线，两者都不能省。
 */

import { useState, type FormEvent } from 'react';
import { Sparkles } from 'lucide-react';

import {
  MAX_TOPIC_DIRECTION_LENGTH,
  MIN_TOPIC_DIRECTION_LENGTH,
} from '../api/types';
import { Button } from '../components/Button';
import { WorkArea } from '../components/WorkArea';

interface DirectionScreenProps {
  /** 是否正在提交（提交期间禁止重复点击） */
  submitting: boolean;
  onSubmit: (direction: string) => void;
  /** 初始内容：从「返回修改方向」回来时带上上一次的方向，避免用户重新打字 */
  initialDirection?: string;
}

export function DirectionScreen({
  submitting,
  onSubmit,
  initialDirection = '',
}: DirectionScreenProps) {
  const [value, setValue] = useState<string>(initialDirection);

  // 用 Array.from 而不是 value.length：后者按 UTF-16 码元计数，
  // 会把一个 emoji 算成 2 个字，与后端 Python 的 len() 不一致。
  const totalChars = Array.from(value).length;
  const trimmedChars = Array.from(value.trim()).length;
  /** 有输入但去掉空白后不足 2 字（例如只打了两个空格） */
  const tooShort = totalChars > 0 && trimmedChars < MIN_TOPIC_DIRECTION_LENGTH;
  const canSubmit = trimmedChars >= MIN_TOPIC_DIRECTION_LENGTH && !submitting;

  const handleChange = (next: string): void => {
    // 超出上限直接截断，而不是等提交后才被拒绝
    setValue(Array.from(next).slice(0, MAX_TOPIC_DIRECTION_LENGTH).join(''));
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    onSubmit(value.trim());
  };

  return (
    <WorkArea
      title="创建内容任务"
      description="写清楚面向谁、讲什么，系统会据此生成 3–5 个候选选题。"
      testId="screen-direction"
    >
      <form className="form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label className="field__label" htmlFor="topic-direction">
            内容方向
          </label>

          <textarea
            id="topic-direction"
            className="textarea textarea--direction"
            value={value}
            placeholder="例如：面向零基础学员讲清楚 LangGraph 的检查点机制"
            aria-describedby={
              tooShort ? 'topic-direction-foot topic-direction-error' : 'topic-direction-foot'
            }
            aria-invalid={tooShort}
            disabled={submitting}
            onChange={(event) => handleChange(event.target.value)}
          />

          <div className="field__foot" id="topic-direction-foot">
            <span>
              {MIN_TOPIC_DIRECTION_LENGTH}–{MAX_TOPIC_DIRECTION_LENGTH}
              字，描述越具体，选题越贴近业务
            </span>
            <span className={tooShort ? 'field__count field__count--warn' : 'field__count'}>
              {totalChars} / {MAX_TOPIC_DIRECTION_LENGTH}
            </span>
          </div>

          {tooShort ? (
            <p className="field__error" id="topic-direction-error">
              内容方向至少需要 {MIN_TOPIC_DIRECTION_LENGTH} 个字
            </p>
          ) : null}
        </div>

        <div className="form__actions">
          <Button
            type="submit"
            variant="primary"
            disabled={!canSubmit}
            loading={submitting}
            loadingLabel="正在生成选题…"
            icon={<Sparkles size={16} aria-hidden="true" />}
          >
            生成选题
          </Button>
        </div>
      </form>
    </WorkArea>
  );
}
