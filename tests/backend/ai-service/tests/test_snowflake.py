import pytest
import threading
import time
from app.utils.snowflake import Snowflake, generate_id, generate_string_id, init_global_node

def test_snowflake_unique_ids():
    node = Snowflake(1)
    id1 = node.generate()
    id2 = node.generate()
    
    assert id1 != id2
    assert id1 < id2

def test_snowflake_invalid_node():
    with pytest.raises(ValueError):
        Snowflake(-1)
        
    with pytest.raises(ValueError):
        Snowflake(1024)

def test_snowflake_concurrency():
    node = Snowflake(1)
    num_threads = 10
    ids_per_thread = 1000
    
    generated_ids = []
    lock = threading.Lock()
    
    def generate_worker():
        local_ids = []
        for _ in range(ids_per_thread):
            local_ids.append(node.generate())
            
        with lock:
            generated_ids.extend(local_ids)
            
    threads = []
    for _ in range(num_threads):
        t = threading.Thread(target=generate_worker)
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    # Check for duplicates
    assert len(generated_ids) == num_threads * ids_per_thread
    assert len(set(generated_ids)) == len(generated_ids)

def test_global_node():
    init_global_node(2)
    
    id1 = generate_id()
    id2 = generate_id()
    
    assert id1 != id2
    assert isinstance(id1, int)
    
    str_id = generate_string_id()
    assert isinstance(str_id, str)
    assert len(str_id) > 0
