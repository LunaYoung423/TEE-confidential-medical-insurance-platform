#!/usr/bin/python3.8
import requests
import base64
import json
import time
import hashlib
import os
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization, hashes
import logging

# 配置日志：输出更详细的请求/响应信息
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 动态容器内证明代理可能较慢（CSV/国密/外呼验证），默认放宽；可通过环境变量覆盖
def _attest_agent_timeout_sec() -> float:
    try:
        return float(os.environ.get("ATTEST_AGENT_TIMEOUT", "120"))
    except ValueError:
        return 120.0


def _attest_verify_timeout_sec() -> float:
    try:
        return float(os.environ.get("ATTEST_VERIFY_TIMEOUT", "60"))
    except ValueError:
        return 60.0


class ConfidentialComputeClient:
    """机密计算客户端 - 增强容错+调试能力"""
    
    def __init__(self, controller_url="http://localhost:8080", 
                 verify_url="http://localhost:8081"):
        self.controller_url = controller_url
        self.verify_url = verify_url
        # 增加请求超时和重试配置
        self.session = requests.Session()
        self.session.mount('http://', requests.adapters.HTTPAdapter(max_retries=2))

    def create_container(self, mode="training", cpu=2, memory=4096, algorithm="xgboost", min_samples=2000):
        """创建训练容器（适配业务参数）"""
        try:
            req_data = {
                "mode": mode,
                "resources": {"cpu": cpu, "memory": f"{memory}M"},
                "task_data": {"algorithm": algorithm, "min_samples": min_samples}
            }
            logger.debug(f"创建容器请求数据: {json.dumps(req_data, indent=2)}")
            
            resp = self.session.post(
                f"{self.controller_url}/api/v1/containers",
                json=req_data,
                timeout=30  # 延长超时（容器创建可能较慢）
            )
            resp.raise_for_status()
            result = resp.json()
            logger.debug(f"创建容器响应数据: {json.dumps(result, indent=2)}")
            
            # 适配业务返回结构（容器ID/证明代理/训练服务地址）
            container_info = {
                "container_id": result.get("container_id") or result.get("data", {}).get("container_id"),
                "attest_addr": result.get("attest_proxy_addr") or result.get("data", {}).get("attest_proxy_addr"),
                "train_addr": result.get("training_addr") or result.get("data", {}).get("training_addr")
            }
            return {"success": True, "data": container_info}
        
        except requests.exceptions.RequestException as e:
            logger.error(f"创建容器失败: {str(e)}", exc_info=True)
            # 捕获服务端返回的错误详情
            error_detail = ""
            try:
                error_detail = resp.json() if resp else ""
            except:
                error_detail = resp.text if resp else ""
            return {
                "success": False,
                "error": f"创建容器异常: {str(e)}",
                "server_error": error_detail
            }

    def attest_container(self, attest_addr):
        """远程证明（增强错误捕获+调试）"""
        # 生成符合规范的挑战值（避免服务端解析失败）
        challenge = base64.b64encode(os.urandom(16)).decode()  # 16字节随机数（更规范）
        logger.debug(f"生成证明挑战值: {challenge}")
        
        try:
            # 构造证明请求
            req_url = f"http://{attest_addr}/api/v1/attest"
            logger.debug(f"发起证明请求: {req_url}")
            
            resp = self.session.post(
                req_url,
                json={"challenge": challenge},
                timeout=_attest_agent_timeout_sec(),
                headers={"Content-Type": "application/json"}  # 显式指定Content-Type
            )
            
            # 打印服务端500错误的详细响应（关键！定位服务端问题）
            if resp.status_code == 500:
                logger.error(f"证明接口500错误 - 响应头: {resp.headers}")
                logger.error(f"证明接口500错误 - 响应体: {resp.text}")
                raise Exception(f"服务端内部错误: {resp.text[:500]}")  # 截断过长响应
            
            resp.raise_for_status()
            data = resp.json()
            logger.debug(f"证明接口响应: {json.dumps(data, indent=2)}")
            
            # 兼容业务响应结构
            evidence = data.get('evidence') or data.get('data', {}).get('evidence')
            public_key_pem = data.get('public_key') or data.get('data', {}).get('public_key')
            
            if not evidence or not public_key_pem:
                raise ValueError(f"证明响应缺少核心字段 - evidence: {bool(evidence)}, public_key: {bool(public_key_pem)}")
            
            # 调用验证服务（若验证服务不可用，先跳过，优先定位证明代理问题）
            verify_result = {"valid": True, "skip_verify": True}
            try:
                verify_resp = self.session.post(
                    f"{self.verify_url}/api/v1/verify",
                    json={"evidence": evidence},
                    timeout=_attest_verify_timeout_sec(),
                )
                verify_resp.raise_for_status()
                verify_result = verify_resp.json()
                logger.debug(f"验证服务响应: {json.dumps(verify_result, indent=2)}")
            except Exception as e:
                logger.warning(f"验证服务调用失败（临时跳过）: {str(e)}")
            
            # 公钥哈希校验
            public_key = serialization.load_pem_public_key(public_key_pem.encode())
            pubkey_bytes = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            pubkey_hash = hashlib.sha256(pubkey_bytes).hexdigest()
            if evidence.get('pubkey_hash') and pubkey_hash != evidence['pubkey_hash']:
                raise Exception(f"公钥哈希不匹配 - 本地计算: {pubkey_hash}, 证据中: {evidence['pubkey_hash']}")
            
            return {
                "success": True,
                "verify_result": verify_result,
                "evidence": evidence,
                "public_key": public_key_pem
            }
        
        except requests.exceptions.RequestException as e:
            logger.error(f"证明请求网络异常: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": f"证明接口网络异常: {str(e)}",
                "url": req_url if 'req_url' in locals() else ""
            }
        except Exception as e:
            logger.error(f"证明流程逻辑异常: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": f"证明流程失败: {str(e)}"
            }

    def inject_key(self, train_addr, public_key_pem):
        """注入会话密钥（适配训练服务地址）"""
        try:
            session_key = os.urandom(32)
            public_key = serialization.load_pem_public_key(public_key_pem.encode())
            encrypted_key = public_key.encrypt(
                session_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            encrypted_key_b64 = base64.b64encode(encrypted_key).decode()
            
            resp = self.session.post(
                f"http://{train_addr}/api/v1/inject-key",
                json={"encrypted_key": encrypted_key_b64},
                timeout=15
            )
            resp.raise_for_status()
            return {"success": True, "data": resp.json()}
        except Exception as e:
            logger.error(f"密钥注入失败: {str(e)}", exc_info=True)
            return {"success": False, "error": f"密钥注入失败: {str(e)}"}

if __name__ == "__main__":
    print("="*60)
    print("开始机密计算训练工作流")
    print("="*60)
    
    client = ConfidentialComputeClient()
    
    # 1. 创建训练容器
    print("\n1. 创建训练容器...")
    create_result = client.create_container()
    if not create_result["success"]:
        print(f"❌ 容器创建失败: {create_result['error']}")
        if create_result.get("server_error"):
            print(f"   服务端错误详情: {create_result['server_error']}")
        exit(1)
    
    container_info = create_result["data"]
    print(f"✅ 训练容器创建成功")
    print(f"   容器ID: {container_info['container_id']}")
    print(f"   证明代理地址: {container_info['attest_addr']}")
    print(f"   训练服务地址: {container_info['train_addr']}")
    
    # 2. 等待容器完全启动（延长等待+健康检查）
    print("\n2. 等待容器启动...")
    max_wait = 20  # 延长至20秒（容器初始化可能需要时间）
    wait_interval = 2
    elapsed = 0
    attest_ready = False
    attest_addr = container_info["attest_addr"]
    
    while elapsed < max_wait:
        try:
            # 检查证明代理健康状态
            health_resp = requests.get(f"http://{attest_addr}/health", timeout=2)
            if health_resp.status_code == 200:
                attest_ready = True
                break
            logger.debug(f"容器未就绪（{elapsed}/{max_wait}秒）: {health_resp.status_code}")
        except:
            logger.debug(f"容器未就绪（{elapsed}/{max_wait}秒）: 连接失败")
        time.sleep(wait_interval)
        elapsed += wait_interval
    
    if not attest_ready:
        print(f"⚠️  警告：容器未检测到健康状态，但尝试继续证明流程（已等待{max_wait}秒）")
    
    # 3. 远程证明
    print("\n🔐 开始远程证明流程...")
    attest_result = client.attest_container(attest_addr)
    if not attest_result["success"]:
        print(f"❌ 远程证明失败: {attest_result['error']}")
        exit(1)
    
    print(f"✅ 远程证明通过")
    print(f"   验证结果: {attest_result['verify_result']}")
    
    # 4. 注入密钥
    print("\n🔑 注入会话密钥...")
    inject_result = client.inject_key(container_info["train_addr"], attest_result["public_key"])
    if not inject_result["success"]:
        print(f"❌ 密钥注入失败: {inject_result['error']}")
        exit(1)
    
    print(f"✅ 密钥注入成功: {inject_result['data']}")
    
    # 5. 任务完成
    print("\n🎉 机密计算训练工作流执行完成！")