package snowflake

import (
	"testing"
	"time"
)

func TestSnowflake(t *testing.T) {
	node, err := NewNode(1)
	if err != nil {
		t.Fatalf("Failed to create node: %v", err)
	}

	id1 := node.Generate()
	id2 := node.Generate()

	if id1 == id2 {
		t.Errorf("Generated duplicate IDs: %d", id1)
	}

	if id1 > id2 {
		t.Errorf("IDs are not monotonically increasing: %d > %d", id1, id2)
	}
}

func TestSnowflakeConcurrency(t *testing.T) {
	node, err := NewNode(1)
	if err != nil {
		t.Fatalf("Failed to create node: %v", err)
	}

	const numGoroutines = 100
	const numIDsPerGoroutine = 1000

	ids := make(chan int64, numGoroutines*numIDsPerGoroutine)

	for i := 0; i < numGoroutines; i++ {
		go func() {
			for j := 0; j < numIDsPerGoroutine; j++ {
				ids <- node.Generate()
			}
		}()
	}

	time.Sleep(100 * time.Millisecond)

	idMap := make(map[int64]bool)
	for i := 0; i < numGoroutines*numIDsPerGoroutine; i++ {
		id := <-ids
		if idMap[id] {
			t.Errorf("Duplicate ID found: %d", id)
		}
		idMap[id] = true
	}
}

func TestGlobalNode(t *testing.T) {
	err := InitGlobalNode(2)
	if err != nil {
		t.Fatalf("Failed to init global node: %v", err)
	}

	id1 := GenerateID()
	id2 := GenerateID()

	if id1 == id2 {
		t.Errorf("Generated duplicate IDs: %d", id1)
	}

	strID := GenerateStringID()
	if strID == "" {
		t.Errorf("Generated empty string ID")
	}
}
