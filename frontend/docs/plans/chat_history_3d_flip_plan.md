# 聊天记录展示功能 - 方案A (3D翻转卡片) 技术落地实现方案

## 1. 架构设计蓝图与 UI 交互流

### 1.1 核心思想
将 `RecentMemoryPanel` 内部的日历视图（`CalendarPanel`）和手机视图（`PhoneMockup`）视为一张 3D 卡片的正反两面。
- **正面**：完整的月视图日历（现有的 `CalendarPanel`）。
- **反面**：拟物化手机界面（`PhoneMockup`），其内部包含横向日期滑动条和聊天记录列表。

### 1.2 交互流规划
1. **初始状态**：用户点击导航栏的“历史日历”图标，展示 3D 卡片的正面（月视图日历）。
2. **触发翻转**：用户在月视图中点击某一个有记录的日期。
3. **翻转动画**：卡片执行绕 Y 轴旋转 180 度的 3D 动画，平滑过渡到反面（手机界面）。
4. **反面交互**：
   - 手机屏幕顶部（灵动岛下方）展示横向滚动的日期条，用户可在此快速切换相邻日期的聊天记录。
   - 手机屏幕左上角（灵动岛左侧）提供一个极简的“< 返回”按钮。
5. **返回正面**：用户点击“< 返回”按钮，卡片再次翻转 180 度，回到月视图日历。

## 2. 组件 DOM 结构重构

### 2.1 `RecentMemoryPanel.tsx` 改造
引入 3D 翻转容器结构，将 `CalendarPanel` 和 `PhoneMockupContainer` 包裹在正反面容器中。

```tsx
// 伪代码结构
<div className="recent-memory-panel calendar-view">
  <HistoryNavigation />
  
  {/* 3D 翻转场景 */}
  <div className={`flip-scene ${selectedDate ? 'is-flipped' : ''}`}>
    <div className="flip-card">
      {/* 正面：月视图日历 */}
      <div className="flip-face flip-front">
        <CalendarPanel />
      </div>
      
      {/* 反面：手机界面 */}
      <div className="flip-face flip-back">
        <PhoneMockupContainer />
      </div>
    </div>
  </div>
</div>
```

### 2.2 `PhoneMockup.tsx` 与 `ChatHistoryView.tsx` 改造
在手机屏幕内部，灵动岛下方增加横向日期滑动条和返回按钮。

```tsx
// PhoneMockup.tsx 内部结构
<div className="phone-screen">
  {/* 顶部导航区 */}
  <div className="phone-header">
    <button className="back-btn" onClick={() => setSelectedDate(null)}>
      <svg>...</svg> {/* 返回图标 */}
    </button>
    <div className="dynamic-island-placeholder"></div> {/* 占位，保持布局平衡 */}
  </div>
  
  {/* 横向日期滑动条 */}
  <HorizontalDatePicker />
  
  {/* 聊天记录列表 */}
  <ChatHistoryView />
</div>
```

## 3. 横向日期滑动条 (`HorizontalDatePicker`) 设计

### 3.1 数据逻辑
- 依赖 `historyStore` 中的 `currentYearMonth` 和 `calendarMetadata`。
- 根据当前年月生成该月的所有天数数组。
- 渲染为一个横向滚动的列表，每个日期项显示“星期几”和“日期号”。
- 带有记录的日期显示高亮小圆点。

### 3.2 交互逻辑
- 监听 `selectedDate` 的变化，当选中日期改变时，自动将对应的日期项滚动到视图中央（使用 `scrollIntoView({ behavior: 'smooth', inline: 'center' })`）。
- 用户点击横向列表中的日期，触发 `setSelectedDate`，从而更新下方的聊天记录。

## 4. CSS 布局与样式策略

### 4.1 3D 翻转核心 CSS
在 `RecentMemoryPanel.css` 中实现 3D 翻转效果，彻底解决面板重叠遮挡问题。

```css
.flip-scene {
  perspective: 1000px; /* 赋予 3D 景深 */
  width: 100%;
  flex: 1;
  position: relative;
}

.flip-card {
  width: 100%;
  height: 100%;
  position: relative;
  transition: transform 0.6s cubic-bezier(0.4, 0, 0.2, 1);
  transform-style: preserve-3d; /* 保持子元素的 3D 空间 */
}

.flip-scene.is-flipped .flip-card {
  transform: rotateY(180deg);
}

.flip-face {
  position: absolute;
  width: 100%;
  height: 100%;
  backface-visibility: hidden; /* 隐藏背面 */
  display: flex;
  flex-direction: column;
}

.flip-front {
  /* 正面默认状态 */
}

.flip-back {
  transform: rotateY(180deg); /* 反面初始翻转 180 度 */
  align-items: center; /* 居中手机模型 */
}
```

### 4.2 横向日期滑动条 CSS
在 `PhoneMockup.css` 或新建的样式文件中实现横向滚动隐藏滚动条的优雅布局。

```css
.horizontal-date-picker {
  display: flex;
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  scrollbar-width: none; /* Firefox 隐藏滚动条 */
  padding: 10px 16px;
  gap: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.horizontal-date-picker::-webkit-scrollbar {
  display: none; /* Chrome/Safari 隐藏滚动条 */
}

.date-item {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 12px;
  border-radius: 12px;
  scroll-snap-align: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.date-item.selected {
  background: rgba(160, 130, 255, 0.2);
  border: 1px solid rgba(160, 130, 255, 0.5);
}
```

### 4.3 返回按钮布局
利用 Flexbox 确保返回按钮位于左上角，不与灵动岛冲突。

```css
.phone-header {
  display: flex;
  align-items: center;
  padding: 12px 16px 0;
  height: 44px; /* 匹配灵动岛高度区域 */
}

.back-btn {
  background: transparent;
  border: none;
  color: #a082ff;
  cursor: pointer;
  display: flex;
  align-items: center;
  padding: 4px;
  margin-left: -4px;
  z-index: 20;
}
```

## 5. 关键代码改造步骤

1. **清理旧布局**：移除 `RecentMemoryPanel.tsx` 中原有的 `PhoneMockupContainer` 外部渲染逻辑。
2. **构建 3D 容器**：在 `RecentMemoryPanel.tsx` 中引入 `flip-scene` 和 `flip-card` 结构。
3. **实现横向选择器**：新建 `HorizontalDatePicker` 组件，实现日期列表渲染和自动居中滚动逻辑。
4. **组装手机界面**：在 `PhoneMockup.tsx` 中整合 `phone-header` (含返回按钮)、`HorizontalDatePicker` 和 `ChatHistoryView`。
5. **调整样式**：应用上述 3D 翻转和横向滚动的 CSS 规则，微调高度和边距，确保在不同状态下均无滚动条重叠或内容溢出。