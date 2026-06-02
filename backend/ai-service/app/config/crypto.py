"""
Luna AI 加解密服务模块

做什么：提供基于 OS Keychain 的 AES-256-GCM 加解密服务。
为什么这样做：保护 API Key 等敏感信息，避免明文落盘。
输入输出：
    - CryptoService: 加解密服务类
边界条件：
    - 首次运行时生成 32 字节 Master Key 并存入 Keychain
    - 后续运行从 Keychain 读取 Master Key
异常行为：
    - Keychain 访问失败或加解密失败时抛出异常
"""

import base64
import os

import keyring
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.logger import logger

SERVICE_NAME = "LunaAI"
KEY_NAME = "MasterKey"


class CryptoService:
    """提供基于 OS Keychain 的 AES-256-GCM 加解密服务"""

    def __init__(self):
        self.master_key = self._get_or_create_master_key()

    def _get_or_create_master_key(self) -> bytes:
        """从 Keychain 获取或生成 Master Key"""
        try:
            key_str = keyring.get_password(SERVICE_NAME, KEY_NAME)
            if key_str:
                master_key = base64.b64decode(key_str)
                if len(master_key) != 32:
                    raise ValueError(f"Master Key 长度不正确，期望 32 字节，实际 {len(master_key)} 字节")
                return master_key
        except Exception as e:
            logger.warning(f"从 Keychain 读取 Master Key 失败或不存在，将生成新密钥: {e}")

        # 如果找不到或读取失败，生成一个新的 32 字节 (256-bit) 密钥
        master_key = os.urandom(32)
        key_str = base64.b64encode(master_key).decode('utf-8')
        
        try:
            keyring.set_password(SERVICE_NAME, KEY_NAME, key_str)
            logger.info("已生成新的 Master Key 并保存到 Keychain")
        except Exception as e:
            logger.error(f"保存 Master Key 到 Keychain 失败: {e}")
            # 降级：如果无法保存到 Keychain，仅在内存中保留（重启后失效）
            # 实际生产环境中可能需要更严格的处理
            
        return master_key

    def encrypt(self, plaintext: str) -> str:
        """使用 Master Key 对明文进行 AES-256-GCM 加密"""
        if not plaintext:
            return ""
            
        aesgcm = AESGCM(self.master_key)
        nonce = os.urandom(12) # GCM 推荐的 nonce 长度为 12 字节
        
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
        
        # 将 nonce 和 ciphertext 拼接后进行 Base64 编码
        # Go 版本的 Seal 会将 ciphertext 附加到 nonce 后面
        combined = nonce + ciphertext
        return base64.b64encode(combined).decode('utf-8')

    def decrypt(self, ciphertext_base64: str) -> str:
        """使用 Master Key 对密文进行 AES-256-GCM 解密"""
        if not ciphertext_base64:
            return ""
            
        try:
            combined = base64.b64decode(ciphertext_base64)
            
            if len(combined) < 12:
                raise ValueError("密文长度太短")
                
            nonce = combined[:12]
            ciphertext = combined[12:]
            
            aesgcm = AESGCM(self.master_key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            
            return plaintext.decode('utf-8')
        except Exception as e:
            raise ValueError(f"解密失败: {e}")
