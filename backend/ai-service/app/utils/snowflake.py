import time
import threading
from typing import Optional

class Snowflake:
    """
    Snowflake ID Generator
    
    Generates 64-bit unique IDs based on Twitter's Snowflake algorithm.
    The ID is composed of:
    - 1 bit: Unused (always 0 to ensure positive numbers)
    - 41 bits: Timestamp (milliseconds since epoch)
    - 10 bits: Node ID (0-1023)
    - 12 bits: Sequence number (0-4095)
    """
    
    # Epoch is set to 2024-01-01 00:00:00 UTC
    EPOCH = 1704067200000
    
    NODE_BITS = 10
    SEQUENCE_BITS = 12
    
    MAX_NODE = -1 ^ (-1 << NODE_BITS)
    MAX_SEQUENCE = -1 ^ (-1 << SEQUENCE_BITS)
    
    NODE_SHIFT = SEQUENCE_BITS
    TIMESTAMP_SHIFT = SEQUENCE_BITS + NODE_BITS
    
    def __init__(self, node_id: int):
        """
        Creates a new Snowflake generator
        :param node_id: Node ID (0-1023)
        """
        if node_id < 0 or node_id > self.MAX_NODE:
            raise ValueError(f"Node ID must be between 0 and {self.MAX_NODE}")
            
        self.node_id = node_id
        self.sequence = 0
        self.last_timestamp = -1
        self.lock = threading.Lock()
        
    def generate(self) -> int:
        """
        Generates a new unique ID
        :return: A 64-bit integer
        """
        with self.lock:
            timestamp = self._get_current_timestamp()
            
            if timestamp < self.last_timestamp:
                raise ValueError("Clock moved backwards. Refusing to generate id")
                
            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & self.MAX_SEQUENCE
                if self.sequence == 0:
                    # Sequence overflow, wait for next millisecond
                    timestamp = self._wait_next_millis(self.last_timestamp)
            else:
                self.sequence = 0
                
            self.last_timestamp = timestamp
            
            id_ = ((timestamp - self.EPOCH) << self.TIMESTAMP_SHIFT) | \
                  (self.node_id << self.NODE_SHIFT) | \
                  self.sequence
                  
            return id_
            
    def generate_string(self) -> str:
        """
        Generates a new unique ID as a string
        :return: A string representation of the 64-bit integer
        """
        return str(self.generate())
            
    def _get_current_timestamp(self) -> int:
        return int(time.time() * 1000)
        
    def _wait_next_millis(self, last_timestamp: int) -> int:
        timestamp = self._get_current_timestamp()
        while timestamp <= last_timestamp:
            timestamp = self._get_current_timestamp()
        return timestamp

# Global instance for convenience
_global_node: Optional[Snowflake] = None
_init_lock = threading.Lock()

def init_global_node(node_id: int) -> None:
    """
    Initializes the global snowflake node
    :param node_id: Node ID (0-1023)
    """
    global _global_node
    with _init_lock:
        if _global_node is None:
            _global_node = Snowflake(node_id)

def generate_id() -> int:
    """
    Generates an ID using the global node
    :return: A unique ID as an integer
    """
    global _global_node
    if _global_node is None:
        # Fallback to node 1 if not initialized
        init_global_node(1)
    return _global_node.generate()

def generate_string_id() -> str:
    """
    Generates an ID using the global node as a string
    :return: A unique ID as a string
    """
    return str(generate_id())
