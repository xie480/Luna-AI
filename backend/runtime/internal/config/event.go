package config

import (
	"sync"
)

// EventType 定义配置变更事件类型
type EventType string

const (
	// ConfigChangedEvent 配置变更事件
	ConfigChangedEvent EventType = "ConfigChanged"
)

// Event 定义事件结构
type Event struct {
	Type EventType
	Data interface{}
}

// EventHandler 定义事件处理器函数签名
type EventHandler func(Event)

// EventBus 提供简单的发布订阅机制
type EventBus struct {
	handlers map[EventType][]EventHandler
	mu       sync.RWMutex
}

// NewEventBus 创建一个新的 EventBus
func NewEventBus() *EventBus {
	return &EventBus{
		handlers: make(map[EventType][]EventHandler),
	}
}

// Subscribe 订阅指定类型的事件
func (eb *EventBus) Subscribe(eventType EventType, handler EventHandler) {
	eb.mu.Lock()
	defer eb.mu.Unlock()
	eb.handlers[eventType] = append(eb.handlers[eventType], handler)
}

// Publish 发布事件
func (eb *EventBus) Publish(event Event) {
	eb.mu.RLock()
	defer eb.mu.RUnlock()
	if handlers, ok := eb.handlers[event.Type]; ok {
		for _, handler := range handlers {
			go handler(event) // 异步执行处理器
		}
	}
}
