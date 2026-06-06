"""
pytest 配置文件：在测试环境中模拟未安装的 qdrant_client 模块

做什么：在测试会话开始时将 qdrant_client 注入 sys.modules，确保
     app.infrastructure.qdrant 中的延迟导入不会因为 qdrant_client
     包未安装而抛出 ModuleNotFoundError。
为什么这样做：qdrant_client 是重依赖（含 gRPC），CI/开发环境中可能未安装，
     但 QdrantClientWrapper 的测试应当能够独立运行。
"""

import os
import sys
from unittest.mock import MagicMock

# 解决 gRPC 生成文件的绝对导入问题
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../../backend/ai-service/app/api'))

# 创建 qdrant_client 模块的模拟
# qdrant_client 本身
mock_qdrant_client = MagicMock()
mock_qdrant_client.__version__ = "1.8.0"

# qdrant_client.http 子模块
mock_qdrant_http = MagicMock()
mock_qdrant_http.models = MagicMock()
mock_qdrant_http.models.VectorParams = MagicMock
mock_qdrant_http.models.Distance = MagicMock
mock_qdrant_http.models.PointStruct = MagicMock
mock_qdrant_http.models.PointIdsList = MagicMock

# qdrant_client.http.models 模拟细节
mock_qdrant_http.models.Distance.COSINE = "Cosine"

# 注入 sys.modules
sys.modules["qdrant_client"] = mock_qdrant_client
sys.modules["qdrant_client.http"] = mock_qdrant_http
sys.modules["qdrant_client.http.models"] = mock_qdrant_http.models
