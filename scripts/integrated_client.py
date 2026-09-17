"""
依赖：Docker 已启动，compose 已 up；在 ECS 宿主机上执行本脚本且本机有 docker 命令时，
会自动把 TRAINING_DOCKER_IMAGE（默认 csv-training-service:latest）注册到证明服务白名单。

若仅用 compose 构建过训练镜像，请先 tag：
  docker tag confidential-computing-platform-confidential-container:latest csv-training-service:latest
（左侧名称以 docker images 为准。）

跳过自动注册：环境变量 SKIP_REGISTER_TRAINING_IMAGE=1

容器内跑全流程请使用 host 网络，例如：
  docker compose run --rm --network host -e CONTROLLER_URL=http://127.0.0.1:8080 \\
    -e VERIFY_URL=http://127.0.0.1:8081 client python3 scripts/integrated_client.py
"""
#!/usr/bin/python3.8
import requests
import json
import time
import base64
import os
import hashlib
import subprocess
import logging
from gmssl.sm4 import CryptSM4, SM4_ENCRYPT, SM4_DECRYPT
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend

# 导入模块1的客户端类
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from module1.client import ConfidentialComputeClient

_ic_log = logging.getLogger("scripts.integrated_client")


def _flow(msg: str) -> None:
    """与命令行跑脚本一致输出到 stdout，并打 INFO 便于 docker logs / 平台日志采集。"""
    print(msg, flush=True)
    _ic_log.info(msg)


def _inject_key_http_timeout():
    try:
        return float(os.environ.get("INJECT_KEY_TIMEOUT", "120"))
    except ValueError:
        return 120.0


def _training_submit_timeout():
    try:
        return float(os.environ.get("TRAINING_SUBMIT_TIMEOUT", "300"))
    except ValueError:
        return 300.0


def _training_result_timeout():
    try:
        return float(os.environ.get("TRAINING_RESULT_TIMEOUT", "120"))
    except ValueError:
        return 120.0


def _training_status_poll_timeout():
    try:
        return float(os.environ.get("TRAINING_STATUS_POLL_TIMEOUT", "15"))
    except ValueError:
        return 15.0


def _container_api_timeout():
    try:
        return float(os.environ.get("CONTAINER_API_TIMEOUT", "300"))
    except ValueError:
        return 300.0


class IntegratedClient:
    def __init__(self, controller_url="http://localhost:8080",
                 verify_url="http://localhost:8081"):
        self.controller_url = controller_url
        self.verify_url = verify_url
        self.session_info = None
        self.dek = None
        self.key_id = None
        # 最近一次成功远程证明的完整材料（供向导等写入 attestation_report.json）
        self._last_attestation_report = None

    def register_training_image_on_service(self):
        """在宿主机存在 docker CLI 时，将训练镜像 ID 登记到证明服务（无需单独跑 auto_register）。"""
        if os.environ.get("SKIP_REGISTER_TRAINING_IMAGE", "").lower() in ("1", "true", "yes"):
            return True
        image_name = os.environ.get("TRAINING_DOCKER_IMAGE", "csv-training-service:latest")
        try:
            r = subprocess.run(
                ["docker", "image", "inspect", "-f", "{{.Id}}", image_name],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except FileNotFoundError:
            print(
                "ℹ️  未检测到 docker 命令，跳过自动注册白名单；"
                "请确保证明服务中已包含当前训练镜像哈希。"
            )
            return True
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            print(f"⚠️  无法 inspect 镜像 {image_name}，跳过自动注册。")
            print(f"    原因: {err[:300] if err else 'unknown'}")
            print(
                f"    请先执行: docker tag <你的训练镜像> {image_name}\n"
                "    再手工将镜像 sha256 登记到证明服务，否则控制器会拒绝创建容器。"
            )
            return True
        full_hash = (r.stdout or "").strip()
        if not full_hash.startswith("sha256:"):
            full_hash = "sha256:" + full_hash.lstrip("sha256:")
        try:
            resp = requests.post(
                f"{self.verify_url}/api/v1/trusted-images",
                json={"image_hash": full_hash},
                timeout=15,
            )
            data = resp.json() if resp.text else {}
            if resp.status_code == 200 and data.get("code") == 0:
                print(f"✅ 证明白名单已更新（{image_name} -> {full_hash[:22]}...）")
                return True
            print(f"⚠️  白名单接口返回异常: HTTP {resp.status_code} {resp.text[:300]}")
        except requests.RequestException as e:
            print(f"⚠️  请求证明服务失败（可稍后手工登记白名单）: {e}")
        return True

    def create_training_container(self, resources=None, algorithm="xgboost_classifier", min_samples=2000):
        if resources is None:
            resources = {"cpu": 2, "memory": "4096M"}
        print("请求URL:", f"{self.controller_url}/api/v1/containers")
        print("请求数据:", json.dumps({
                "mode": "training",
                "resources": resources,
                "task_data": {
                    "algorithm": algorithm,
                    "min_samples": min_samples
                }
            }))
        resp = requests.post(
            f"{self.controller_url}/api/v1/containers",
            json={
                "mode": "training",
                "resources": resources,
                "task_data": {
                    "algorithm": algorithm,
                    "min_samples": min_samples
                }
            },
            timeout=_container_api_timeout(),
        )
        if resp.status_code != 200:
            raise Exception(f"创建容器失败: {resp.text}")
        result = resp.json()
        if result['code'] != 0:
            raise Exception(f"创建容器失败: {result['message']}")
        container_info = result['data']
        _flow(f"✅ 训练容器创建成功")
        _flow(f"   容器ID: {container_info['container_id']}")
        _flow(f"   证明代理地址: {container_info['attestation_address']}")
        _flow(f"   训练服务地址: {container_info['training_address']}")
        return container_info

    def perform_remote_attestation(self, container_addr):
        _flow(f"🔐 开始远程证明流程...（目标证明代理: {container_addr}，验证服务: {self.verify_url}）")
        self._last_attestation_report = None
        client = ConfidentialComputeClient(
            controller_url=self.controller_url,
            verify_url=self.verify_url
        )
        result = client.attest_container(container_addr)
        evidence = None

        # 处理返回结果（兼容字典和元组）
        if isinstance(result, tuple):
            if len(result) >= 3:
                verify_result, evidence, pubkey = result[:3]
            else:
                raise ValueError(f"Unexpected tuple return from attest_container: {result}")
        elif isinstance(result, dict):
            if not result.get('success'):
                raise Exception(f"远程证明失败: {result.get('error', '未知错误')}")
            verify_result = result['verify_result']
            pubkey = result['public_key']
            evidence = result.get('evidence')
        else:
            raise ValueError(f"Unexpected return type from attest_container: {type(result)}")
        
        # 从 verify_result 中提取验证状态和信息
        if isinstance(verify_result, dict):
            valid = False
            token = None
            session_id = None
            expires_at = None
            reason = None
            
            # 尝试多种可能的路径
            if 'valid' in verify_result:
                valid = verify_result['valid']
                token = verify_result.get('token')
                session_id = verify_result.get('session_id')
                expires_at = verify_result.get('expires_at')
                reason = verify_result.get('reason')
            elif verify_result.get('code') == 0 and 'data' in verify_result:
                data = verify_result['data']
                valid = data.get('valid', False)
                token = data.get('token')
                session_id = data.get('session_id')
                expires_at = data.get('expires_at')
                reason = data.get('reason')
            elif verify_result.get('valid') is not None:
                valid = verify_result['valid']
                token = verify_result.get('token')
                session_id = verify_result.get('session_id')
                expires_at = verify_result.get('expires_at')
                reason = verify_result.get('reason')
            else:
                reason = str(verify_result)
            
            if valid:
                _flow(f"✅ 远程证明通过（ConfidentialComputeClient.attest_container + 验证服务链）")
                self.session_info = {
                    "token": token,
                    "session_id": session_id,
                    "container_addr": container_addr,
                    "expires_at": expires_at
                }
                self._last_attestation_report = {
                    "container_addr": container_addr,
                    "controller_url": self.controller_url,
                    "verify_url": self.verify_url,
                    "verify_result": verify_result,
                    "evidence": evidence,
                    "public_key_pem": pubkey if isinstance(pubkey, str) else None,
                }
                return True, pubkey
            else:
                _flow(f"❌ 远程证明失败: {reason}")
                return False, None
        else:
            raise ValueError(f"Unexpected verify_result type: {type(verify_result)}")

    def generate_dek(self):
        self.dek = os.urandom(16)
        _flow(f"🔑 生成数据加密密钥: {self.dek.hex()}")
        return self.dek

    def encrypt_data_file(self, input_path, output_path):
        with open(input_path, 'rb') as f:
            data = f.read()
        crypt_sm4 = CryptSM4()
        crypt_sm4.set_key(self.dek, SM4_ENCRYPT)
        padding_len = 16 - (len(data) % 16)
        padded_data = data + bytes([padding_len] * padding_len)
        encrypted_data = crypt_sm4.crypt_ecb(padded_data)
        with open(output_path, 'wb') as f:
            f.write(encrypted_data)
        _flow(f"🔐 数据加密完成，保存到: {output_path}")
        return output_path

    def inject_key(self, container_addr, public_key_pem):
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode('utf-8'),
            backend=default_backend()
        )
        encrypted_key = public_key.encrypt(
            self.dek,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        encrypted_key_b64 = base64.b64encode(encrypted_key).decode()
        resp = requests.post(
            f"http://{container_addr}/api/v1/inject-key",
            json={"encrypted_key": encrypted_key_b64},
            timeout=_inject_key_http_timeout(),
        )
        result = resp.json()
        if result['code'] == 0:
            self.key_id = result['data']['key_id']
            _flow(f"✅ 密钥注入成功，key_id: {self.key_id}")
            return self.key_id
        else:
            raise Exception(f"密钥注入失败: {result.get('message')}")

    def submit_training_task(
        self,
        training_endpoint,
        encrypted_data_path,
        algorithm="xgboost",
        params=None,
        data_uri_override=None,
    ):
        if params is None:
            params = {"n_estimators": 50, "max_depth": 3}
        # 训练容器内可读路径：compose 中 client 挂载 ./data:/data，训练容器 ./data:/app/data
        if data_uri_override:
            data_uri = data_uri_override
        else:
            data_uri = f"file://{os.path.abspath(encrypted_data_path)}"
        _flow(f"📊 提交训练任务... endpoint={training_endpoint} algorithm={algorithm}")
        resp = requests.post(
            f"{training_endpoint}",
            params={"algorithm": algorithm, "data_uri": data_uri, "key_id": self.key_id},
            json={"params": params},
            timeout=_training_submit_timeout(),
        )
        if resp.status_code != 200:
            raise Exception(f"提交训练任务失败: {resp.text}")
        result = resp.json()
        task_id = result.get('task_id')
        _flow(f"✅ 训练任务提交成功，task_id: {task_id}")
        return task_id

    def monitor_training_task(self, training_endpoint, task_id, timeout=600):
        url = f"{training_endpoint}/{task_id}/status"
        start_time = time.time()
        poll_to = _training_status_poll_timeout()
        _flow(f"⏳ 监控训练任务 {task_id}... url={url}")
        while time.time() - start_time < timeout:
            try:
                resp = requests.get(url, timeout=poll_to)
                if resp.status_code == 200:
                    status = resp.json()
                    current_status = status.get('status', 'unknown')
                    if current_status == 'completed':
                        _flow(f"✅ 训练任务完成")
                        return True, status
                    elif current_status == 'failed':
                        _flow(f"❌ 训练任务失败: {status.get('error', '未知错误')}")
                        return False, status
                    else:
                        _flow(f"⏳ 任务状态: {current_status}, 等待中...")
                else:
                    _flow(f"⚠️ 查询状态失败: {resp.status_code}")
            except Exception as e:
                _flow(f"⚠️ 查询状态异常: {e}")
            time.sleep(5)
        _flow(f"❌ 训练任务超时")
        return False, None

    def get_training_result(self, training_endpoint, task_id):
        url = f"{training_endpoint}/{task_id}/result"
        resp = requests.get(url, timeout=_training_result_timeout())
        if resp.status_code != 200:
            raise Exception(f"获取训练结果失败: {resp.text}")
        result = resp.json()
        model_hex = result.get('model')
        metadata = result.get('metadata', {})
        if model_hex:
            model_bytes = bytes.fromhex(model_hex)
            crypt_sm4 = CryptSM4()
            crypt_sm4.set_key(self.dek, SM4_DECRYPT)
            decrypted_padded = crypt_sm4.crypt_ecb(model_bytes)
            padding_len = decrypted_padded[-1]
            if 1 <= padding_len <= 16:
                model_plain = decrypted_padded[:-padding_len]
            else:
                model_plain = decrypted_padded
            model_path = f"model_{task_id}.pkl"
            with open(model_path, 'wb') as f:
                f.write(model_plain)
            _flow(f"✅ 模型解密并保存到: {model_path}")
            return model_path
        else:
            _flow(f"❌ 未找到模型数据")
            return None

    def run_full_workflow(self, data_path, algorithm="xgboost_classifier", params=None):
        _flow("=" * 60)
        _flow("开始机密计算训练工作流")
        _flow("=" * 60)
        # 与 docker-compose 一致：密文放在共享 data 卷，训练容器内路径为 /app/data/同名文件
        shared_dir = os.environ.get("CLIENT_DATA_DIR", "/data")
        training_dir = os.environ.get("TRAINING_CONTAINER_DATA_DIR", "/app/data")
        enc_name = "encrypted_train_data.bin"
        encrypted_data_path = os.path.join(shared_dir, enc_name)
        training_data_uri = f"file://{training_dir.rstrip('/')}/{enc_name}"
        use_same_path = os.environ.get("TRAINING_USE_LOCAL_FILE_URI", "").lower() in ("1", "true", "yes")
        try:
            self.register_training_image_on_service()
            container_info = self.create_training_container(algorithm=algorithm)
            time.sleep(10)  

            success, pubkey = self.perform_remote_attestation(container_info['attestation_address'])
            if not success:
                return False

            self.generate_dek()
            os.makedirs(shared_dir, exist_ok=True)
            self.encrypt_data_file(data_path, encrypted_data_path)

            self.inject_key(container_info['attestation_address'], pubkey)

            training_endpoint = f"http://{container_info['training_address']}/v1/tasks"
            uri = f"file://{os.path.abspath(encrypted_data_path)}" if use_same_path else training_data_uri
            task_id = self.submit_training_task(
                training_endpoint,
                encrypted_data_path,
                algorithm,
                params,
                data_uri_override=uri,
            )

            success, status = self.monitor_training_task(training_endpoint, task_id)
            if not success:
                return False

            model_path = self.get_training_result(training_endpoint, task_id)
            if model_path:
                _flow("\n" + "=" * 60)
                _flow("✅ 机密计算训练工作流完成！")
                return True
            else:
                return False
        except Exception as e:
            _flow(f"\n❌ 工作流执行失败: {e}")
            import traceback

            traceback.print_exc()
            _ic_log.exception("工作流异常")
            return False
        finally:
            if os.environ.get("KEEP_ENCRYPTED_TRAIN_BIN", "").lower() not in ("1", "true", "yes"):
                if os.path.exists(encrypted_data_path):
                    try:
                        os.remove(encrypted_data_path)
                    except OSError:
                        pass

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _DATA_DIR = os.path.join(_ROOT, "data")
    # 宿主机从项目根跑时默认用 ./data；容器 cc-client 仍可用卷挂载的 /data
    if "TRAIN_DATA_PATH" not in os.environ:
        _default_train = os.path.join(_DATA_DIR, "train_claims_numeric.csv")
        TRAIN_DATA_PATH = _default_train if os.path.isfile(_default_train) else "/data/train_claims_numeric.csv"
    else:
        TRAIN_DATA_PATH = os.environ["TRAIN_DATA_PATH"]
    if "CLIENT_DATA_DIR" not in os.environ:
        os.environ["CLIENT_DATA_DIR"] = _DATA_DIR if os.path.isdir(_DATA_DIR) else "/data"
    client = IntegratedClient(
        controller_url=os.environ.get("CONTROLLER_URL", "http://localhost:8080"),
        verify_url=os.environ.get("VERIFY_URL", "http://localhost:8081"),
    )
    success = client.run_full_workflow(
        data_path=TRAIN_DATA_PATH,
        algorithm=os.environ.get("TRAIN_ALGORITHM", "xgboost_classifier"),
        params={
            "n_estimators": 50,
            "max_depth": 3,
            "random_state": 42,
            "n_jobs": 1,
        },
    )
    if success:
        print("\n🎉 机密计算训练任务执行成功！")
    else:
        print("\n💥 机密计算训练任务执行失败")
        exit(1)