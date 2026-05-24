.PHONY: all init check test clean run run-go run-py run-fe proto proto-go proto-py

# 默认目标
all: check test

# 初始化所有依赖
init: init-go init-py init-fe

init-go:
	cd backend/runtime && go mod tidy

init-py:
	cd backend/ai-service && pip install -e .[dev]

init-fe:
	cd frontend && npm install

# 运行所有代码检查
check: check-go check-py check-fe

check-go:
	cd backend/runtime && golangci-lint run ./...

check-py:
	cd backend/ai-service && ruff check . && mypy .

check-fe:
	cd frontend && npm run lint

# 运行所有测试
test: test-go test-py test-fe

test-go:
	cd backend/runtime && go test -v ./...

test-py:
	cd backend/ai-service && pytest -v

test-fe:
	cd frontend && npm run test

# 一键启动本地最小开发环境（三个服务并行运行）
run: run-go run-py run-fe

run-go:
	cd backend/runtime && go run ./cmd/main.go

run-py:
	cd backend/ai-service && python -m app.main

run-fe:
	cd frontend && npm run dev

# 清理缓存和构建产物
clean:
	cd backend/runtime && go clean
	cd backend/ai-service && rm -rf .pytest_cache .ruff_cache .mypy_cache *.egg-info
	cd frontend && rm -rf node_modules dist

# ============================================
# Protobuf 编译相关命令
# ============================================

# 编译所有 Protobuf 文件（Go + Python）
proto: proto-go proto-py

# 编译 Go 侧 Protobuf 文件
# 输出目录: backend/runtime/shared/proto
# 注意: .proto 源文件位于 backend/shared/proto，作为跨语言契约的 SSOT
proto-go:
	cd backend/runtime && ./protoc/bin/protoc.exe \
		-I=./protoc/include \
		-I=../shared/proto \
		--go_out=./shared/proto \
		--go_opt=module=luna-ai/backend/runtime/shared/proto \
		--go-grpc_out=./shared/proto \
		--go-grpc_opt=module=luna-ai/backend/runtime/shared/proto \
		../shared/proto/communication.proto

# 编译 Python 侧 Protobuf 文件
# 输出目录: backend/ai-service/app/api
proto-py:
	cd backend/runtime && ./protoc/bin/protoc.exe \
		-I=./protoc/include \
		-I=../shared/proto \
		--python_out=../ai-service/app/api \
		--grpc_python_out=../ai-service/app/api \
		../shared/proto/communication.proto
