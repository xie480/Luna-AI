package config

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"io"

	"github.com/zalando/go-keyring"
)

const (
	serviceName = "LunaAI"
	keyName     = "MasterKey"
)

// CryptoService 提供基于 OS Keychain 的 AES-256-GCM 加解密服务
type CryptoService struct {
	masterKey []byte
}

// NewCryptoService 初始化 CryptoService，从 Keychain 获取或生成 Master Key
func NewCryptoService() (*CryptoService, error) {
	keyStr, err := keyring.Get(serviceName, keyName)
	var masterKey []byte

	if err != nil {
		// 如果找不到，生成一个新的 32 字节 (256-bit) 密钥
		masterKey = make([]byte, 32)
		if _, err := io.ReadFull(rand.Reader, masterKey); err != nil {
			return nil, fmt.Errorf("生成 Master Key 失败: %w", err)
		}

		// 将生成的密钥进行 Base64 编码后存入 Keychain
		keyStr = base64.StdEncoding.EncodeToString(masterKey)
		if err := keyring.Set(serviceName, keyName, keyStr); err != nil {
			return nil, fmt.Errorf("保存 Master Key 到 Keychain 失败: %w", err)
		}
	} else {
		// 从 Keychain 读取并解码
		masterKey, err = base64.StdEncoding.DecodeString(keyStr)
		if err != nil {
			return nil, fmt.Errorf("解码 Master Key 失败: %w", err)
		}
		if len(masterKey) != 32 {
			return nil, fmt.Errorf("Master Key 长度不正确，期望 32 字节，实际 %d 字节", len(masterKey))
		}
	}

	return &CryptoService{
		masterKey: masterKey,
	}, nil
}

// Encrypt 使用 Master Key 对明文进行 AES-256-GCM 加密
func (s *CryptoService) Encrypt(plaintext string) (string, error) {
	block, err := aes.NewCipher(s.masterKey)
	if err != nil {
		return "", fmt.Errorf("创建 AES cipher 失败: %w", err)
	}

	aesGCM, err := cipher.NewGCM(block)
	if err != nil {
		return "", fmt.Errorf("创建 GCM 失败: %w", err)
	}

	nonce := make([]byte, aesGCM.NonceSize())
	if _, err = io.ReadFull(rand.Reader, nonce); err != nil {
		return "", fmt.Errorf("生成 nonce 失败: %w", err)
	}

	ciphertext := aesGCM.Seal(nonce, nonce, []byte(plaintext), nil)
	return base64.StdEncoding.EncodeToString(ciphertext), nil
}

// Decrypt 使用 Master Key 对密文进行 AES-256-GCM 解密
func (s *CryptoService) Decrypt(ciphertextBase64 string) (string, error) {
	ciphertext, err := base64.StdEncoding.DecodeString(ciphertextBase64)
	if err != nil {
		return "", fmt.Errorf("解码密文失败: %w", err)
	}

	block, err := aes.NewCipher(s.masterKey)
	if err != nil {
		return "", fmt.Errorf("创建 AES cipher 失败: %w", err)
	}

	aesGCM, err := cipher.NewGCM(block)
	if err != nil {
		return "", fmt.Errorf("创建 GCM 失败: %w", err)
	}

	nonceSize := aesGCM.NonceSize()
	if len(ciphertext) < nonceSize {
		return "", fmt.Errorf("密文长度太短")
	}

	nonce, ciphertext := ciphertext[:nonceSize], ciphertext[nonceSize:]
	plaintext, err := aesGCM.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return "", fmt.Errorf("解密失败: %w", err)
	}

	return string(plaintext), nil
}
