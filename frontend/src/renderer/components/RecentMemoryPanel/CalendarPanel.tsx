import React, { useEffect, useRef, useState } from 'react';
import { useHistoryStore } from '../../stores/historyStore';
import './CalendarPanel.css';

interface WheelPickerProps {
  options: number[];
  value: number;
  onChange: (val: number) => void;
  formatOption?: (val: number) => string;
}

const WheelPicker: React.FC<WheelPickerProps> = ({ options, value, onChange, formatOption = (v) => String(v) }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const itemHeight = 36; // px
  const isScrolling = useRef(false);
  const scrollTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (containerRef.current && !isScrolling.current) {
      const index = options.indexOf(value);
      if (index !== -1) {
        containerRef.current.scrollTop = index * itemHeight;
      }
    }
  }, [value, options]);

  const handleScroll = () => {
    isScrolling.current = true;
    if (scrollTimeout.current) clearTimeout(scrollTimeout.current);
    
    scrollTimeout.current = setTimeout(() => {
      isScrolling.current = false;
      if (containerRef.current) {
        const index = Math.round(containerRef.current.scrollTop / itemHeight);
        if (options[index] !== undefined && options[index] !== value) {
          onChange(options[index]);
        }
      }
    }, 150);
  };

  return (
    <div className="wheel-picker-container">
      <div className="wheel-picker-selection-overlay"></div>
      <div 
        className="wheel-picker-scroll" 
        ref={containerRef} 
        onScroll={handleScroll}
      >
        <div className="wheel-picker-padding"></div>
        {options.map((opt) => (
          <div 
            key={opt} 
            className={`wheel-picker-item ${opt === value ? 'selected' : ''}`}
            onClick={() => {
              if (containerRef.current) {
                const index = options.indexOf(opt);
                containerRef.current.scrollTo({ top: index * itemHeight, behavior: 'smooth' });
                onChange(opt);
              }
            }}
          >
            {formatOption(opt)}
          </div>
        ))}
        <div className="wheel-picker-padding"></div>
      </div>
    </div>
  );
};

export const CalendarPanel: React.FC = () => {
  const { 
    currentYearMonth, 
    setCurrentYearMonth, 
    calendarMetadata, 
    selectedDate, 
    setSelectedDate,
    isLoadingMetadata
  } = useHistoryStore();

  const [year, month] = currentYearMonth.split('-').map(Number);

  // 生成日历网格数据
  const getDaysInMonth = (y: number, m: number) => new Date(y, m, 0).getDate();
  const getFirstDayOfMonth = (y: number, m: number) => new Date(y, m - 1, 1).getDay();

  const daysInMonth = getDaysInMonth(year, month);
  const firstDay = getFirstDayOfMonth(year, month);
  
  const days = Array.from({ length: daysInMonth }, (_, i) => i + 1);
  const blanks = Array.from({ length: firstDay === 0 ? 6 : firstDay - 1 }, (_, i) => i); // 调整周一为第一天

  const handlePrevMonth = () => {
    let newMonth = month - 1;
    let newYear = year;
    if (newMonth < 1) {
      newMonth = 12;
      newYear -= 1;
    }
    setCurrentYearMonth(`${newYear}-${String(newMonth).padStart(2, '0')}`);
  };

  const handleNextMonth = () => {
    let newMonth = month + 1;
    let newYear = year;
    if (newMonth > 12) {
      newMonth = 1;
      newYear += 1;
    }
    setCurrentYearMonth(`${newYear}-${String(newMonth).padStart(2, '0')}`);
  };

  const [isPickerOpen, setIsPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);

  // 生成年份选项 (前后 5 年)
  const currentYear = new Date().getFullYear();
  const yearOptions = Array.from({ length: 11 }, (_, i) => currentYear - 5 + i);
  
  // 生成月份选项
  const monthOptions = Array.from({ length: 12 }, (_, i) => i + 1);

  // 点击外部关闭下拉框
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setIsPickerOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleDateClick = (day: number) => {
    const dateStr = `${currentYearMonth}-${String(day).padStart(2, '0')}`;
    if (calendarMetadata[dateStr]) {
      // 如果点击的是当前已选中的日期，则取消选中（关闭手机界面）
      if (selectedDate === dateStr) {
        setSelectedDate(null);
      } else {
        setSelectedDate(dateStr);
      }
    }
  };

  const today = new Date();
  const isCurrentMonth = today.getFullYear() === year && today.getMonth() + 1 === month;
  const todayDate = today.getDate();

  // 初始加载时获取当前月的元数据
  useEffect(() => {
    const { fetchCalendarMetadata } = useHistoryStore.getState();
    fetchCalendarMetadata(currentYearMonth);
  }, [currentYearMonth]);

  return (
    <div className="calendar-panel-container">
      <div className="calendar-header">
        {/* 修复月份切换按钮位置：左侧按钮切换到上个月 */}
        <button className="month-nav-btn" onClick={handlePrevMonth}>
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" strokeWidth="2" fill="none">
            <polyline points="15 18 9 12 15 6"></polyline>
          </svg>
        </button>
        
        <div className="current-month-display-wrapper" ref={pickerRef}>
          <div className="current-month-display" onClick={() => setIsPickerOpen(!isPickerOpen)}>
            <span className="year-text">{year}年</span>
            <span className="month-text">{String(month).padStart(2, '0')}月</span>
            <svg className={`picker-arrow ${isPickerOpen ? 'open' : ''}`} viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" strokeWidth="2" fill="none">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </div>
          
          {isPickerOpen && (
            <div className="wheel-picker-popover">
              <WheelPicker 
                options={yearOptions} 
                value={year} 
                onChange={(y) => setCurrentYearMonth(`${y}-${String(month).padStart(2, '0')}`)} 
                formatOption={(v) => `${v}年`} 
              />
              <WheelPicker 
                options={monthOptions} 
                value={month} 
                onChange={(m) => setCurrentYearMonth(`${year}-${String(m).padStart(2, '0')}`)} 
                formatOption={(v) => `${String(v).padStart(2, '0')}月`} 
              />
            </div>
          )}
        </div>

        {/* 修复月份切换按钮位置：右侧按钮切换到下个月 */}
        <button className="month-nav-btn" onClick={handleNextMonth}>
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" strokeWidth="2" fill="none">
            <polyline points="9 18 15 12 9 6"></polyline>
          </svg>
        </button>
      </div>

      <div className={`calendar-grid ${isLoadingMetadata ? 'loading' : ''}`}>
        <div className="weekdays">
          <span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span>
        </div>
        <div className="days">
          {blanks.map((_, i) => (
            <div key={`blank-${i}`} className="day-cell empty"></div>
          ))}
          {days.map(day => {
            const dateStr = `${currentYearMonth}-${String(day).padStart(2, '0')}`;
            const hasRecord = calendarMetadata[dateStr];
            const isSelected = selectedDate === dateStr;
            const isToday = isCurrentMonth && day === todayDate;

            return (
              <div 
                key={day} 
                className={`day-cell ${hasRecord ? 'has-record' : 'no-record'} ${isSelected ? 'selected' : ''} ${isToday ? 'today' : ''}`}
                onClick={() => handleDateClick(day)}
              >
                <span className="day-number">{day}</span>
                {hasRecord && <div className="record-dot"></div>}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
