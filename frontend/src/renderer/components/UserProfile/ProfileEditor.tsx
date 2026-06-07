/**
 * 用户画像编辑器组件。
 *
 * 做什么：复用一套表单完成手动新增和编辑画像。
 * 为什么这样做：新增与编辑的字段和校验规则一致，复用组件可避免规则分散导致协议不一致。
 * 输入输出：输入为模式、初始值、保存状态和回调；输出为符合 user_profile.v1 的 MutationPayload。
 * 边界条件：内容限制 4 到 200 字；选择 custom 时必须填写自定义类别。
 * 异常行为：表单校验失败只展示本地中文提示，不向后端发请求；后端失败由 Store 页面错误条展示。
 */
import React, { useEffect, useMemo, useState } from 'react';
import { USER_PROFILE_CATEGORY, USER_PROFILE_SCHEMA_VERSION } from '../../../shared/enum';
import {
  UserProfileCategory,
  UserProfileItem,
  UserProfileMutationPayload,
  USER_PROFILE_CATEGORY_OPTIONS,
  USER_PROFILE_CONTENT_MAX_LENGTH,
  USER_PROFILE_CONTENT_MIN_LENGTH,
  USER_PROFILE_CUSTOM_CATEGORY_MAX_LENGTH,
} from '../../types/userProfile';

interface ProfileEditorProps {
  mode: 'create' | 'edit';
  initialValue?: UserProfileItem;
  isSaving: boolean;
  onSubmit: (payload: UserProfileMutationPayload) => Promise<void>;
  onCancel?: () => void;
}

/** 根据当前表单字段生成中文校验错误。 */
function validateProfileForm(category: UserProfileCategory, customCategoryName: string, content: string): string | null {
  const normalizedContent = content.trim();
  if (normalizedContent.length < USER_PROFILE_CONTENT_MIN_LENGTH) {
    return '画像内容至少需要 4 个字';
  }
  if (normalizedContent.length > USER_PROFILE_CONTENT_MAX_LENGTH) {
    return '画像内容不能超过 200 个字';
  }
  if (category === USER_PROFILE_CATEGORY.CUSTOM && !customCategoryName.trim()) {
    return '选择自定义类别时必须填写类别名称';
  }
  if (customCategoryName.trim().length > USER_PROFILE_CUSTOM_CATEGORY_MAX_LENGTH) {
    return '自定义类别名称不能超过 64 个字';
  }
  return null;
}

export const ProfileEditor: React.FC<ProfileEditorProps> = ({ mode, initialValue, isSaving, onSubmit, onCancel }) => {
  const [category, setCategory] = useState<UserProfileCategory>(initialValue?.category || USER_PROFILE_CATEGORY.LIKES);
  const [customCategoryName, setCustomCategoryName] = useState(initialValue?.custom_category_name || '');
  const [content, setContent] = useState(initialValue?.content || '');
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (initialValue) {
      setCategory(initialValue.category);
      setCustomCategoryName(initialValue.custom_category_name || '');
      setContent(initialValue.content);
      setLocalError(null);
    }
  }, [initialValue]);

  const contentCountText = useMemo(() => `${content.trim().length}/${USER_PROFILE_CONTENT_MAX_LENGTH}`, [content]);

  /** 提交表单，校验通过后交给 Store Action 与后端确认。 */
  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const validationError = validateProfileForm(category, customCategoryName, content);
    if (validationError) {
      setLocalError(validationError);
      return;
    }

    setLocalError(null);
    await onSubmit({
      schema_version: USER_PROFILE_SCHEMA_VERSION,
      category,
      custom_category_name: category === USER_PROFILE_CATEGORY.CUSTOM ? customCategoryName.trim() : null,
      content: content.trim(),
    });

    if (mode === 'create') {
      setCategory(USER_PROFILE_CATEGORY.LIKES);
      setCustomCategoryName('');
      setContent('');
    }
  };

  return (
    <form className={`profile-editor profile-editor-${mode}`} onSubmit={handleSubmit}>
      <div className="profile-editor-grid">
        <label className="profile-field">
          <span>类别</span>
          <select
            value={category}
            disabled={isSaving}
            onChange={(event) => setCategory(event.target.value as UserProfileCategory)}
          >
            {USER_PROFILE_CATEGORY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        {category === USER_PROFILE_CATEGORY.CUSTOM && (
          <label className="profile-field">
            <span>自定义类别</span>
            <input
              type="text"
              value={customCategoryName}
              maxLength={USER_PROFILE_CUSTOM_CATEGORY_MAX_LENGTH}
              disabled={isSaving}
              placeholder="例如：学习方式"
              onChange={(event) => setCustomCategoryName(event.target.value)}
            />
          </label>
        )}
      </div>

      <label className="profile-field profile-field-content">
        <span>画像内容</span>
        <textarea
          value={content}
          minLength={USER_PROFILE_CONTENT_MIN_LENGTH}
          maxLength={USER_PROFILE_CONTENT_MAX_LENGTH}
          disabled={isSaving}
          placeholder="请填写稳定、明确、与你本人相关的信息，例如：我平时只喝无糖咖啡。"
          onChange={(event) => setContent(event.target.value)}
        />
      </label>

      <div className="profile-editor-footer">
        <span className={`profile-content-counter ${content.trim().length > USER_PROFILE_CONTENT_MAX_LENGTH ? 'over-limit' : ''}`}>
          {contentCountText}
        </span>
        {localError && <span className="profile-local-error">{localError}</span>}
        <div className="profile-editor-actions">
          {onCancel && (
            <button type="button" className="user-profile-ghost-button" onClick={onCancel} disabled={isSaving}>
              取消
            </button>
          )}
          <button type="submit" className="user-profile-primary-button" disabled={isSaving}>
            {isSaving ? '保存中...' : mode === 'create' ? '保存画像' : '保存修改'}
          </button>
        </div>
      </div>
    </form>
  );
};
