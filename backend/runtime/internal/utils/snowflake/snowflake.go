package snowflake

import (
	"errors"
	"strconv"
	"sync"
	"time"
)

const (
	// Epoch is set to 2024-01-01 00:00:00 UTC
	Epoch int64 = 1704067200000

	// Number of bits for each part
	NodeBits     uint8 = 10
	SequenceBits uint8 = 12

	// Maximum values
	MaxNode     int64 = -1 ^ (-1 << NodeBits)
	MaxSequence int64 = -1 ^ (-1 << SequenceBits)

	// Shifts
	NodeShift      uint8 = SequenceBits
	TimestampShift uint8 = SequenceBits + NodeBits
)

// Node represents a snowflake ID generator node
type Node struct {
	mu        sync.Mutex
	timestamp int64
	nodeID    int64
	sequence  int64
}

// NewNode creates a new snowflake node
// nodeID 必须在 0 到 1023 之间
func NewNode(nodeID int64) (*Node, error) {
	if nodeID < 0 || nodeID > MaxNode {
		return nil, errors.New("node ID must be between 0 and 1023")
	}
	return &Node{
		timestamp: 0,
		nodeID:    nodeID,
		sequence:  0,
	}, nil
}

// Generate creates and returns a unique snowflake ID
func (n *Node) Generate() int64 {
	n.mu.Lock()
	defer n.mu.Unlock()

	now := time.Now().UnixMilli()

	if n.timestamp == now {
		n.sequence = (n.sequence + 1) & MaxSequence
		if n.sequence == 0 {
			// Sequence overflow, wait for next millisecond
			for now <= n.timestamp {
				now = time.Now().UnixMilli()
			}
		}
	} else {
		n.sequence = 0
	}

	n.timestamp = now

	id := ((now - Epoch) << TimestampShift) |
		(n.nodeID << NodeShift) |
		(n.sequence)

	return id
}

// Global instance for convenience
var (
	globalNode *Node
	once       sync.Once
)

// InitGlobalNode initializes the global snowflake node
func InitGlobalNode(nodeID int64) error {
	var err error
	once.Do(func() {
		globalNode, err = NewNode(nodeID)
	})
	return err
}

// GenerateID generates an ID using the global node
func GenerateID() int64 {
	if globalNode == nil {
		// Fallback to node 1 if not initialized
		_ = InitGlobalNode(1)
	}
	return globalNode.Generate()
}

// GenerateStringID generates an ID and returns it as a string
// 推荐在与前端交互或 JSON 序列化时使用，避免 JS 精度丢失
func GenerateStringID() string {
	return strconv.FormatInt(GenerateID(), 10)
}
