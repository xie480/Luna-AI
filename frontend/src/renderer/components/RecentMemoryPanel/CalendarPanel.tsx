import React, { useEffect } from 'react';
import { useHistoryStore } from '../../stores/historyStore';
import './CalendarPanel.css';

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

  const handleYearChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setCurrentYearMonth(`${e.target.value}-${String(month).padStart(2, '0')}`);
  };

  const handleMonthChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setCurrentYearMonth(`${year}-${String(e.target.value).padStart(2, '0')}`);
  };

  // 生成年份选项 (前后 5 年)
  const currentYear = new Date().getFullYear();
  const yearOptions = Array.from({ length: 11 }, (_, i) => currentYear - 5 + i);
  
  // 生成月份选项
  const monthOptions = Array.from({ length: 12 }, (_, i) => i + 1);

  const handleDateClick = (day: number) => {
    const dateStr = `${currentYearMonth}-${String(day).padStart(2, '0')}`;
    if (calendarMetadata[dateStr]) {
      setSelectedDate(dateStr);
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
        <button className="month-nav-btn" onClick={handlePrevMonth}>
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" strokeWidth="2" fill="none">
            <polyline points="15 18 9 12 15 6"></polyline>
          </svg>
        </button>
        <div className="current-month-display">
          <div className="select-wrapper">
            <select value={year} onChange={handleYearChange} className="year-select">
              {yearOptions.map(y => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </div>
          <div className="select-wrapper">
            <select value={month} onChange={handleMonthChange} className="month-select">
              {monthOptions.map(m => (
                <option key={m} value={m}>{String(m).padStart(2, '0')}</option>
              ))}
            </select>
          </div>
        </div>
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
