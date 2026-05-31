package config

import (
	"sync"
)

// EventType 定义事件类型
type EventType string

const (
	// EventConfigChanged 配置变更事件
	EventConfigChanged EventType = "ConfigChanged"
)

// Event 定义事件结构
type Event struct {
	Type EventType
	Data interface{}
}

// EventHandler 定义事件处理器函数签名
type EventHandler func(event Event)

// EventBus 提供简单的发布订阅机制
type EventBus struct {
	mu       sync.RWMutex
	handlers map[EventType][]EventHandler
}

// NewEventBus 创建一个新的 EventBus
func NewEventBus() *EventBus {
	return &EventBus{
		handlers: make(map[EventType][]EventHandler),
	}
}

// Subscribe 订阅指定类型的事件
func (b *EventBus) Subscribe(eventType EventType, handler EventHandler) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.handlers[eventType] = append(b.handlers[eventType], handler)
}

// Publish 发布事件
func (b *EventBus) Publish(event Event) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if handlers, ok := b.handlers[event.Type]; ok {
		for _, handler := range handlers {
			// 异步执行处理器，避免阻塞发布者
			go handler(event)
		}
	}
}
