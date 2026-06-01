# Python Scripts in `src/main/resources/python`

## `embedding.py`
```python
import sys
import json
import traceback
from sentence_transformers import SentenceTransformer

def get_embedding(model_path, text):
    # 模型路径由参数传入
    model = SentenceTransformer(model_path)
    vec = model.encode(text).tolist()
    return vec

if __name__ == "__main__":
    # 参数顺序: 脚本路径, 模型路径, 文本
    if len(sys.argv) < 3:
        sys.stderr.write("Error: Missing arguments. Usage: python embedding.py <model_path> <text>\n")
        sys.exit(1)

    model_path = sys.argv[1]
    text = sys.argv[2]

    try:
        vector = get_embedding(model_path, text)
        print(json.dumps(vector, ensure_ascii=False))
    except Exception as e:
        # 将错误信息写入标准错误流 (stderr)，以便 Java 端捕获
        sys.stderr.write(f"Python Script Error: {str(e)}\n")
        traceback.print_exc(file=sys.stderr)
        # 以非 0 状态码退出，表示执行失败
        sys.exit(1)
```

## `embedding_service_http.py`
```python
import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("embedding-http")

model = None


def json_response(handler: BaseHTTPRequestHandler, status_code: int, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class EmbeddingHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/embedding":
            json_response(self, 404, {"vector_json": "[]", "success": False, "error_message": "not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            req = json.loads(raw.decode("utf-8"))
            text = (req.get("text") or "").strip()

            if not text:
                json_response(self, 200, {"vector_json": "[]", "success": False, "error_message": "text is blank"})
                return

            vec = model.encode(text).tolist()
            json_response(
                self,
                200,
                {
                    "vector_json": json.dumps(vec, ensure_ascii=False),
                    "success": True,
                    "error_message": ""
                }
            )
        except Exception as e:
            logger.exception("embedding request failed")
            json_response(self, 200, {"vector_json": "[]", "success": False, "error_message": str(e)})

    def log_message(self, format, *args):
        logger.info("%s - %s", self.address_string(), format % args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--embedding-model-path", required=True)
    args = parser.parse_args()

    logger.info("加载 embedding 模型: %s", args.embedding_model_path)
    model = SentenceTransformer(args.embedding_model_path)
    logger.info("embedding 模型加载完成，启动 HTTP 服务: %s:%s", args.host, args.port)

    server = ThreadingHTTPServer((args.host, args.port), EmbeddingHandler)
    server.serve_forever()
```

## `luna_inference_grpc_server.py`
```python
import json
import logging
from concurrent import futures

import grpc
from sentence_transformers import SentenceTransformer, CrossEncoder

import luna_inference_pb2
import luna_inference_pb2_grpc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("luna-inference-grpc")


class LunaInferenceService(luna_inference_pb2_grpc.LunaInferenceServiceServicer):
    def __init__(self, embedding_model_path: str, rerank_model_path: str):
        logger.info("加载 embedding 模型: %s", embedding_model_path)
        self.embedding_model = SentenceTransformer(embedding_model_path)
        logger.info("加载 rerank 模型: %s", rerank_model_path)
        self.rerank_model = CrossEncoder(rerank_model_path, max_length=1024, trust_remote_code=True)
        logger.info("模型加载完成，服务可用")

    def Embedding(self, request, context):
        try:
            text = request.text or ""
            if not text.strip():
                return luna_inference_pb2.EmbeddingResponse(
                    vector_json="[]",
                    success=False,
                    error_message="text is blank"
                )
            vec = self.embedding_model.encode(text).tolist()
            return luna_inference_pb2.EmbeddingResponse(
                vector_json=json.dumps(vec, ensure_ascii=False),
                success=True,
                error_message=""
            )
        except Exception as e:
            logger.exception("Embedding 调用失败")
            return luna_inference_pb2.EmbeddingResponse(
                vector_json="[]",
                success=False,
                error_message=str(e)
            )

    def Rerank(self, request, context):
        try:
            query = request.query or ""
            docs = list(request.documents)
            if not query.strip():
                return luna_inference_pb2.RerankResponse(
                    scores=[],
                    success=False,
                    error_message="query is blank"
                )
            if not docs:
                return luna_inference_pb2.RerankResponse(
                    scores=[],
                    success=True,
                    error_message=""
                )
            pairs = [[query, d] for d in docs]
            scores = self.rerank_model.predict(pairs).tolist()
            return luna_inference_pb2.RerankResponse(
                scores=scores,
                success=True,
                error_message=""
            )
        except Exception as e:
            logger.exception("Rerank 调用失败")
            return luna_inference_pb2.RerankResponse(
                scores=[],
                success=False,
                error_message=str(e)
            )


def serve(
        host: str = "127.0.0.1",
        port: int = 50051,
        embedding_model_path: str = "",
        rerank_model_path: str = ""
):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    luna_inference_pb2_grpc.add_LunaInferenceServiceServicer_to_server(
        LunaInferenceService(embedding_model_path, rerank_model_path),
        server
    )
    bind_addr = f"{host}:{port}"
    server.add_insecure_port(bind_addr)
    server.start()
    logger.info("Luna Inference gRPC 服务已启动: %s", bind_addr)
    server.wait_for_termination()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50051)
    parser.add_argument("--embedding-model-path", required=True)
    parser.add_argument("--rerank-model-path", required=True)
    args = parser.parse_args()

    serve(
        host=args.host,
        port=args.port,
        embedding_model_path=args.embedding_model_path,
        rerank_model_path=args.rerank_model_path
    )
```

## `rerank.py`
```python
import sys
import json
import traceback
# 需確保 Python 環境中已安裝 sentence-transformers
from sentence_transformers import CrossEncoder

def get_scores(model_path, query, documents):
    # 加載 CrossEncoder 模型
    # max_length 根據模型限制設定，bge-reranker-v2-m3 支持較長上下文，這裡設為 1024 以平衡性能
    model = CrossEncoder(model_path, max_length=1024, trust_remote_code=True)
    
    # 構造 (query, doc) 對
    pairs = [[query, doc] for doc in documents]
    
    # 預測分數，返回 numpy array
    scores = model.predict(pairs)
    
    # 轉換為 list 返回
    return scores.tolist()

if __name__ == "__main__":
    # 參數: 腳本路徑, 模型路徑
    # 注意：Query 和 Documents 通過 Stdin 傳入 JSON
    if len(sys.argv) < 2:
        sys.stderr.write("Error: Missing model_path argument. Usage: python rerank.py <model_path>\n")
        sys.exit(1)

    model_path = sys.argv[1]

    try:
        # 從標準輸入讀取 JSON 數據
        # 格式: { "query": "...", "documents": ["doc1", "doc2", ...] }
        # 使用 sys.stdin.read() 確保讀取完整輸入
        input_str = sys.stdin.read()
        if not input_str:
             raise ValueError("Empty input from stdin")
             
        input_data = json.loads(input_str)
        
        query = input_data.get("query")
        documents = input_data.get("documents")

        if not query or documents is None:
            raise ValueError("Input JSON must contain 'query' and 'documents' fields.")

        if len(documents) == 0:
            print("[]")
            sys.exit(0)

        scores = get_scores(model_path, query, documents)
        
        # 輸出分數列表 JSON
        print(json.dumps(scores, ensure_ascii=False))
        
    except Exception as e:
        # 將錯誤信息寫入標準錯誤流 (stderr)
        sys.stderr.write(f"Python Rerank Script Error: {str(e)}\n")
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
```

## `rerank_service_http.py`
```python
import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from sentence_transformers import CrossEncoder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rerank-http")

model = None


def json_response(handler: BaseHTTPRequestHandler, status_code: int, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class RerankHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/rerank":
            json_response(self, 404, {"scores": [], "success": False, "error_message": "not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            req = json.loads(raw.decode("utf-8"))

            query = (req.get("query") or "").strip()
            docs = req.get("documents") or []

            if not query:
                json_response(self, 200, {"scores": [], "success": False, "error_message": "query is blank"})
                return

            if not docs:
                json_response(self, 200, {"scores": [], "success": True, "error_message": ""})
                return

            pairs = [[query, d] for d in docs]
            scores = model.predict(pairs).tolist()

            json_response(self, 200, {"scores": scores, "success": True, "error_message": ""})
        except Exception as e:
            logger.exception("rerank request failed")
            json_response(self, 200, {"scores": [], "success": False, "error_message": str(e)})

    def log_message(self, format, *args):
        logger.info("%s - %s", self.address_string(), format % args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--rerank-model-path", required=True)
    args = parser.parse_args()

    logger.info("加载 rerank 模型: %s", args.rerank_model_path)
    model = CrossEncoder(args.rerank_model_path, max_length=1024, trust_remote_code=True)
    logger.info("rerank 模型加载完成，启动 HTTP 服务: %s:%s", args.host, args.port)

    server = ThreadingHTTPServer((args.host, args.port), RerankHandler)
    server.serve_forever()




## 相关路径
embedding:
  python-path: D:/AI_Models/BGE-base-zh-v1.5/bge-env/Scripts/python.exe
  script-path: ./python/embedding.py
  model-path: D:/AI_Models/bge-base-zh-v1.5-model
