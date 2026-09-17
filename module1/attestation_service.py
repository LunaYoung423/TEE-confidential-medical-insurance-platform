#!/usr/bin/python3.8
from flask import Flask, request, jsonify
import base64
import hashlib
import logging
import subprocess
import os
import sys
import json
import time
import tempfile

from module3.audit.middleware import AuditMiddleware

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
AuditMiddleware(
    app,
    service_name=os.environ.get("AUDIT_SERVICE_NAME_ATTESTATION", "attestation-service"),
)

class AttestationService:
    def __init__(self):
        self.trusted_measurements = self._load_trusted_measurements()
        # 默认用镜像内副本，避免宿主机 bind-mount 的 600/无执行位导致子进程报 Permission denied
        default_tool = "/app/_embedded/csv_attestation_tool.py"
        self.csv_tool = os.environ.get("CSV_ATTESTATION_SCRIPT", default_tool)
        if not os.path.isfile(self.csv_tool):
            self.csv_tool = "/app/csv-attestation.py"
        self.verified_reports = {}

    def _load_trusted_measurements(self):
        trusted_measurements = {"app_measurements": []}
        config_file = '/etc/attestation/trusted_images.json'
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    trusted_measurements['app_measurements'] = config.get('trusted_hashes', [])
            except Exception as e:
                logger.error(f"加载可信配置失败: {e}")
        return trusted_measurements

    def _is_app_measurement_trusted(self, app_measure: str) -> bool:
        if not app_measure:
            return False
        lst = self.trusted_measurements['app_measurements']
        if app_measure in lst:
            return True
        bare = app_measure[7:] if app_measure.startswith("sha256:") else app_measure
        if bare in lst:
            return True
        if f"sha256:{bare}" in lst:
            return True
        return False

    def _save_trusted_images(self):
        """保存可信镜像列表到文件"""
        try:
            # 确保目录存在
            os.makedirs('/etc/attestation', exist_ok=True)
            with open('/etc/attestation/trusted_images.json', 'w') as f:
                json.dump({
                    "trusted_hashes": self.trusted_measurements['app_measurements']
                }, f, indent=2)
            logger.info(f"✅ 可信镜像列表已保存，共 {len(self.trusted_measurements['app_measurements'])} 个")
        except Exception as e:
            logger.error(f"❌ 保存可信镜像失败: {e}")

    def verify_evidence(self, evidence: dict) -> dict:
        evidence_type = evidence.get('type', '')
        if evidence_type == 'csv_simulated':
            if os.environ.get("ALLOW_CSV_SIMULATION", "").lower() not in ("1", "true", "yes"):
                return {
                    "valid": False,
                    "reason": "已禁止模拟证明（csv_simulated）。请在海光 CSV 环境生成 type=csv 的硬件证据，"
                    "或为验证服务设置 ALLOW_CSV_SIMULATION=1 仅用于开发调试。",
                }
            return {
                "valid": True,
                "token": hashlib.sha256(b"simulated").hexdigest()[:32],
                "session_id": hashlib.sha256(b"simulated").hexdigest()[:16],
                "expires_at": time.time() + 3600,
                "measurements": {
                    "csv_status": "simulated",
                    "app_measurement": evidence.get('app_measurement', ''),
                    "evidence_hash": "simulated"
                }
            }
        elif evidence_type == 'csv':
            return self._verify_csv_evidence(evidence)
        else:
            return {"valid": False, "reason": "不支持的证据类型"}

    def _verify_csv_evidence(self, evidence: dict) -> dict:
        try:
            # 新鲜性：以证据中的 timestamp 为准（挑战值为 base64 时不能当时间解析）
            ts = evidence.get("timestamp")
            if ts is not None:
                try:
                    if time.time() - float(ts) > 300:
                        return {"valid": False, "reason": "证明证据已过期"}
                except (TypeError, ValueError):
                    pass
            else:
                ch = str(evidence.get("challenge", ""))
                if "-" in ch:
                    try:
                        challenge_time = float(ch.split("-")[-1])
                        if time.time() - challenge_time > 300:
                            return {"valid": False, "reason": "挑战已过期"}
                    except ValueError:
                        pass

            # 应用程序度量检查（兼容 sha256: 前缀有无）
            app_measure = evidence.get('app_measurement')
            if not self._is_app_measurement_trusted(app_measure):
                logger.warning(f"应用程序镜像哈希不在白名单: {app_measure}")
                return {"valid": False, "reason": "应用程序镜像哈希不在白名单"}

            # 验证硬件证据
            evidence_data = base64.b64decode(evidence['evidence'])
            evidence_hash = hashlib.sha256(evidence_data).hexdigest()
            if evidence_hash in self.verified_reports:
                if time.time() - self.verified_reports[evidence_hash] < 300:
                    return {"valid": False, "reason": "证明报告重复使用"}

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                report_path = tmp.name
                tmp.write(evidence_data)

            try:
                result = subprocess.run(
                    [sys.executable, self.csv_tool, "verify", "-r", report_path],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode != 0:
                    logger.error(f"CSV验证失败: {result.stderr}")
                    return {"valid": False, "reason": f"签名验证失败: {result.stderr[:100]}"}
            finally:
                os.remove(report_path)

            token = hashlib.sha256(evidence_data).hexdigest()[:32]
            session_id = hashlib.sha256(token.encode()).hexdigest()[:16]

            self.verified_reports[evidence_hash] = time.time()
            expired = [k for k, v in self.verified_reports.items() if time.time() - v > 3600]
            for k in expired:
                del self.verified_reports[k]

            return {
                "valid": True,
                "token": token,
                "session_id": session_id,
                "expires_at": time.time() + 3600,
                "measurements": {
                    "csv_status": "secure",
                    "app_measurement": app_measure,
                    "evidence_hash": evidence_hash[:16]
                }
            }
        except Exception as e:
            logger.error(f"验证异常: {e}")
            return {"valid": False, "reason": str(e)}

service = AttestationService()

@app.route('/api/v1/verify', methods=['POST'])
def verify():
    data = request.json
    evidence = data.get('evidence', {})
    if not evidence:
        return jsonify({"code": 400, "message": "缺少evidence"}), 400
    result = service.verify_evidence(evidence)
    return jsonify({
        "code": 0 if result.get('valid') else 400,
        "data": result
    })

@app.route('/api/v1/trusted-images', methods=['GET'])
def get_trusted_images():
    return jsonify({
        "code": 0,
        "data": {
            "trusted_hashes": service.trusted_measurements['app_measurements']
        }
    })

@app.route('/api/v1/trusted-images', methods=['POST'])
def add_trusted_image():
    data = request.json
    image_hash = data.get('image_hash')
    if not image_hash:
        return jsonify({"code": 400, "message": "缺少image_hash"}), 400
    
    is_new = False
    if image_hash not in service.trusted_measurements['app_measurements']:
        service.trusted_measurements['app_measurements'].append(image_hash)
        # 持久化到文件
        service._save_trusted_images()
        logger.info(f"✅ 添加可信镜像哈希并持久化: {image_hash}")
        is_new = True
    else:
        logger.info(f"ℹ️ 镜像哈希已存在: {image_hash}")
    
    return jsonify({
        "code": 0,
        "message": "添加成功" if is_new else "镜像已存在",
        "total": len(service.trusted_measurements['app_measurements'])
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, debug=False)