"""
第六阶段（Layer 6）综合测试

做什么：验证 Go backend/runtime/cmd/main.go 的 Python 端口
     与原始 Go 实现在行为、逻辑和边界条件上 100% 一致。

覆盖范围：
    - main.py: FastAPI 应用入口、生命周期管理（Lifespan）、依赖注入装配

Go 原版参考文件：
    - backend/runtime/cmd/main.go
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.main import lifespan


class TestMainLifespan:
    """验证 main.py 中的 lifespan 生命周期管理"""

    @pytest.mark.asyncio
    @patch("app.main.RedisClient")
    @patch("app.main.PostgresClient")
    @patch("app.main.CryptoService")
    @patch("app.main.PromptPGRepo")
    @patch("app.main.PromptManager")
    @patch("app.main.ChatHistoryRedisRepo")
    @patch("app.main.ChatHistoryPGRepo")
    @patch("app.main.LongTermMemoryPGRepo")
    @patch("app.main.QdrantClientWrapper")
    @patch("app.main.LongTermMemoryQdrantRepo")
    @patch("app.main.MemoryManager")
    @patch("app.main.ConfigPresetPGRepo")
    @patch("app.main.WSServer")
    @patch("app.main.load_embedding_model")
    @patch("app.main.load_rerank_model")
    @patch("app.main.init_worker")
    @patch("app.main.get_worker")
    async def test_lifespan_startup_and_shutdown(
        self,
        mock_get_worker,
        mock_init_worker,
        mock_load_rerank_model,
        mock_load_embedding_model,
        mock_ws_server,
        mock_config_preset_pg_repo,
        mock_memory_manager,
        mock_long_term_memory_qdrant_repo,
        mock_qdrant_client_wrapper,
        mock_long_term_memory_pg_repo,
        mock_chat_history_pg_repo,
        mock_chat_history_redis_repo,
        mock_prompt_manager,
        mock_prompt_pg_repo,
        mock_crypto_service,
        mock_postgres_client,
        mock_redis_client,
    ):
        """验证启动和关闭流程"""
        app = FastAPI()
        
        # 模拟依赖
        mock_pg_instance = MagicMock()
        mock_pg_instance.engine.begin.return_value.__aenter__.return_value.run_sync = AsyncMock()
        mock_pg_instance.close = AsyncMock()
        mock_postgres_client.return_value = mock_pg_instance
        
        mock_worker = MagicMock()
        mock_worker.start = AsyncMock()
        mock_worker.stop = AsyncMock()
        mock_get_worker.return_value = mock_worker
        
        mock_memory_mgr_instance = MagicMock()
        mock_memory_mgr_instance.init = AsyncMock()
        mock_memory_manager.return_value = mock_memory_mgr_instance
        
        mock_load_embedding_model.return_value = "embedding_model"
        mock_load_rerank_model.return_value = "rerank_model"
        
        mock_redis_client.return_value.close = AsyncMock()
        
        with patch("app.telemetry.metrics.start_metrics_collector", new_callable=AsyncMock) as mock_start_metrics, \
             patch("app.telemetry.metrics.stop_metrics_collector", new_callable=AsyncMock) as mock_stop_metrics, \
             patch("app.telemetry.metrics.init_metrics") as mock_init_metrics:
            
            async with lifespan(app):
                # 验证启动流程
                mock_redis_client.assert_called_once()
                mock_postgres_client.assert_called_once()
                mock_init_worker.assert_called_once_with(mock_pg_instance)
                mock_worker.start.assert_called_once()
                mock_crypto_service.assert_called_once()
                mock_prompt_pg_repo.assert_called_once()
                mock_prompt_manager.assert_called_once()
                mock_chat_history_redis_repo.assert_called_once()
                mock_chat_history_pg_repo.assert_called_once()
                mock_long_term_memory_pg_repo.assert_called_once()
                mock_qdrant_client_wrapper.assert_called_once()
                mock_long_term_memory_qdrant_repo.assert_called_once()
                mock_memory_manager.assert_called_once()
                mock_memory_mgr_instance.init.assert_called_once()
                
                # 验证依赖注入
                assert app.state.pg_client == mock_pg_instance
                assert app.state.redis_client == mock_redis_client.return_value
                assert app.state.crypto_svc == mock_crypto_service.return_value
                assert app.state.prompt_manager == mock_prompt_manager.return_value
                assert app.state.memory_manager == mock_memory_mgr_instance
                assert app.state.config_preset_repo == mock_config_preset_pg_repo.return_value
                
                # 验证模型加载
                mock_load_embedding_model.assert_called_once()
                mock_load_rerank_model.assert_called_once()
                
                # 验证 metrics
                mock_init_metrics.assert_called_once()
                mock_start_metrics.assert_called_once()
                
            # 验证关闭流程
            mock_stop_metrics.assert_called_once()
            mock_worker.stop.assert_called_once()
            mock_pg_instance.close.assert_called_once()
            mock_redis_client.return_value.close.assert_called_once()
