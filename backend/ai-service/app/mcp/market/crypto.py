"""
MCP 鉴权配置加密器。

做什么：使用 AES-256-GCM 加密远程 MCP 的鉴权配置（API Key/Token），
        密文和盐分开存储，防止数据库泄露导致凭证暴露。
为什么这样做：agent.md 要求敏感信息不落明文，
            结合 Phase 3 的密钥管理体系提供加密基础设施。
"""

import os
import json
from typing import Any
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.logger import logger


class MCPAuthCrypto:
    def __init__(self, master_key: bytes | None = None):
        """
        初始化加密器。
        master_key 应为 32 字节。如果不提供，尝试从环境变量 LUNA_MASTER_KEY 读取，
        如果没有配置，则回退到一个默认的（仅用于开发测试，生产环境不推荐）。
        """
        if master_key:
            self.key = master_key
        else:
            env_key = os.environ.get("LUNA_MASTER_KEY")
            if env_key:
                self.key = env_key.encode('utf-8')[:32].ljust(32, b'\0')
            else:
                logger.warning("未配置 LUNA_MASTER_KEY，将使用默认密钥加密 MCP 凭证，生产环境请勿使用此配置")
                self.key = b"default_luna_master_key_for_test".ljust(32, b'\0')
                
        self.aesgCM = AESGCM(self.key)

    def encrypt(self, auth_config: dict[str, Any]) -> tuple[str, str]:
        """加密鉴权配置，返回 (密文(hex), 盐/nonce(hex))。"""
        if not auth_config:
            return "", ""
            
        data = json.dumps(auth_config).encode('utf-8')
        nonce = os.urandom(12)
        ct = self.aesgCM.encrypt(nonce, data, None)
        return ct.hex(), nonce.hex()

    def decrypt(self, ciphertext: str, salt: str) -> dict[str, Any]:
        """解密鉴权配置。"""
        if not ciphertext or not salt:
            return {}
            
        try:
            ct = bytes.fromhex(ciphertext)
            nonce = bytes.fromhex(salt)
            data = self.aesgCM.decrypt(nonce, ct, None)
            return json.loads(data.decode('utf-8'))
        except Exception as e:
            logger.error(f"解密 MCP 鉴权配置失败: {e}")
            return {}
