import os
import base64
import requests
from urllib.parse import urlparse

class CryptoInterface:
    def __init__(self, attestation_agent_url="http://localhost:8006"):
        self.attestation_agent_url = attestation_agent_url

    def _call_decrypt(self, encrypted_data: bytes, key_id: str) -> bytes:
        """调用证明代理的解密接口"""
        encrypted_b64 = base64.b64encode(encrypted_data).decode('ascii')
        resp = requests.post(
            f"{self.attestation_agent_url}/api/v1/decrypt",
            json={"encrypted_data": encrypted_b64, "key_id": key_id},
            timeout=30
        )
        if resp.status_code != 200:
            raise Exception(f"解密API调用失败: {resp.text}")
        data = resp.json()
        if data['code'] != 0:
            raise Exception(f"解密失败: {data.get('message')}")
        plain_b64 = data['data']['plain_data']
        return base64.b64decode(plain_b64)

    def _call_encrypt(self, plain_data: bytes, key_id: str) -> bytes:
        """调用证明代理的加密接口"""
        plain_b64 = base64.b64encode(plain_data).decode('ascii')
        resp = requests.post(
            f"{self.attestation_agent_url}/api/v1/encrypt",
            json={"plain_data": plain_b64, "key_id": key_id},
            timeout=30
        )
        if resp.status_code != 200:
            raise Exception(f"加密API调用失败: {resp.text}")
        data = resp.json()
        if data['code'] != 0:
            raise Exception(f"加密失败: {data.get('message')}")
        encrypted_b64 = data['data']['encrypted_data']
        return base64.b64decode(encrypted_b64)

    def decrypt_data(self, encrypted_uri: str, key_id: str) -> bytes:
        """从文件读取加密数据，调用解密API，返回明文"""
        parsed = urlparse(encrypted_uri)
        path = parsed.path
        if os.name == 'nt' and path.startswith('/') and len(path) > 2 and path[2] == ':':
            path = path[1:]
        with open(path, 'rb') as f:
            encrypted_data = f.read()
        return self._call_decrypt(encrypted_data, key_id)

    def encrypt_model(self, model_bytes: bytes, key_id: str) -> (bytes, dict):
        """调用加密API加密模型，返回密文和元信息"""
        encrypted_model = self._call_encrypt(model_bytes, key_id)
        metadata = {
            "algorithm": "SM4-ECB (via attestation agent)",
            "key_id": key_id,
            "padding": "PKCS7"
        }
        return encrypted_model, metadata

    def cleanup_task(self, task_id: str):
        pass