import asyncio
import json
import time
import websockets

async def test_ping_pong():
    """测试 WebSocket Ping/Pong 通信链路"""
    uri = "ws://localhost:8080/ws"
    
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to WebSocket server")
            
            # 发送 Ping 消息
            trace_id = f"test-{time.time()}"
            ping_msg = {
                "type": "PING",
                "trace_id": trace_id,
                "payload": {
                    "timestamp": int(time.time() * 1000)
                }
            }
            
            print(f"Sending PING message: {json.dumps(ping_msg, indent=2)}")
            await websocket.send(json.dumps(ping_msg))
            
            # 接收响应
            response = await websocket.recv()
            pong_msg = json.loads(response)
            
            print(f"Received response: {json.dumps(pong_msg, indent=2)}")
            
            # 验证响应
            if pong_msg.get("type") == "PONG":
                print(f"[OK] Test passed! trace_id={pong_msg.get('trace_id')}")
                print(f"[OK] source={pong_msg['payload'].get('source')}")
                return True
            else:
                print(f"[FAIL] Test failed: received non-PONG response")
                return False
                
    except Exception as e:
        print(f"[FAIL] Connection failed: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_ping_pong())
    if result:
        print("\n=== Phase 1 Three-layer communication verification PASSED ===")
    else:
        print("\n=== Phase 1 Three-layer communication verification FAILED ===")