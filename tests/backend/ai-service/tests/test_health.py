from fastapi.testclient import TestClient

from app.types.errors import ErrorCode
from app.main import app

client = TestClient(app)

def test_health_check() -> None:
    response = client.get("/health", headers={"X-Trace-ID": "test-trace-123"})
    assert response.status_code == 200
    
    data = response.json()
    assert data["code"] == ErrorCode.SUCCESS.value
    assert data["msg"] == "success"
    assert data["trace_id"] == "test-trace-123"
    assert data["data"]["status"] == "ok"
    assert data["data"]["service"] == "luna-ai-service"
