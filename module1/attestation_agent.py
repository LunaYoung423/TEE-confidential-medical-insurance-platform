# import sys, os; print("Python executable:", sys.executable); print("PID:", os.getpid()); print("CONTAINER_IMAGE_HASH from env:", os.getenv("CONTAINER_IMAGE_HASH")); import time; time.sleep(2)
# #!/usr/bin/python3.8
# import subprocess
# import json
# import base64
# import logging
# import os
# import hashlib
# import time
# import tempfile
# from flask import Flask, request, jsonify
# from cryptography.hazmat.primitives.asymmetric import rsa, padding
# from cryptography.hazmat.primitives import serialization, hashes
# from cryptography.hazmat.backends import default_backend
# from gmssl.sm4 import CryptSM4, SM4_ENCRYPT, SM4_DECRYPT

# app = Flask(__name__)
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# class AttestationAgent:
#     def __init__(self):
#         self.private_key = rsa.generate_private_key(
#             public_exponent=65537,
#             key_size=2048,
#             backend=default_backend()
#         )
#         self.public_key = self.private_key.public_key()
#         self.session_keys = {}  # key_id -> {'key': bytes, 'client_id': str, ...}
#         self.attestation_server = os.getenv('ATTESTATION_SERVER', 'http://localhost:8081')
#         self.csv_device = '/dev/csv-guest'
#         self.csv_tool = '/app/csv-attestation.py'
#         self.app_measurement = self._get_actual_image_hash()
#         self.verified_clients = {}

#     def _get_actual_image_hash(self):
#         import time
#         # 尝试多次读取环境变量（最多5次，每次等待1秒）
#         for i in range(5):
#             h = os.getenv('CONTAINER_IMAGE_HASH')
#             if h:
#                 return h
#             time.sleep(1)
#         raise Exception("无法获取容器镜像哈希，请设置环境变量 CONTAINER_IMAGE_HASH")

#     def collect_evidence(self, challenge: str) -> dict:
#         pubkey_pem = self.public_key.public_bytes(
#             encoding=serialization.Encoding.PEM,
#             format=serialization.PublicFormat.SubjectPublicKeyInfo
#         )
#         pubkey_hash = hashlib.sha256(pubkey_pem).hexdigest()

#         # ⭐ 模拟模式
#         if not os.path.exists(self.csv_device):
#             logger.warning("CSV设备不存在，使用模拟证明模式")
#             return {
#                 "type": "csv_simulated",
#                 "challenge": challenge,
#                 "pubkey_hash": pubkey_hash,
#                 "app_measurement": self.app_measurement,
#                 "evidence": base64.b64encode(b"simulated_evidence_data").decode("ascii"),
#                 "timestamp": time.time(),
#                 "service_type": "training",
#             }

#         # ⭐ 真正 CSV 分支（以后再开）
#         report_path = None
#         try:
#             with tempfile.NamedTemporaryFile(delete=False) as tmp:
#                 report_path = tmp.name
#         # TODO: 调用 csv 工具
#         finally:
#             if report_path and os.path.exists(report_path):
#                 os.remove(report_path)


#     def inject_key(self, encrypted_key_b64: str, client_id: str = None) -> dict:
#         try:
#             encrypted_key = base64.b64decode(encrypted_key_b64)
#             session_key = self.private_key.decrypt(
#                 encrypted_key,
#                 padding.OAEP(
#                     mgf=padding.MGF1(algorithm=hashes.SHA256()),
#                     algorithm=hashes.SHA256(),
#                     label=None
#                 )
#             )
#             key_id = hashlib.sha256(session_key).hexdigest()[:16]
#             if not client_id:
#                 client_id = hashlib.sha256(os.urandom(32)).hexdigest()[:16]

#             self.session_keys[key_id] = {
#                 "key": session_key,
#                 "client_id": client_id,
#                 "created_at": time.time(),
#                 "last_used": time.time()
#             }
#             self.verified_clients[client_id] = {
#                 "key_id": key_id,
#                 "verified_at": time.time(),
#                 "status": "active"
#             }
#             logger.info(f"密钥注入成功: {key_id}, 客户端: {client_id}")
#             return {
#                 "success": True,
#                 "key_id": key_id,
#                 "client_id": client_id,
#                 "expires_at": time.time() + 3600
#             }
#         except Exception as e:
#             logger.error(f"密钥注入失败: {e}")
#             return {"success": False, "error": str(e)}

#     def get_key(self, key_id: str):
#         key_info = self.session_keys.get(key_id)
#         if not key_info:
#             return None
#         key_info['last_used'] = time.time()
#         return key_info['key']

#     def verify_client(self, client_id: str, signature: str = None) -> bool:
#         client_info = self.verified_clients.get(client_id)
#         if not client_info:
#             return False
#         if time.time() - client_info['verified_at'] > 3600:
#             del self.verified_clients[client_id]
#             return False
#         client_info['last_used'] = time.time()
#         return True

#     def decrypt_data(self, encrypted_data_b64: str, key_id: str) -> bytes:
#         key = self.get_key(key_id)
#         if not key:
#             raise Exception(f"密钥不存在: {key_id}")
#         encrypted_data = base64.b64decode(encrypted_data_b64)
#         crypt_sm4 = CryptSM4()
#         crypt_sm4.set_key(key, SM4_DECRYPT)
#         decrypted_padded = crypt_sm4.crypt_ecb(encrypted_data)
#         padding_len = decrypted_padded[-1]
#         if 1 <= padding_len <= 16:
#             decrypted_data = decrypted_padded[:-padding_len]
#         else:
#             decrypted_data = decrypted_padded
#         return decrypted_data

#     def encrypt_data(self, plain_data_b64: str, key_id: str) -> bytes:
#         key = self.get_key(key_id)
#         if not key:
#             raise Exception(f"密钥不存在: {key_id}")
#         plain_data = base64.b64decode(plain_data_b64)
#         crypt_sm4 = CryptSM4()
#         crypt_sm4.set_key(key, SM4_ENCRYPT)
#         padding_len = 16 - (len(plain_data) % 16)
#         padded_data = plain_data + bytes([padding_len] * padding_len)
#         encrypted_data = crypt_sm4.crypt_ecb(padded_data)
#         return encrypted_data

# agent = AttestationAgent()

# @app.route('/api/v1/attest', methods=['POST'])
# def attest():
#     data = request.json
#     challenge = data.get('challenge', str(time.time()))
#     client_id = data.get('client_id')
#     if client_id and not agent.verify_client(client_id):
#         return jsonify({"code": 403, "message": "客户端验证失败"}), 403

#     try:
#         evidence = agent.collect_evidence(challenge)
#     except Exception as e:
#         return jsonify({"code": 500, "message": f"证据采集失败: {str(e)}"}), 500

#     pubkey_pem = agent.public_key.public_bytes(
#         encoding=serialization.Encoding.PEM,
#         format=serialization.PublicFormat.SubjectPublicKeyInfo
#     ).decode('utf-8')

#     return jsonify({
#         "code": 0,
#         "data": {
#             "evidence": evidence,
#             "public_key": pubkey_pem,
#             "timestamp": time.time()
#         }
#     })

# @app.route('/api/v1/inject-key', methods=['POST'])
# def inject_key():
#     data = request.json
#     encrypted_key = data.get('encrypted_key')
#     client_id = data.get('client_id')
#     if not encrypted_key:
#         return jsonify({"code": 400, "message": "缺少encrypted_key"}), 400
#     result = agent.inject_key(encrypted_key, client_id)
#     if result.get('success'):
#         return jsonify({
#             "code": 0,
#             "data": {
#                 "key_id": result['key_id'],
#                 "client_id": result['client_id'],
#                 "expires_at": result['expires_at']
#             }
#         })
#     else:
#         return jsonify({"code": 500, "message": f"密钥注入失败: {result.get('error')}"}), 500

# @app.route('/api/v1/keys/<key_id>', methods=['GET'])
# def get_key(key_id):
#     key = agent.get_key(key_id)
#     if key is None:
#         return jsonify({"code": 404, "message": "密钥不存在"}), 404
#     return jsonify({"code": 0, "data": {"key": base64.b64encode(key).decode('ascii')}})

# @app.route('/api/v1/decrypt', methods=['POST'])
# def decrypt():
#     """解密数据：接收base64编码的密文和key_id，返回base64编码的明文"""
#     data = request.json
#     encrypted_data_b64 = data.get('encrypted_data')
#     key_id = data.get('key_id')
#     if not encrypted_data_b64 or not key_id:
#         return jsonify({"code": 400, "message": "缺少encrypted_data或key_id"}), 400
#     try:
#         plain_data = agent.decrypt_data(encrypted_data_b64, key_id)
#         return jsonify({
#             "code": 0,
#             "data": {
#                 "plain_data": base64.b64encode(plain_data).decode('ascii')
#             }
#         })
#     except Exception as e:
#         logger.error(f"解密失败: {e}")
#         return jsonify({"code": 500, "message": str(e)}), 500

# @app.route('/api/v1/encrypt', methods=['POST'])
# def encrypt():
#     """加密数据：接收base64编码的明文和key_id，返回base64编码的密文"""
#     data = request.json
#     plain_data_b64 = data.get('plain_data')
#     key_id = data.get('key_id')
#     if not plain_data_b64 or not key_id:
#         return jsonify({"code": 400, "message": "缺少plain_data或key_id"}), 400
#     try:
#         encrypted_data = agent.encrypt_data(plain_data_b64, key_id)
#         return jsonify({
#             "code": 0,
#             "data": {
#                 "encrypted_data": base64.b64encode(encrypted_data).decode('ascii')
#             }
#         })
#     except Exception as e:
#         logger.error(f"加密失败: {e}")
#         return jsonify({"code": 500, "message": str(e)}), 500

# @app.route('/api/v1/health', methods=['GET'])
# def health():
#     training_service_healthy = False
#     try:
#         import requests
#         resp = requests.get('http://localhost:8000/', timeout=2)
#         training_service_healthy = resp.status_code == 200
#     except:
#         pass
#     return jsonify({
#         "status": "ok",
#         "csv_device": os.path.exists(agent.csv_device),
#         "training_service": "running" if training_service_healthy else "stopped",
#         "verified_clients": len(agent.verified_clients),
#         "session_keys": len(agent.session_keys)
#     })

# if __name__ == '__main__':
#     app.run(host='0.0.0.0', port=8006, debug=False)

#!/usr/bin/python3.8
import subprocess
import json
import base64
import logging
import os
import hashlib
import time
import tempfile
from flask import Flask, request, jsonify
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
from gmssl.sm4 import CryptSM4, SM4_ENCRYPT, SM4_DECRYPT

from module3.audit.middleware import AuditMiddleware

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
AuditMiddleware(
    app,
    service_name=os.environ.get("AUDIT_SERVICE_NAME_AGENT", "attestation-agent"),
)

class AttestationAgent:
    def __init__(self):
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        self.public_key = self.private_key.public_key()
        self.session_keys = {}  # key_id -> {'key': bytes, 'client_id': str, ...}
        self.attestation_server = os.getenv('ATTESTATION_SERVER', 'http://localhost:8081')
        # 允许通过环境变量指定实际 CSV 设备节点路径（便于适配不同厂商/实例命名）
        self.csv_device = os.getenv('CSV_DEVICE_PATH', '/dev/csv-guest')
        self.csv_tool = '/app/csv-attestation.py'
        self.app_measurement = self._get_actual_image_hash()
        self.verified_clients = {}

    def _get_actual_image_hash(self):
        import time
        # 尝试多次读取环境变量（最多5次，每次等待1秒）
        for i in range(5):
            h = os.getenv('CONTAINER_IMAGE_HASH')
            if h:
                return h[7:] if h.startswith("sha256:") else h
            time.sleep(1)
        raise Exception("无法获取容器镜像哈希，请设置环境变量 CONTAINER_IMAGE_HASH")

    def collect_evidence(self, challenge: str) -> dict:
        pubkey_pem = self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        pubkey_hash = hashlib.sha256(pubkey_pem).hexdigest()

        userdata = json.dumps({
            "challenge": challenge,
            "pubkey_hash": pubkey_hash,
            "app_measurement": self.app_measurement,
            "timestamp": time.time(),
            "service_type": "training"
        })

        # 默认要求真实 CSV：无设备则失败。仅当 ALLOW_CSV_SIMULATION=1/true/yes 时允许模拟（本地调试）
        if not os.path.exists(self.csv_device):
            if os.environ.get("ALLOW_CSV_SIMULATION", "").lower() in ("1", "true", "yes"):
                logger.warning("CSV设备不存在，使用模拟证明模式（ALLOW_CSV_SIMULATION 已开启）")
                return {
                    "type": "csv_simulated",
                    "challenge": challenge,
                    "pubkey_hash": pubkey_hash,
                    "app_measurement": self.app_measurement,
                    "evidence": base64.b64encode(b"simulated_evidence_data").decode('ascii'),
                    "timestamp": time.time(),
                    "service_type": "training"
                }
            raise RuntimeError(
                f"未找到 CSV 设备 {self.csv_device}，无法生成硬件证明。"
                "请在阿里云海光 CSV 实例（g7h + 机密虚拟机 + Alibaba Cloud Linux 3 UEFI）上运行，"
                "并执行: sudo modprobe csv-guest && ls -l /dev/csv-guest。"
                "若仅在开发机调试，可设置环境变量 ALLOW_CSV_SIMULATION=1。"
            )

        # 真实 CSV 证明流程
        report_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                report_path = tmp.name

            result = subprocess.run(
                ["python3", self.csv_tool, "generate", "-r", report_path, "-u", userdata],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                logger.error(f"生成证据失败: {result.stderr}")
                raise Exception(f"CSV证据生成失败: {result.stderr}")

            with open(report_path, 'rb') as f:
                evidence_raw = f.read()

            evidence = {
                "type": "csv",
                "challenge": challenge,
                "pubkey_hash": pubkey_hash,
                "app_measurement": self.app_measurement,
                "evidence": base64.b64encode(evidence_raw).decode('ascii'),
                "timestamp": time.time(),
                "service_type": "training"
            }
            logger.info("硬件证据生成成功")
            return evidence
        except Exception as e:
            logger.error(f"证据生成异常: {e}")
            raise
        finally:
            if report_path and os.path.exists(report_path):
                os.remove(report_path)

    def inject_key(self, encrypted_key_b64: str, client_id: str = None) -> dict:
        try:
            encrypted_key = base64.b64decode(encrypted_key_b64)
            session_key = self.private_key.decrypt(
                encrypted_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            key_id = hashlib.sha256(session_key).hexdigest()[:16]
            if not client_id:
                client_id = hashlib.sha256(os.urandom(32)).hexdigest()[:16]

            self.session_keys[key_id] = {
                "key": session_key,
                "client_id": client_id,
                "created_at": time.time(),
                "last_used": time.time()
            }
            self.verified_clients[client_id] = {
                "key_id": key_id,
                "verified_at": time.time(),
                "status": "active"
            }
            logger.info(f"密钥注入成功: {key_id}, 客户端: {client_id}")
            return {
                "success": True,
                "key_id": key_id,
                "client_id": client_id,
                "expires_at": time.time() + 3600
            }
        except Exception as e:
            logger.error(f"密钥注入失败: {e}")
            return {"success": False, "error": str(e)}

    def get_key(self, key_id: str):
        key_info = self.session_keys.get(key_id)
        if not key_info:
            return None
        key_info['last_used'] = time.time()
        return key_info['key']

    def verify_client(self, client_id: str, signature: str = None) -> bool:
        client_info = self.verified_clients.get(client_id)
        if not client_info:
            return False
        if time.time() - client_info['verified_at'] > 3600:
            del self.verified_clients[client_id]
            return False
        client_info['last_used'] = time.time()
        return True

    def decrypt_data(self, encrypted_data_b64: str, key_id: str) -> bytes:
        key = self.get_key(key_id)
        if not key:
            raise Exception(f"密钥不存在: {key_id}")
        encrypted_data = base64.b64decode(encrypted_data_b64)
        crypt_sm4 = CryptSM4()
        crypt_sm4.set_key(key, SM4_DECRYPT)
        decrypted_padded = crypt_sm4.crypt_ecb(encrypted_data)
        padding_len = decrypted_padded[-1]
        if 1 <= padding_len <= 16:
            decrypted_data = decrypted_padded[:-padding_len]
        else:
            decrypted_data = decrypted_padded
        return decrypted_data

    def encrypt_data(self, plain_data_b64: str, key_id: str) -> bytes:
        key = self.get_key(key_id)
        if not key:
            raise Exception(f"密钥不存在: {key_id}")
        plain_data = base64.b64decode(plain_data_b64)
        crypt_sm4 = CryptSM4()
        crypt_sm4.set_key(key, SM4_ENCRYPT)
        padding_len = 16 - (len(plain_data) % 16)
        padded_data = plain_data + bytes([padding_len] * padding_len)
        encrypted_data = crypt_sm4.crypt_ecb(padded_data)
        return encrypted_data

agent = AttestationAgent()

@app.route('/api/v1/attest', methods=['POST'])
def attest():
    data = request.json
    challenge = data.get('challenge', str(time.time()))
    client_id = data.get('client_id')
    if client_id and not agent.verify_client(client_id):
        return jsonify({"code": 403, "message": "客户端验证失败"}), 403

    try:
        evidence = agent.collect_evidence(challenge)
    except Exception as e:
        return jsonify({"code": 500, "message": f"证据采集失败: {str(e)}"}), 500

    pubkey_pem = agent.public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')

    return jsonify({
        "code": 0,
        "data": {
            "evidence": evidence,
            "public_key": pubkey_pem,
            "timestamp": time.time()
        }
    })

@app.route('/api/v1/inject-key', methods=['POST'])
def inject_key():
    data = request.json
    encrypted_key = data.get('encrypted_key')
    client_id = data.get('client_id')
    if not encrypted_key:
        return jsonify({"code": 400, "message": "缺少encrypted_key"}), 400
    result = agent.inject_key(encrypted_key, client_id)
    if result.get('success'):
        return jsonify({
            "code": 0,
            "data": {
                "key_id": result['key_id'],
                "client_id": result['client_id'],
                "expires_at": result['expires_at']
            }
        })
    else:
        return jsonify({"code": 500, "message": f"密钥注入失败: {result.get('error')}"}), 500

@app.route('/api/v1/keys/<key_id>', methods=['GET'])
def get_key(key_id):
    key = agent.get_key(key_id)
    if key is None:
        return jsonify({"code": 404, "message": "密钥不存在"}), 404
    return jsonify({"code": 0, "data": {"key": base64.b64encode(key).decode('ascii')}})

@app.route('/api/v1/decrypt', methods=['POST'])
def decrypt():
    """解密数据：接收base64编码的密文和key_id，返回base64编码的明文"""
    data = request.json
    encrypted_data_b64 = data.get('encrypted_data')
    key_id = data.get('key_id')
    if not encrypted_data_b64 or not key_id:
        return jsonify({"code": 400, "message": "缺少encrypted_data或key_id"}), 400
    try:
        plain_data = agent.decrypt_data(encrypted_data_b64, key_id)
        return jsonify({
            "code": 0,
            "data": {
                "plain_data": base64.b64encode(plain_data).decode('ascii')
            }
        })
    except Exception as e:
        logger.error(f"解密失败: {e}")
        return jsonify({"code": 500, "message": str(e)}), 500

@app.route('/api/v1/encrypt', methods=['POST'])
def encrypt():
    """加密数据：接收base64编码的明文和key_id，返回base64编码的密文"""
    data = request.json
    plain_data_b64 = data.get('plain_data')
    key_id = data.get('key_id')
    if not plain_data_b64 or not key_id:
        return jsonify({"code": 400, "message": "缺少plain_data或key_id"}), 400
    try:
        encrypted_data = agent.encrypt_data(plain_data_b64, key_id)
        return jsonify({
            "code": 0,
            "data": {
                "encrypted_data": base64.b64encode(encrypted_data).decode('ascii')
            }
        })
    except Exception as e:
        logger.error(f"加密失败: {e}")
        return jsonify({"code": 500, "message": str(e)}), 500

@app.route('/api/v1/health', methods=['GET'])
def health():
    training_service_healthy = False
    try:
        import requests
        resp = requests.get('http://localhost:8000/', timeout=2)
        training_service_healthy = resp.status_code == 200
    except:
        pass
    return jsonify({
        "status": "ok",
        "csv_device": os.path.exists(agent.csv_device),
        "training_service": "running" if training_service_healthy else "stopped",
        "verified_clients": len(agent.verified_clients),
        "session_keys": len(agent.session_keys)
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8006, debug=False)