#!/usr/bin/python3.8
import base64
import docker
import json
import uuid
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse
import requests
from flask import Flask, request, jsonify, make_response, Response
from typing import Any, Dict, List, Optional, Tuple
from werkzeug.security import check_password_hash
from sqlalchemy import select, delete

from module3.audit.middleware import AuditMiddleware
from module3.audit.service import get_audit_service
from module3.audit.context import AuditContext
from module3.audit.models import (
    get_session,
    User,
    Account,
    Task,
    TaskDetail,
    UserNotification,
    AdminAuditEvent,
    TaskAuditEvent,
    SystemConfig,
    AuditLog,
)
from module3.scheduler import get_scheduler_service

_sys_root = os.path.dirname(os.path.abspath(__file__))
if _sys_root not in sys.path:
    sys.path.insert(0, _sys_root)
import wizard_pipeline as wizpl  # noqa: E402

app = Flask(__name__)
AuditMiddleware(
    app,
    service_name=os.environ.get("AUDIT_SERVICE_NAME_CONTROLLER", "controller"),
)
client = docker.from_env()
containers: Dict[str, dict] = {}
containers_lock = threading.RLock()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
_TOKENS: Dict[str, Dict[str, str]] = {}


def _build_cors_origin() -> str:
    # 联调期默认放开；生产可改为精确域名，如 http://8.136.228.188:5173
    return os.environ.get("CORS_ALLOW_ORIGIN", "*")


@app.before_request
def _handle_cors_preflight():
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        origin = _build_cors_origin()
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type,X-User-ID,X-Request-ID"
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp
    return None


@app.after_request
def _attach_cors_headers(resp):
    origin = _build_cors_origin()
    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type,X-User-ID,X-Request-ID"
    return resp


def _scene_name(scene: str) -> str:
    mapper = {
        "fraud": "欺诈检测",
        "claim_amount": "理赔金额预测",
        "anomaly_cluster": "异常行为聚类",
    }
    return mapper.get(scene or "", scene or "")


def _parse_auth_token() -> Optional[Dict[str, str]]:
    auth = request.headers.get("Authorization", "").strip()
    if not auth.startswith("Bearer "):
        return None
    token = auth[len("Bearer ") :].strip()
    if not token:
        return None
    return _TOKENS.get(token)


_ADMIN_SYSTEM_CONFIG_DEFAULTS: Dict[str, Any] = {
    "cert_valid_until": "-",
    "audit_retention_days": 30,
    "tee_driver_path": "/dev/tee0",
    "crypto_lib_version": "v1.2.3",
}


def _require_admin_auth() -> Optional[Dict[str, str]]:
    auth = _parse_auth_token()
    if not auth:
        return None
    if str(auth.get("role") or "").lower() != "admin":
        return {"forbidden": "1"}
    return auth


def _load_admin_system_config(db) -> Dict[str, Any]:
    cfg = dict(_ADMIN_SYSTEM_CONFIG_DEFAULTS)
    rows = (
        db.execute(
            select(SystemConfig).where(SystemConfig.config_key.in_(list(_ADMIN_SYSTEM_CONFIG_DEFAULTS.keys())))
        )
        .scalars()
        .all()
    )
    for r in rows:
        key = str(r.config_key or "")
        if key not in cfg:
            continue
        val = r.config_value
        if key == "audit_retention_days":
            try:
                cfg[key] = int(val)
            except (TypeError, ValueError):
                cfg[key] = int(_ADMIN_SYSTEM_CONFIG_DEFAULTS[key])
        else:
            cfg[key] = str(val or _ADMIN_SYSTEM_CONFIG_DEFAULTS[key])
    return cfg


def _save_admin_system_config(db, payload: Dict[str, Any], updated_by: str) -> Dict[str, Any]:
    cfg = _load_admin_system_config(db)
    if "audit_retention_days" in payload:
        try:
            days = int(payload.get("audit_retention_days"))
        except (TypeError, ValueError):
            raise ValueError("audit_retention_days 必须为整数")
        if days < 1 or days > 3650:
            raise ValueError("audit_retention_days 必须在 1-3650 之间")
        cfg["audit_retention_days"] = days
    if "tee_driver_path" in payload:
        cfg["tee_driver_path"] = str(payload.get("tee_driver_path") or "/dev/tee0").strip() or "/dev/tee0"
    if "crypto_lib_version" in payload:
        cfg["crypto_lib_version"] = str(payload.get("crypto_lib_version") or "v1.2.3").strip() or "v1.2.3"
    if "cert_valid_until" in payload:
        cfg["cert_valid_until"] = str(payload.get("cert_valid_until") or "-").strip() or "-"

    for key, value in cfg.items():
        row = db.execute(select(SystemConfig).where(SystemConfig.config_key == key)).scalar_one_or_none()
        if not row:
            row = SystemConfig(config_key=key)
            db.add(row)
        row.config_value = str(value)
        row.value_type = "int" if key == "audit_retention_days" else "string"
        row.description = f"admin system config: {key}"
        row.updated_by = updated_by
    db.commit()
    return cfg


def _record_business_audit_event(
    *,
    operation_type: str,
    object_type: str,
    object_id: str,
    actor: str,
    result: str = "success",
    detail_json: Optional[dict] = None,
    task_id: Optional[str] = None,
):
    """写业务审计事件（管理员视角），避免把 API 技术日志直接暴露给前端。"""
    db = get_session()
    try:
        event_id = f"audit-{uuid.uuid4().hex[:16]}"
        admin_event = AdminAuditEvent(
            event_id=event_id,
            operation_type=operation_type,
            object_type=object_type,
            object_id=object_id,
            actor=actor,
            result=result,
            detail_json=json.dumps(detail_json or {}, ensure_ascii=False),
        )
        db.add(admin_event)
        if task_id:
            task_event = TaskAuditEvent(
                event_id=f"task-audit-{uuid.uuid4().hex[:16]}",
                task_id=task_id,
                event_type=operation_type,
                result=result,
                node_name=(detail_json or {}).get("node_name"),
                container_name=(detail_json or {}).get("container_name"),
                detail_json=json.dumps(detail_json or {}, ensure_ascii=False),
            )
            db.add(task_event)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"写业务审计事件失败: {e}")
    finally:
        db.close()


def _training_http_base_from_localhost(training_address: str) -> str:
    """与 module3.scheduler 一致：controller 容器内访问宿主机映射的训练端口。"""
    if not training_address:
        return ""
    if training_address.startswith("http://") or training_address.startswith("https://"):
        return training_address.rstrip("/")
    use_local = os.environ.get("SCHEDULER_DYNAMIC_USE_LOCALHOST", "").lower() in ("1", "true", "yes")
    host, sep, port = training_address.partition(":")
    if not sep or not port:
        return f"http://{training_address}"
    if use_local and host.lower() in ("localhost", "127.0.0.1"):
        return f"http://{host}:{port}"
    if host.lower() in ("localhost", "127.0.0.1"):
        gw = os.environ.get("HOST_GATEWAY_IP", "172.17.0.1")
        return f"http://{gw}:{port}"
    return f"http://{training_address}"

class EnvironmentController:
    def __init__(self):
        self.attestation_server = "http://attestation-service:8081"
        self.image_whitelist = self._load_image_whitelist()
        self.training_image = "csv-training-service:latest"
        self._controller_container_data_mount_point = "/data"  # controller 容器内的数据挂载点（来自 docker-compose.yml）
        # 允许通过环境变量指定 CSV 设备节点路径（用于真实远程证明）
        self.csv_device_path = os.getenv('CSV_DEVICE_PATH', '/dev/csv-guest')
        self._restore_recent_dynamic_containers()

    def _parse_docker_created_ts(self, created_raw: str) -> float:
        if not created_raw:
            return time.time()
        try:
            # Docker Created 形如 2026-04-20T14:13:23.123456789Z
            norm = created_raw.replace("Z", "+00:00")
            if "." in norm:
                base, frac_and_tz = norm.split(".", 1)
                tz_idx = frac_and_tz.find("+")
                if tz_idx >= 0:
                    frac = frac_and_tz[:tz_idx]
                    tz = frac_and_tz[tz_idx:]
                    # Python 仅支持微秒（6 位）
                    norm = f"{base}.{frac[:6]}{tz}"
            return datetime.fromisoformat(norm).timestamp()
        except Exception:
            return time.time()

    def _bytes_to_mem_str(self, memory_bytes: int) -> str:
        if memory_bytes <= 0:
            return "4g"
        mb = int(round(memory_bytes / (1024.0 * 1024.0)))
        if mb % 1024 == 0:
            return f"{int(mb / 1024)}g"
        return f"{mb}m"

    def _restore_recent_dynamic_containers(self) -> None:
        """
        controller 重启后恢复最近窗口内的动态 csv-* 容器，避免管理页列表瞬间清空。
        默认恢复窗口为 10 分钟（可用 DYNAMIC_CONTAINER_RESTORE_WINDOW_SECONDS 调整）。
        """
        lc_opts = self._lifecycle_defaults(None)
        default_idle_timeout = float(lc_opts["idle_timeout_seconds"])
        try:
            restore_window = float(
                os.environ.get("DYNAMIC_CONTAINER_RESTORE_WINDOW_SECONDS", str(default_idle_timeout))
            )
        except ValueError:
            restore_window = default_idle_timeout
        restore_window = max(30.0, restore_window)
        now_ts = time.time()
        dyn_net = (os.environ.get("DYNAMIC_CONTAINER_NETWORK") or "").strip()
        restored = 0

        for c in client.containers.list(all=True):
            name = (c.name or "").lstrip("/")
            if not name.startswith("csv-"):
                continue
            if (c.status or "").lower() not in ("running", "restarting"):
                continue
            attrs = c.attrs or {}
            created_at = str(attrs.get("Created") or "")
            created_ts = self._parse_docker_created_ts(created_at)
            if (now_ts - created_ts) > restore_window:
                continue

            ports = ((attrs.get("NetworkSettings") or {}).get("Ports") or {})
            nets = ((attrs.get("NetworkSettings") or {}).get("Networks") or {})
            if dyn_net and dyn_net in nets:
                attestation_address = f"{name}:8006"
                training_address = f"{name}:8000"
            else:
                a = ports.get("8006/tcp") or []
                t = ports.get("8000/tcp") or []
                attestation_address = f"localhost:{a[0]['HostPort']}" if a and a[0].get("HostPort") else None
                training_address = f"localhost:{t[0]['HostPort']}" if t and t[0].get("HostPort") else None

            host_cfg = attrs.get("HostConfig") or {}
            nano_cpus = int(host_cfg.get("NanoCpus") or 0)
            cpu_val = round(nano_cpus / 1e9, 2) if nano_cpus > 0 else 2.0
            mem_val = self._bytes_to_mem_str(int(host_cfg.get("Memory") or 0))

            with containers_lock:
                containers[c.id] = {
                    "id": c.id,
                    "name": c.name,
                    "status": c.status,
                    "attestation_address": attestation_address,
                    "training_address": training_address,
                    "image": (attrs.get("Config") or {}).get("Image") or "",
                    "image_hash": "",
                    "created_at": created_at,
                    "created_ts": created_ts,
                    # 重启后无法准确知道上次活动时间；用当前时间避免误回收
                    "last_activity_ts": now_ts,
                    "idle_timeout_seconds": default_idle_timeout,
                    "idle_min_lifetime_seconds": float(lc_opts["idle_min_lifetime_seconds"]),
                    "idle_reap_enabled": bool(lc_opts["idle_reap_enabled"]),
                    "resources": {"cpu": cpu_val, "memory": mem_val},
                    "task_data": {},
                }
            restored += 1

        if restored > 0:
            logger.info(
                "controller 启动恢复动态容器: restored=%s, window_seconds=%s",
                restored,
                int(restore_window),
            )

    def _lifecycle_defaults(self, lifecycle: Optional[dict]) -> dict:
        lc = dict(lifecycle or {})
        def _f(key: str, env_key: str, default: float) -> float:
            if lc.get(key) is not None:
                return float(lc[key])
            raw = os.environ.get(env_key)
            if raw is not None and str(raw).strip() != "":
                return float(raw)
            return float(default)

        def _b(key: str, env_key: str, default: bool) -> bool:
            if lc.get(key) is not None:
                v = lc[key]
                if isinstance(v, bool):
                    return v
                return str(v).lower() not in ("0", "false", "no", "")
            raw = os.environ.get(env_key)
            if raw is not None and str(raw).strip() != "":
                return str(raw).lower() not in ("0", "false", "no", "")
            return default

        return {
            "idle_timeout_seconds": max(30.0, _f("idle_timeout_seconds", "DYNAMIC_CONTAINER_IDLE_TIMEOUT_SECONDS", 600.0)),
            "idle_min_lifetime_seconds": max(0.0, _f("idle_min_lifetime_seconds", "DYNAMIC_CONTAINER_IDLE_MIN_LIFETIME_SECONDS", 60.0)),
            "idle_reap_enabled": _b("idle_reap_enabled", "DYNAMIC_CONTAINER_IDLE_REAP_ENABLED", True),
        }

    def _fetch_training_workload_busy(self, container_info: dict) -> Optional[bool]:
        addr = container_info.get("training_address")
        if not addr:
            return None
        base = _training_http_base_from_localhost(addr)
        timeout_s_raw = os.environ.get("ADMIN_WORKLOAD_PROBE_TIMEOUT_SECONDS", "0.8")
        try:
            timeout_s = max(0.2, float(timeout_s_raw))
        except ValueError:
            timeout_s = 0.8
        try:
            r = requests.get(f"{base}/v1/workload", timeout=timeout_s)
            if r.status_code != 200:
                return None
            return bool(r.json().get("busy"))
        except Exception as e:
            logger.debug("workload 探测失败: %s", e)
            return None

    def touch_container_activity(self, container_id: str) -> bool:
        """延长空闲回收时间（例如远程证明阶段无训练任务时由客户端定期调用）。"""
        with containers_lock:
            info = containers.get(container_id)
            if not info:
                return False
            info["last_activity_ts"] = time.time()
        return True

    def idle_reap_tick(self) -> None:
        now = time.time()
        with containers_lock:
            snapshot: List[Tuple[str, dict]] = list(containers.items())
        to_destroy: List[str] = []
        for cid, info in snapshot:
            if not info.get("idle_reap_enabled", True):
                continue
            created = float(info.get("created_ts", now))
            if now - created < float(info.get("idle_min_lifetime_seconds", 60.0)):
                continue
            busy = self._fetch_training_workload_busy(info)
            if busy is True:
                with containers_lock:
                    cur = containers.get(cid)
                    if cur:
                        cur["last_activity_ts"] = now
                continue
            if busy is None:
                continue
            idle_sec = float(info.get("idle_timeout_seconds", 600.0))
            with containers_lock:
                cur = containers.get(cid)
                if not cur:
                    continue
                last_act = float(cur.get("last_activity_ts", cur.get("created_ts", now)))
                if now - last_act < idle_sec:
                    continue
                name = cur.get("name")
            logger.info(
                "动态训练容器空闲超时回收: id=%s name=%s idle_timeout=%ss",
                cid[:12],
                name,
                int(idle_sec),
            )
            to_destroy.append(cid)
        for cid in to_destroy:
            self.destroy_container(cid)

    def _get_host_bind_source(self, container_mount_point: str) -> str:
        """
        获取 controller 容器中某个挂载点（例如 /data）对应的宿主机源路径。

        之所以不直接用 mountinfo：在部分场景 mountinfo 解析会把挂载源解析成 /dev/vda3 这类“设备”，
        导致把块设备挂进 /app/data，从而训练报错 `Not a directory`。

        正确做法：通过 Docker API inspection 读取当前容器的 Mounts.Source，拿到真实宿主目录。
        """
        # 1) 优先：Docker API inspection（最可靠）
        try:
            # 从 /proc/self/cgroup 解析当前容器 id（常见形如 .../docker/<id>）
            container_id = None
            with open("/proc/self/cgroup", "r") as f:
                for line in f:
                    if "docker/" in line:
                        container_id = line.strip().split("docker/", 1)[1].split("/", 1)[0]
                        break

            if not container_id:
                # hostname 通常是容器 id 前缀，这里做一个保底判断
                hn = os.environ.get("HOSTNAME", "")
                if hn and len(hn) >= 12 and all(c in "0123456789abcdef" for c in hn.lower()):
                    container_id = hn

            if container_id:
                self_info = client.containers.get(container_id)
                mounts = self_info.attrs.get("Mounts", []) or []
                for m in mounts:
                    if m.get("Destination") == container_mount_point:
                        source = m.get("Source", "")
                        # 防止把 /dev/vda3 这类块设备当目录挂进去
                        if source and not str(source).startswith("/dev/"):
                            return source
                        break
        except Exception:
            pass

        # 2) 兜底：mountinfo（不保证正确，但尽量避免 /dev/*）
        try:
            with open("/proc/self/mountinfo", "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or " - " not in line:
                        continue
                    before, after = line.split(" - ", 1)
                    before_parts = before.split()
                    after_parts = after.split()
                    # before_parts[4] 是 mount point
                    if len(before_parts) >= 5 and before_parts[4] == container_mount_point and len(after_parts) >= 2:
                        # mountinfo: <fstype> <mount_source> ...
                        mount_source = after_parts[1]
                        if mount_source and not str(mount_source).startswith("/dev/"):
                            return mount_source
        except Exception:
            pass

        return ""

    def _host_project_root_for_training(self, host_data_dir: str) -> str:
        """由 ./data 挂载源推断项目根（.../data -> ...），用于把宿主 module1/2 挂进动态训练容器。"""
        explicit = (os.environ.get("HOST_PROJECT_ROOT") or "").strip()
        if explicit:
            return explicit
        if not host_data_dir:
            return ""
        base = host_data_dir.rstrip("/")
        if os.path.basename(base) == "data":
            return os.path.dirname(base)
        return ""

    def _attach_host_modules_to_volumes(self, volumes: dict, host_data_dir: str) -> None:
        """挂载宿主 module1/module2，使 attestation_agent 等为最新代码。
        同时挂载 csv-attestation.py：脚本已按「SM3/SM2 分路导入」兼容 snowland_smx 的 pysmx。"""
        root = self._host_project_root_for_training(host_data_dir)
        if not root:
            logger.warning(
                "未推断出项目根目录（请确认 controller 挂载了 ./data:/data，或设置环境变量 HOST_PROJECT_ROOT）"
            )
            return
        strict_check = os.environ.get("STRICT_HOST_PATH_CHECK", "0").lower() in ("1", "true", "yes")
        for rel, dest, mode in (
            ("module1", "/app/module1", "rw"),
            ("module2", "/app/module2", "rw"),
        ):
            hp = os.path.join(root, rel)
            # hp 是“宿主机路径”，在 controller 容器内直接 os.path.isdir 可能误判不存在。
            # 默认直接透传给 Docker daemon，由宿主机侧判定路径是否可挂载。
            if (not strict_check) or os.path.isdir(hp):
                volumes[hp] = {"bind": dest, "mode": mode}
                logger.info(f"✅ 动态训练容器挂载: {hp} -> {dest}")
            else:
                logger.warning(f"未找到宿主目录，跳过挂载: {hp}")
        csv_script = os.path.join(root, "module1", "csv-attestation.py")
        if (not strict_check) or os.path.isfile(csv_script):
            volumes[csv_script] = {"bind": "/app/csv-attestation.py", "mode": "ro"}
            logger.info(f"✅ 动态训练容器挂载 csv-attestation: {csv_script}")

    def _normalize_database_url_for_dynamic_container(self, raw_url: str) -> str:
        """
        动态容器不是 compose 服务，无法天然继承 host-gateway 映射。
        若 DATABASE_URL 使用 host.docker.internal，这里替换为可达网关 IP。
        """
        if not raw_url:
            return raw_url
        if "host.docker.internal" not in raw_url:
            return raw_url
        gateway_host = os.getenv("HOST_GATEWAY_IP", "172.17.0.1")
        try:
            parsed = urlparse(raw_url)
            host = parsed.hostname
            if host != "host.docker.internal":
                return raw_url
            userinfo = ""
            if parsed.username:
                userinfo = parsed.username
                if parsed.password:
                    userinfo += f":{parsed.password}"
                userinfo += "@"
            netloc = f"{userinfo}{gateway_host}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse(
                (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
            )
        except Exception:
            return raw_url.replace("host.docker.internal", gateway_host)

    def _load_image_whitelist(self):
        whitelist = {}
        config_file = '/etc/attestation/trusted_images.json'
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    hashes = config.get('trusted_hashes', [])
                    for h in hashes:
                        whitelist[h] = "trusted"
            except Exception as e:
                logger.error(f"加载镜像白名单失败: {e}")
        return whitelist

    def _get_image_hash(self, image_name: str) -> str:
        try:
            image = client.images.get(image_name)
            image_id = image.id.replace('sha256:', '')
            logger.info(f"获取到的镜像哈希: {image_id}")
            return image_id
        except docker.errors.ImageNotFound:
            logger.error(f"镜像不存在: {image_name}")
            return ""
        except Exception as e:
            logger.error(f"获取镜像哈希失败 {image_name}: {e}")
            return ""

    @staticmethod
    def _normalize_image_hash_hex(h: str) -> str:
        """统一为无 sha256: 前缀的小写 64 hex，便于与白名单比对。"""
        if not h:
            return ""
        s = str(h).strip().lower()
        if s.startswith("sha256:"):
            s = s[7:]
        return s

    def _verify_image_with_attestation(self, image_hash: str) -> bool:
        """通过证明服务验证镜像哈希"""
        timeout_sec = float(os.environ.get("ATTESTATION_TRUSTED_IMAGES_TIMEOUT", "8"))
        norm_local = self._normalize_image_hash_hex(image_hash)
        try:
            logger.info(f"正在验证镜像哈希: {image_hash}")
            resp = requests.get(
                f"{self.attestation_server}/api/v1/trusted-images",
                timeout=timeout_sec,
            )

            if resp.status_code != 200:
                logger.error(f"证明服务返回错误: {resp.status_code}")
                return norm_local in map(
                    self._normalize_image_hash_hex, self.image_whitelist
                )

            data = resp.json()
            trusted_hashes = data.get("data", {}).get("trusted_hashes", [])
            logger.info(f"从证明服务获取的白名单: {trusted_hashes}")

            for h in trusted_hashes:
                hn = self._normalize_image_hash_hex(str(h))
                if norm_local and hn == norm_local:
                    logger.info(f"✅ 镜像验证通过，匹配哈希: {h}")
                    return True

            logger.warning(f"❌ 镜像哈希 {norm_local} 不在白名单中")
            return False

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            logger.error(
                "无法连接证明服务或请求超时(%ss)，改用本地白名单: %s",
                int(timeout_sec),
                e,
            )
            return norm_local in map(self._normalize_image_hash_hex, self.image_whitelist)
        except Exception as e:
            logger.error(f"验证镜像时发生错误: {e}")
            return norm_local in map(self._normalize_image_hash_hex, self.image_whitelist)

    def create_container(self, image: str, resources: dict, task_data: dict = None, lifecycle: dict = None) -> tuple:
        logger.info("=" * 60)
        logger.info("开始创建容器流程")
        
        # 获取镜像哈希
        image_hash = self._get_image_hash(image)
        if not image_hash:
            raise ValueError(f"无法获取镜像 {image} 的哈希值")
        
        logger.info(f"待验证的镜像哈希: {image_hash}")
        
        # 通过证明服务验证
        if not self._verify_image_with_attestation(image_hash):
            error_msg = f"镜像 {image} (哈希: {image_hash}) 不在可信白名单中"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.info("✅ 镜像验证通过，开始创建容器")

        lc_opts = self._lifecycle_defaults(lifecycle)

        startup_command = [
            "sh", "-c",
            f"python3 /app/module1/attestation_agent.py & "
            f"sleep 5 && "
            f"cd /app/module2 && "
            f"uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1"
        ]

        raw_database_url = os.getenv("DATABASE_URL", "")
        dynamic_database_url = self._normalize_database_url_for_dynamic_container(raw_database_url)

        env_vars = {
            "ATTESTATION_SERVER": self.attestation_server,
            "CONTAINER_MODE": "csv",
            "TASK_DATA": json.dumps(task_data) if task_data else "{}",
            "CONTAINER_IMAGE_HASH": image_hash,
            # 审计相关环境变量透传到动态训练容器，避免 /v1/tasks 因审计初始化失败而 500
            "DATABASE_URL": dynamic_database_url,
            "AUDIT_DEFAULT_ACCOUNT_ID": os.getenv("AUDIT_DEFAULT_ACCOUNT_ID", "1"),
            "AUDIT_SM2_PRIVATE_KEY": os.getenv("AUDIT_SM2_PRIVATE_KEY", ""),
            "AUDIT_SM2_PUBLIC_KEY": os.getenv("AUDIT_SM2_PUBLIC_KEY", ""),
            "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
            "PYTHONPATH": "/app",
        }

        try:
            host_data_dir = self._get_host_bind_source(self._controller_container_data_mount_point)
            volumes = {
                '/tmp': {'bind': '/tmp', 'mode': 'rw'}  # 挂载主机/tmp到容器/tmp
            }
            if host_data_dir:
                # 让动态训练容器能读到 integrated_client 写入的数据密文文件
                volumes[host_data_dir] = {'bind': '/app/data', 'mode': 'rw'}
                logger.info(f"✅ 挂载数据目录到训练容器: {host_data_dir} -> /app/data")
                self._attach_host_modules_to_volumes(volumes, host_data_dir)
            else:
                logger.warning(
                    f"未能解析 controller 容器内 {self._controller_container_data_mount_point} 对应的宿主机路径，"
                    "动态训练容器将无法读取 /app/data 下的加密数据。"
                )

            dyn_net = (os.environ.get("DYNAMIC_CONTAINER_NETWORK") or "").strip()
            container_name = f"csv-{uuid.uuid4().hex[:8]}"
            run_kw: Dict[str, object] = dict(
                image=image,
                command=startup_command,
                detach=True,
                devices=[f"{self.csv_device_path}:{self.csv_device_path}:rwm"],
                privileged=True,
                mem_limit=resources.get("memory", "4g"),
                nano_cpus=int(resources.get("cpu", 2) * 1e9),
                ports={
                    "8006/tcp": None,
                    "8000/tcp": None,
                },
                environment=env_vars,
                volumes=volumes,
                extra_hosts={"host.docker.internal": "host-gateway"},
                name=container_name,
            )
            if dyn_net:
                run_kw["network"] = dyn_net
                logger.info("✅ 动态训练容器将加入 Docker 网络: %s（controller 内网直连证明/训练端口）", dyn_net)

            container = client.containers.run(**run_kw)

            container.reload()
            dns_name = (container.name or "").lstrip("/")
            ports = container.attrs["NetworkSettings"]["Ports"]
            now_ts = time.time()
            if dyn_net:
                attestation_address = f"{dns_name}:8006"
                training_address = f"{dns_name}:8000"
            else:
                attestation_address = (
                    f"localhost:{ports['8006/tcp'][0]['HostPort']}" if ports.get("8006/tcp") else None
                )
                training_address = (
                    f"localhost:{ports['8000/tcp'][0]['HostPort']}" if ports.get("8000/tcp") else None
                )

            container_info = {
                "id": container.id,
                "name": container.name,
                "status": container.status,
                "attestation_address": attestation_address,
                "training_address": training_address,
                "image": image,
                "image_hash": image_hash,
                "created_at": container.attrs['Created'],
                "created_ts": now_ts,
                "last_activity_ts": now_ts,
                "idle_timeout_seconds": lc_opts["idle_timeout_seconds"],
                "idle_min_lifetime_seconds": lc_opts["idle_min_lifetime_seconds"],
                "idle_reap_enabled": lc_opts["idle_reap_enabled"],
                "resources": {
                    "cpu": float(resources.get("cpu", 2)),
                    "memory": resources.get("memory", "4g"),
                },
                # 供管理端详情/审计关联：用户向导会带 portal_task_id
                "task_data": dict(task_data) if isinstance(task_data, dict) else {},
            }
            with containers_lock:
                containers[container.id] = container_info
            logger.info(f"✅ 容器创建成功: {container.id}")
            logger.info(f"   证明代理地址: {container_info['attestation_address']}")
            logger.info(f"   训练服务地址: {container_info['training_address']}")
            logger.info("=" * 60)
            return container.id, container_info
            
        except Exception as e:
            logger.error(f"容器创建失败: {e}")
            raise

    def destroy_container(self, container_id: str) -> bool:
        try:
            container = client.containers.get(container_id)
            container.stop(timeout=10)
            container.remove()
            with containers_lock:
                containers.pop(container_id, None)
            logger.info(f"销毁容器成功: {container_id}")
            return True
        except Exception as e:
            logger.error(f"销毁容器失败 {container_id}: {e}")
            return False

    def update_container_resources(self, container_id: str, resources: dict) -> dict:
        """
        运行中调整 CPU/内存配额（单机容器级“缩容/扩容”资源维度）。
        cpu 为 vCPU 近似值；内存支持 Docker 字符串如 4g、512m。
        """
        container = client.containers.get(container_id)
        mem = resources.get("memory", "4g")
        cpu = float(resources.get("cpu", 2))
        # 与 create 时 nano_cpus 一致：Docker 不允许在已设置 NanoCPUs 的容器上再写 cpu_period/cpu_quota
        nano_cpus = int(cpu * 1e9)
        container.update(mem_limit=mem, nano_cpus=nano_cpus)
        with containers_lock:
            info = containers.get(container_id)
            if info:
                info["resources"] = {"cpu": cpu, "memory": mem}
                info["last_activity_ts"] = time.time()
        return {"container_id": container_id, "cpu": cpu, "memory": mem}

    def list_containers(self) -> list:
        with containers_lock:
            return list(containers.values())

    def create_training_container(self, resources: dict, task_data: dict, lifecycle: dict = None) -> tuple:
        return self.create_container(self.training_image, resources, task_data, lifecycle)

controller = EnvironmentController()
scheduler = get_scheduler_service(controller)


def _idle_reaper_loop() -> None:
    interval = int(os.environ.get("DYNAMIC_CONTAINER_REAP_INTERVAL_SECONDS", "30") or "30")
    interval = max(5, interval)
    while True:
        time.sleep(interval)
        try:
            controller.idle_reap_tick()
        except Exception:
            logger.exception("idle_reaper tick 异常")


threading.Thread(target=_idle_reaper_loop, name="dynamic-container-idle-reaper", daemon=True).start()

# ---------- 管理端 TEE 资源池（节点列表 / 真实指标 / 扩容缩容 / 电源） ----------
_ADMIN_NODE_LOCK = threading.RLock()
_ADMIN_NODE_STATE: Dict[str, Dict[str, Any]] = {
    "an-01": {
        "status": "online",
        # 默认总容量略高于常见单容器限额，避免一进来就「已用 > 配置」；扩容/缩容只改此字段，不与已用混写
        "epc_total_mb": 8192,
        "csv_protected_size": 512,
        "csv_protection_level": "enhanced",
    },
    "an-02": {
        "status": "offline",
        "epc_total_mb": 2048,
        "csv_protected_size": 512,
        "csv_protection_level": "enhanced",
    },
    "an-03": {
        "status": "offline",
        "epc_total_mb": 1024,
        "csv_protected_size": 512,
        "csv_protection_level": "enhanced",
    },
}
_ADMIN_NODE_IDS = frozenset(_ADMIN_NODE_STATE.keys())

# 节点监控：避免每次列表/轮询都对全部 csv-* 容器打 stats（极慢），短时复用结果
_ADMIN_METRICS_LOCK = threading.RLock()
_ADMIN_METRICS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
try:
    _ADMIN_METRICS_TTL = float(os.environ.get("ADMIN_NODE_METRICS_CACHE_SECONDS", "3") or "3")
except ValueError:
    _ADMIN_METRICS_TTL = 3.0
_ADMIN_METRICS_TTL = max(0.5, min(_ADMIN_METRICS_TTL, 30.0))


def _csv_total_envelope_mb(pool_mb_cfg: float, sum_limits_mb: float) -> float:
    """
    「整个 CSV 包含内存」作为占比分母：
    1) CSV_PLATFORM_PROTECTED_MEMORY_MB（与单容器 metrics 一致）
    2) 否则 CSV_TOTAL_PROTECTED_MEMORY_MB
    3) 否则用各 csv-* 容器 cgroup 内存上限之和（表征平台为训练预留的包络），至少 512MB
    """
    if pool_mb_cfg > 0:
        return pool_mb_cfg
    raw = (os.environ.get("CSV_TOTAL_PROTECTED_MEMORY_MB") or "").strip()
    if raw:
        try:
            v = float(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return max(float(sum_limits_mb), 512.0)


def _compute_platform_metrics_inner() -> Dict[str, Any]:
    """聚合训练相关容器（csv-* / cc-training）的已用内存 + CPU；供 an-01 与缓存使用。"""
    pool_mb_env = (os.environ.get("CSV_PLATFORM_PROTECTED_MEMORY_MB") or "").strip()
    try:
        pool_mb_cfg = float(pool_mb_env) if pool_mb_env else 0.0
    except ValueError:
        pool_mb_cfg = 0.0
    total_used_mb = 0.0
    sum_limits_mb = 0.0
    active_train_containers = 0
    try:
        for c in client.containers.list(all=True):
            nm = (c.name or "").lstrip("/")
            # 动态训练容器通常命名为 csv-*；静态训练容器为 cc-training
            if not (nm.startswith("csv-") or nm == "cc-training"):
                continue
            try:
                st = c.stats(stream=False)
            except Exception:
                continue
            active_train_containers += 1
            mem = (st or {}).get("memory_stats") or {}
            usage = float(mem.get("usage") or 0)
            limit = float(mem.get("limit") or 0)
            total_used_mb += usage / (1024.0 * 1024.0)
            if 0 < limit < 1e15:
                sum_limits_mb += limit / (1024.0 * 1024.0)
    except Exception as ex:
        logger.debug("聚合 csv-* 容器内存失败: %s", ex)
    envelope_mb = _csv_total_envelope_mb(pool_mb_cfg, sum_limits_mb)
    pct = max(0.0, min(100.0, 100.0 * total_used_mb / envelope_mb)) if envelope_mb else 0.0
    cpu_pct = _host_cpu_percent_approx()
    try:
        data = scheduler.collect_metrics()
        vals: List[float] = []
        for it in data.get("containers") or []:
            v = it.get("cpu_percent")
            if isinstance(v, (int, float)):
                vals.append(float(v))
        if vals:
            cpu_pct = round(sum(vals) / len(vals), 2)
    except Exception as ex:
        logger.debug("collect_metrics CPU: %s", ex)
    return {
        "used_mb": round(total_used_mb, 2),
        "pool_mb": round(envelope_mb, 2),
        "csv_memory_pct": round(pct, 2),
        "cpu_percent": float(cpu_pct),
        "active_train_containers": int(active_train_containers),
    }


def _get_cached_platform_metrics() -> Dict[str, Any]:
    now = time.time()
    with _ADMIN_METRICS_LOCK:
        cached = _ADMIN_METRICS_CACHE.get("data")
        ts = float(_ADMIN_METRICS_CACHE.get("ts") or 0.0)
        if cached is not None and (now - ts) < _ADMIN_METRICS_TTL:
            return dict(cached)
    snap = _compute_platform_metrics_inner()
    with _ADMIN_METRICS_LOCK:
        _ADMIN_METRICS_CACHE["ts"] = time.time()
        _ADMIN_METRICS_CACHE["data"] = snap
    return dict(snap)


def _host_cpu_percent_approx() -> float:
    """宿主机 CPU 占用近似 %（无训练容器 stats 时）。"""
    try:
        def _read_stat():
            with open("/proc/stat", "r", encoding="utf-8") as f:
                parts = f.readline().split()
            nums = [int(x) for x in parts[1:8]]
            active = nums[0] + nums[1] + nums[2]
            idle = nums[3]
            return active, idle

        a1, i1 = _read_stat()
        time.sleep(0.12)
        a2, i2 = _read_stat()
        da, di = a2 - a1, i2 - i1
        if da + di <= 0:
            return 0.0
        return round(100.0 * da / (da + di), 2)
    except Exception:
        try:
            with open("/proc/loadavg", "r", encoding="utf-8") as f:
                la = float(f.read().split()[0])
            n = max(1, (os.cpu_count() or 1))
            return round(min(100.0, (la / n) * 100.0), 2)
        except Exception:
            return 0.0


def _aggregate_csv_named_containers_memory() -> Tuple[float, float, float]:
    """csv-* 训练容器已用内存、CSV 包络总容量(MB)、占比%（带短时缓存）。"""
    m = _get_cached_platform_metrics()
    return float(m["used_mb"]), float(m["pool_mb"]), float(m["csv_memory_pct"])


def _admin_node_cpu_physical() -> float:
    """TEE节点A：与内存同缓存快照中的 CPU%。"""
    return float(_get_cached_platform_metrics()["cpu_percent"])


def _admin_live_metrics_payload(node_id: str) -> Dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    with _ADMIN_NODE_LOCK:
        st = dict(_ADMIN_NODE_STATE.get(node_id) or {})
    if st.get("status") == "offline":
        pool = float(int(st.get("epc_total_mb") or 1024))
        return {
            "time": now_iso,
            "cpu_percent": 0.0,
            "csv_memory_pct": 0.0,
            "used_mb": 0.0,
            "pool_mb": round(pool, 2),
        }
    if node_id == "an-01":
        m = _get_cached_platform_metrics()
        env_pool = float(m["pool_mb"])
        used = float(m["used_mb"])
        # 展示用「总容量」= 管理端配置的 epc_total_mb（扩容/缩容即改此值）；聚合包络单独字段供参考
        cfg = float(max(256, int(st.get("epc_total_mb") or 1024)))
        pct = (100.0 * used / cfg) if cfg > 0 else 0.0
        return {
            "time": now_iso,
            "cpu_percent": m["cpu_percent"],
            "csv_memory_pct": round(pct, 2),
            "used_mb": used,
            "pool_mb": round(cfg, 2),
            "csv_envelope_mb": round(env_pool, 2),
            "active_train_containers": int(m.get("active_train_containers") or 0),
        }
    # 其它节点：稳定可复现的模拟曲线（接口形态与 an-01 一致）
    pool = float(max(256, int(st.get("epc_total_mb") or 2048)))
    tick = int(time.time()) // 20
    seed = (hash(node_id) % 10007) + tick * 13
    cpu_pct = float(18 + (seed % 52))
    mem_pct = float(22 + (seed * 11 % 55))
    used_mb = round(pool * mem_pct / 100.0, 2)
    csv_pct = round(100.0 * used_mb / pool, 2) if pool > 0 else 0.0
    return {
        "time": now_iso,
        "cpu_percent": round(cpu_pct, 2),
        "csv_memory_pct": csv_pct,
        "used_mb": used_mb,
        "pool_mb": round(pool, 2),
        "active_train_containers": 1,
    }


def _admin_nodes_list_rows() -> List[Dict[str, Any]]:
    """节点列表行：epc_total_mb 仅为用户配置的总容量，不因已用自动改写；已用为真实聚合值（可大于配置）。"""
    rows: List[Dict[str, Any]] = []
    with _ADMIN_NODE_LOCK:
        for nid, name, ip in (
            ("an-01", "TEE节点A", "192.168.10.11"),
            ("an-02", "TEE节点B", "192.168.10.12"),
            ("an-03", "TEE节点C", "192.168.10.13"),
        ):
            st = _ADMIN_NODE_STATE.setdefault(
                nid,
                {
                    "status": "online" if nid == "an-01" else "offline",
                    "epc_total_mb": 1024 if nid != "an-02" else 2048,
                    "csv_protected_size": 512,
                    "csv_protection_level": "enhanced",
                },
            )
            status = str(st.get("status") or ("online" if nid == "an-01" else "offline"))
            epc_total = int(st.get("epc_total_mb") or (1024 if nid != "an-02" else 2048))
            if nid == "an-01":
                used_mb, _, _ = _aggregate_csv_named_containers_memory()
                uh = int(max(0, round(used_mb)))
                epc_used = uh
            else:
                lm = _admin_live_metrics_payload(nid)
                epc_used = int(max(0, min(epc_total, int(round(float(lm.get("used_mb") or 0))))))
            rows.append(
                {
                    "id": nid,
                    "name": name,
                    "ip": ip,
                    "cpu_model": "海光",
                    "tee_type": "CSV",
                    "status": status,
                    "epc_total_mb": epc_total,
                    "epc_used_mb": epc_used,
                    "csv_protected_size": int(st.get("csv_protected_size") or 512),
                    "csv_protection_level": str(st.get("csv_protection_level") or "enhanced"),
                }
            )
    return rows


def _admin_nodes_panel_payload() -> Dict[str, Any]:
    """
    单次列表构建 + 同源 live_metrics（内部复用同一条 Docker 指标缓存），
    避免前端「先拉列表再拉监控」触发两轮全量 stats。
    """
    nodes = _admin_nodes_list_rows()
    live_metrics: Dict[str, Any] = {}
    for nid in ("an-01", "an-02", "an-03"):
        if nid in _ADMIN_NODE_IDS:
            live_metrics[nid] = _admin_live_metrics_payload(nid)
    return {"nodes": nodes, "live_metrics": live_metrics}


@app.route("/api/v1/scheduler/tasks", methods=["POST"])
def scheduler_submit_task():
    data = request.get_json(silent=True) or {}
    try:
        job = scheduler.submit(data)
        return jsonify({"code": 0, "data": {"job_id": job.job_id, "status": job.status.value}})
    except RuntimeError as e:
        return jsonify({"code": 429, "message": str(e)}), 429
    except Exception as e:
        logger.error("调度入队失败: %s", e)
        return jsonify({"code": 500, "message": str(e)}), 500


@app.route("/api/v1/scheduler/tasks", methods=["GET"])
def scheduler_list_tasks():
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        limit = 50
    jobs = scheduler.list_jobs(limit=limit)
    return jsonify({"code": 0, "data": {"jobs": [j.to_public_dict() for j in jobs], "count": len(jobs)}})


@app.route("/api/v1/scheduler/tasks/<job_id>", methods=["GET"])
def scheduler_get_task(job_id):
    job = scheduler.get_job(job_id)
    if not job:
        return jsonify({"code": 404, "message": "job not found"}), 404
    return jsonify({"code": 0, "data": job.to_public_dict()})


@app.route("/api/v1/scheduler/tasks/<job_id>", methods=["DELETE"])
def scheduler_cancel_task(job_id):
    ok = scheduler.cancel_job(job_id)
    if not ok:
        return jsonify({"code": 404, "message": "job not found"}), 404
    return jsonify({"code": 0, "message": "cancel requested"})


@app.route("/api/v1/scheduler/config", methods=["GET"])
def scheduler_get_config():
    return jsonify({"code": 0, "data": scheduler.get_config()})


@app.route("/api/v1/scheduler/scale", methods=["POST"])
def scheduler_scale():
    body = request.get_json(silent=True) or {}
    n = body.get("max_concurrent_jobs") or body.get("max_workers")
    if n is None:
        return jsonify({"code": 400, "message": "缺少 max_concurrent_jobs"}), 400
    try:
        cap = scheduler.set_max_concurrent(int(n))
    except (TypeError, ValueError):
        return jsonify({"code": 400, "message": "max_concurrent_jobs 无效"}), 400
    return jsonify({"code": 0, "data": {"max_concurrent_jobs": cap}})


@app.route("/api/v1/scheduler/metrics", methods=["GET"])
def scheduler_metrics():
    return jsonify({"code": 0, "data": scheduler.collect_metrics()})


@app.route("/api/v1/admin/nodes", methods=["GET"])
def admin_nodes_list():
    """管理端 TEE 资源池：返回 nodes + live_metrics，一次响应减少前端往返与重复 Docker 扫描。"""
    return jsonify({"code": 0, "data": _admin_nodes_panel_payload()})


@app.route("/api/v1/admin/nodes/<node_id>/live-metrics", methods=["GET"])
def admin_node_live_metrics(node_id: str):
    """节点监控：an-01 为 Docker 聚合真实 CPU + CSV 保护区内存；其它节点返回同结构模拟数据。"""
    nid = (node_id or "").strip()
    if nid not in _ADMIN_NODE_IDS:
        return jsonify({"code": 404, "message": "节点不存在"}), 404
    return jsonify({"code": 0, "data": _admin_live_metrics_payload(nid)})


@app.route("/api/v1/admin/nodes/<node_id>/detail", methods=["GET"])
def admin_node_drawer_detail(node_id: str):
    """节点详情抽屉：与列表同源字段 + 硬件/容器/证明摘要。"""
    nid = (node_id or "").strip()
    if nid not in _ADMIN_NODE_IDS:
        return jsonify({"code": 404, "message": "节点不存在"}), 404
    base = next((x for x in _admin_nodes_list_rows() if x.get("id") == nid), None)
    if not base:
        return jsonify({"code": 404, "message": "节点不存在"}), 404
    hw = {
        "kernel_version": "5.15.0-103",
        "tee_driver_version": "tee-driver-1.2.0",
        "cpu_cores": 32,
        "memory_total_gb": 128,
    }
    running: List[Dict[str, Any]] = []
    try:
        if nid == "an-01":
            with containers_lock:
                snap = dict(containers)
            for cid, info in snap.items():
                try:
                    c = client.containers.get(cid)
                    nm = (c.name or "").lstrip("/")
                    if not nm.startswith("csv-"):
                        continue
                    mem = str((info.get("resources") or {}).get("memory", "4g")).lower()
                    lim_mb = int(round(_memory_str_to_mb(mem)))
                    running.append(
                        {
                            "name": nm,
                            "status": c.status,
                            "epc_used_mb": min(base.get("epc_used_mb") or 0, lim_mb),
                            "epc_limit_mb": lim_mb,
                        }
                    )
                except Exception:
                    continue
    except Exception:
        pass
    now_ts = time.time()
    recent_proofs: List[Dict[str, Any]] = []
    for i in range(5):
        recent_proofs.append(
            {
                "time": datetime.fromtimestamp(now_ts - i * 3600, tz=timezone.utc).isoformat(),
                "result": "pass",
                "reason": "-",
            }
        )
    out = {**base, "hardware": hw, "running_containers": running, "recent_proofs": recent_proofs}
    return jsonify({"code": 0, "data": out})


@app.route("/api/v1/admin/nodes/<node_id>/resources", methods=["POST"])
def admin_node_update_resources(node_id: str):
    """
    CSV 节点 EPC/保护区配置（管理端扩容/缩容复用此接口）。
    body: { epc_total_mb?, protected_size?, protection_level? }
    """
    nid = (node_id or "").strip()
    if nid not in _ADMIN_NODE_IDS:
        return jsonify({"code": 404, "message": "节点不存在"}), 404
    body = request.get_json(silent=True) or {}
    with _ADMIN_NODE_LOCK:
        st = _ADMIN_NODE_STATE.setdefault(nid, {})
        if "epc_total_mb" in body and body.get("epc_total_mb") is not None:
            try:
                total = int(body.get("epc_total_mb"))
            except (TypeError, ValueError):
                return jsonify({"code": 400, "message": "epc_total_mb 无效"}), 400
            if total < 256:
                return jsonify({"code": 400, "message": "epc_total_mb 不得低于 256"}), 400
            if nid == "an-01":
                used_hint = int(max(0, round(_aggregate_csv_named_containers_memory()[0])))
                # 总容量不得小于当前已用；不自动改写为已用，避免「扩容」变成对齐到占用
                if total < used_hint:
                    return jsonify(
                        {
                            "code": 400,
                            "message": (
                                f"配置总容量 epc_total_mb 不可低于当前 CSV 容器已用约 {used_hint}MB；"
                                f"请先释放任务或先调高总容量至 ≥{used_hint}"
                            ),
                        }
                    ), 400
            st["epc_total_mb"] = total
        if "protected_size" in body and body.get("protected_size") is not None:
            try:
                st["csv_protected_size"] = int(body.get("protected_size"))
            except (TypeError, ValueError):
                return jsonify({"code": 400, "message": "protected_size 无效"}), 400
        if body.get("protection_level") is not None:
            st["csv_protection_level"] = str(body.get("protection_level"))[:32]
    # 不清空 metrics 缓存：扩容缩容只改 epc_total_mb，live-metrics 会与配置合并展示；
    # 若此处清空缓存会导致紧接着的列表+监控各触发一轮全量 docker stats，界面明显卡顿。
    return jsonify({"code": 0, "data": {"node_id": nid}})


@app.route("/api/v1/admin/nodes/<node_id>/power", methods=["POST"])
def admin_node_power(node_id: str):
    """电源：power=on|off，立即切换在线/离线（前端负责「打开中/关闭中」约 10s 展示）。"""
    nid = (node_id or "").strip()
    if nid not in _ADMIN_NODE_IDS:
        return jsonify({"code": 404, "message": "节点不存在"}), 404
    body = request.get_json(silent=True) or {}
    p = str(body.get("power") or "").strip().lower()
    if p not in ("on", "off"):
        return jsonify({"code": 400, "message": "power 须为 on 或 off"}), 400
    with _ADMIN_NODE_LOCK:
        st = _ADMIN_NODE_STATE.setdefault(nid, {})
        st["status"] = "online" if p == "on" else "offline"
        new_status = st["status"]
    return jsonify({"code": 0, "data": {"node_id": nid, "status": new_status}})


@app.route("/api/v1/containers/<container_id>/resources", methods=["POST"])
def scale_container_resources(container_id):
    body = request.get_json(silent=True) or {}
    try:
        out = controller.update_container_resources(container_id, body)
        return jsonify({"code": 0, "data": out})
    except Exception as e:
        logger.error("更新容器资源失败: %s", e)
        return jsonify({"code": 500, "message": str(e)}), 500


@app.route('/api/v1/containers', methods=['POST'])
def create_container():
    data = request.json
    try:
        task_data = data.get('task_data', {})
        lifecycle = data.get('lifecycle')
        if data.get('mode') == 'training':
            cid, info = controller.create_training_container(
                resources=data.get('resources', {}),
                task_data=task_data,
                lifecycle=lifecycle,
            )
        else:
            cid, info = controller.create_container(
                image=data['image'],
                resources=data.get('resources', {}),
                task_data=data.get('task_data'),
                lifecycle=lifecycle,
            )
        return jsonify({
            "code": 0,
            "data": {
                "container_id": cid,
                **info
            }
        })
    except ValueError as e:
        logger.error(f"创建容器失败: {e}")
        return jsonify({"code": 500, "message": str(e)}), 500
    except Exception as e:
        logger.error(f"创建容器失败: {e}")
        return jsonify({"code": 500, "message": str(e)}), 500

def _admin_workload_status(container_info: dict) -> str:
    """
    管理端展示用二元状态：训练服务报告有任务在执行 -> InProgress，否则 -> Pending。
    无法探测 workload 时保守为 Pending。
    """
    now_ts = time.time()
    checked_ts = float(container_info.get("admin_status_checked_ts") or 0.0)
    cached = container_info.get("admin_status")
    cache_ttl = float(os.environ.get("ADMIN_WORKLOAD_STATUS_CACHE_SECONDS", "5") or "5")
    if cached in ("InProgress", "Pending") and (now_ts - checked_ts) <= max(1.0, cache_ttl):
        return str(cached)

    busy = controller._fetch_training_workload_busy(container_info)
    if busy is True:
        status = "InProgress"
    else:
        status = "Pending"
    container_info["admin_status"] = status
    container_info["admin_status_checked_ts"] = now_ts
    return status


def _normalize_task_data(info: dict) -> dict:
    td = info.get("task_data")
    if isinstance(td, dict):
        return td
    if isinstance(td, str) and td.strip():
        try:
            return json.loads(td)
        except Exception:
            return {}
    return {}


def _container_node_display_name(info: dict) -> str:
    td = _normalize_task_data(info)
    if str(td.get("portal_task_id") or "").strip():
        return "TEE节点A"
    return "docker-host"


def _memory_str_to_mb(mem_str: str) -> float:
    s = str(mem_str or "4g").lower().strip()
    try:
        if s.endswith("g"):
            return float(s[:-1]) * 1024.0
        if s.endswith("m"):
            return float(s[:-1])
        if s.endswith("k"):
            return float(s[:-1]) / 1024.0
    except ValueError:
        pass
    return 4096.0


@app.route('/api/v1/containers/<container_id>', methods=['GET', 'DELETE'])
def get_or_destroy_container(container_id):
    if request.method == "GET":
        with containers_lock:
            info = containers.get(container_id)
        if not info:
            return jsonify({"code": 404, "message": "容器不存在"}), 404
        td = _normalize_task_data(info)
        out = {
            "id": info.get("id"),
            "name": info.get("name") or "",
            "image": info.get("image") or "",
            "status": _admin_workload_status(info),
            "node_name": _container_node_display_name(info),
            "created_at": info.get("created_at"),
            "portal_task_id": str(td.get("portal_task_id") or ""),
        }
        return jsonify({"code": 0, "data": out})
    success = controller.destroy_container(container_id)
    if success:
        return jsonify({"code": 0, "message": "destroyed"})
    return jsonify({"code": 404, "message": "not found"}), 404


@app.route("/api/v1/containers/<container_id>/audit", methods=["GET"])
def container_audit_logs(container_id):
    with containers_lock:
        info = containers.get(container_id)
    if not info:
        return jsonify({"code": 404, "message": "容器不存在"}), 404
    td = _normalize_task_data(info)
    portal_tid = str(td.get("portal_task_id") or "").strip() or None
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    try:
        size = int(request.args.get("size", 200))
    except ValueError:
        size = 200
    data = get_audit_service().query_audit_logs_for_container(
        container_id, portal_tid, page=page, size=size
    )
    return jsonify({"code": 0, "data": data})


@app.route("/api/v1/containers/<container_id>/logs", methods=["GET"])
def container_logs(container_id):
    with containers_lock:
        info = containers.get(container_id)
    if not info:
        return jsonify({"code": 404, "message": "容器不存在"}), 404
    try:
        tail = int(request.args.get("tail", 300))
    except ValueError:
        tail = 300
    tail = max(50, min(tail, 2000))
    try:
        c = client.containers.get(container_id)
        raw = c.logs(tail=tail)
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        lines = text.splitlines()
    except Exception as e:
        logger.warning("读取容器日志失败 %s: %s", container_id[:12], e)
        lines = []
    return jsonify({"code": 0, "data": {"lines": lines}})


@app.route("/api/v1/containers/<container_id>/metrics", methods=["GET"])
def container_metrics(container_id):
    """Docker 内存用量相对「CSV 平台受保护区」配置或本容器 cgroup 上限的占比（%）。"""
    with containers_lock:
        info = containers.get(container_id)
    if not info:
        return jsonify({"code": 404, "message": "容器不存在"}), 404
    now_iso = datetime.now(timezone.utc).isoformat()
    pool_mb_env = (os.environ.get("CSV_PLATFORM_PROTECTED_MEMORY_MB") or "").strip()
    try:
        pool_mb_cfg = float(pool_mb_env) if pool_mb_env else 0.0
    except ValueError:
        pool_mb_cfg = 0.0
    res_mem = (info.get("resources") or {}).get("memory", "4g")
    cgroup_limit_mb = _memory_str_to_mb(res_mem)
    try:
        c = client.containers.get(container_id)
        st = c.stats(stream=False)
        mem = (st or {}).get("memory_stats") or {}
        usage = float(mem.get("usage") or 0)
        limit = float(mem.get("limit") or 0)
        if limit <= 0 or limit > 1e15:
            limit = cgroup_limit_mb * 1024.0 * 1024.0
        used_mb = usage / (1024.0 * 1024.0)
        limit_mb = limit / (1024.0 * 1024.0) if limit > 0 else cgroup_limit_mb
        denom_mb = pool_mb_cfg if pool_mb_cfg > 0 else max(limit_mb, 1.0)
        pct = max(0.0, min(100.0, 100.0 * used_mb / denom_mb))
    except Exception as e:
        logger.warning("容器 metrics 采集失败 %s: %s", container_id[:12], e)
        used_mb = 0.0
        denom_mb = pool_mb_cfg if pool_mb_cfg > 0 else max(cgroup_limit_mb, 1.0)
        pct = 0.0
    return jsonify(
        {
            "code": 0,
            "data": {
                "time": now_iso,
                "csv_memory_pct": round(pct, 2),
                "used_mb": round(used_mb, 2),
                "pool_mb": round(denom_mb, 2),
            },
        }
    )


@app.route('/api/v1/containers', methods=['GET'])
def list_containers():
    items = controller.list_containers()
    enriched = []
    for info in items:
        row = dict(info)
        row["admin_status"] = _admin_workload_status(info)
        enriched.append(row)
    return jsonify({"code": 0, "data": enriched})

@app.route('/api/v1/containers/<container_id>/training', methods=['POST'])
def trigger_training(container_id):
    with containers_lock:
        container_info = containers.get(container_id)
        if container_info:
            container_info["last_activity_ts"] = time.time()
    if not container_info:
        return jsonify({"code": 404, "message": "容器不存在"}), 404
    training_address = container_info.get('training_address')
    if not training_address:
        return jsonify({"code": 400, "message": "该容器未运行训练服务"}), 400
    return jsonify({
        "code": 0,
        "message": "训练任务已触发",
        "training_endpoint": f"http://{training_address}/v1/tasks"
    })


@app.route("/api/v1/containers/<container_id>/touch", methods=["POST"])
def touch_container(container_id):
    """手动续期空闲回收计时（例如远程证明耗时较长、尚未提交训练任务时）。"""
    ok = controller.touch_container_activity(container_id)
    if not ok:
        return jsonify({"code": 404, "message": "容器不存在"}), 404
    return jsonify({"code": 0, "message": "ok"})


@app.route("/api/v1/audit/verify-chain", methods=["GET", "POST"])
def audit_verify_chain():
    start = (request.get_json(silent=True) or {}).get("start_task_id") or request.args.get(
        "start_task_id"
    )
    report = get_audit_service().verify_chain_report(start_log_id=start or None)
    return jsonify({"code": 0, "data": report})


@app.route("/api/v1/audit/recent", methods=["GET"])
def audit_recent():
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        limit = 50
    rows = get_audit_service().list_recent_logs(limit=limit)
    return jsonify({"code": 0, "data": {"logs": rows, "count": len(rows)}})


@app.route("/api/v1/auth/login", methods=["POST"])
def auth_login():
    body = request.get_json(silent=True) or {}
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", "")).strip()
    if not username or not password:
        return jsonify({"code": 400, "message": "用户名或密码不能为空"}), 400

    db = get_session()
    try:
        user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({"code": 401, "message": "用户名或密码错误"}), 401

        account = (
            db.execute(select(Account).where(Account.user_id == user.user_id).order_by(Account.account_id.asc()))
            .scalars()
            .first()
        )
        if not account:
            return jsonify({"code": 403, "message": "用户未关联账号"}), 403

        token = f"tk-{uuid.uuid4().hex}"
        role = "admin" if username.lower() == "admin" else "user"
        _TOKENS[token] = {
            "user_id": str(user.user_id),
            "account_id": str(account.account_id),
            "role": role,
            "username": user.username,
        }
        return jsonify(
            {
                "code": 0,
                "data": {
                    "token": token,
                    "role": role,
                    "user": {
                        "id": user.user_id,
                        "username": user.username,
                        "email": user.email,
                        "phone": user.phone,
                    },
                    "default_account_id": str(account.account_id),
                },
            }
        )
    finally:
        db.close()


@app.route("/api/v1/accounts", methods=["GET"])
def accounts_list():
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401

    db = get_session()
    try:
        user_id = int(auth["user_id"])
        rows = (
            db.execute(select(Account).where(Account.user_id == user_id).order_by(Account.account_id.asc()))
            .scalars()
            .all()
        )
        items = [
            {
                "id": str(a.account_id),
                "name": a.account_name,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ]
        return jsonify({"code": 0, "data": {"items": items}})
    finally:
        db.close()


@app.route("/api/v1/notifications", methods=["GET"])
def notifications_list():
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401

    account_id = request.args.get("account_id") or auth.get("account_id")
    db = get_session()
    try:
        rows = (
            db.execute(
                select(UserNotification)
                .where(UserNotification.account_id == int(account_id))
                .order_by(UserNotification.created_at.desc())
                .limit(100)
            )
            .scalars()
            .all()
        )
        items = [
            {
                "id": n.notification_id,
                "title": n.title,
                "content": n.content,
                "time": n.created_at.isoformat() if n.created_at else None,
                "read": bool(n.is_read),
            }
            for n in rows
        ]
        return jsonify({"code": 0, "data": {"items": items}})
    finally:
        db.close()


@app.route("/api/v1/accounts/<account_id>/stats", methods=["GET"])
def account_stats(account_id):
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401

    db = get_session()
    try:
        detail_rows = (
            db.execute(
                select(TaskDetail)
                .join(Task, Task.task_id == TaskDetail.task_id)
                .where(Task.account_id == int(account_id))
            )
            .scalars()
            .all()
        )
        total = len(detail_rows)
        completed = len([x for x in detail_rows if x.status == "success"])
        running = len([x for x in detail_rows if x.status == "running"])
        pending_download = completed
        epc_memory_mb_total = sum((x.epc_memory_mb or 0) for x in detail_rows)
        return jsonify(
            {
                "code": 0,
                "data": {
                    "total": total,
                    "completed": completed,
                    "running": running,
                    "pending_download": pending_download,
                    "epc_memory_mb_total": epc_memory_mb_total,
                },
            }
        )
    finally:
        db.close()


@app.route("/api/v1/tasks", methods=["GET"])
def tasks_list():
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401

    account_id = request.args.get("account_id") or auth.get("account_id")
    status = (request.args.get("status") or "").strip()
    scene = (request.args.get("scene") or "").strip()
    start_time = _parse_iso_datetime(request.args.get("start_time", ""))
    end_time = _parse_iso_datetime(request.args.get("end_time", ""))
    limit_raw = request.args.get("limit")
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    try:
        size = int(request.args.get("size", 10))
    except ValueError:
        size = 10

    db = get_session()
    try:
        query = (
            select(Task, TaskDetail)
            .join(TaskDetail, Task.task_id == TaskDetail.task_id, isouter=True)
            .where(Task.account_id == int(account_id))
        )
        rows = db.execute(query).all()
        items = []
        for task_row, detail in rows:
            detail = detail or TaskDetail(task_id=task_row.task_id)
            created_at = detail.created_at or task_row.account.created_at
            if status and status != "all" and (detail.status or "running") != status:
                continue
            if scene:
                scenes = [x.strip() for x in scene.split(",") if x.strip()]
                if scenes and (detail.scene or "") not in scenes:
                    continue
            if start_time and created_at:
                ca = _as_naive_utc_for_compare(created_at)
                st = _as_naive_utc_for_compare(start_time)
                if ca is not None and st is not None and ca < st:
                    continue
            if end_time and created_at:
                ca = _as_naive_utc_for_compare(created_at)
                et = _as_naive_utc_for_compare(end_time)
                if ca is not None and et is not None and ca > et:
                    continue
            fixed_finished = _normalize_finished_at_for_display(detail.created_at, detail.finished_at)
            timeline = json.loads(detail.timeline_json) if detail.timeline_json else []
            for ev in timeline:
                if isinstance(ev, dict):
                    ev["time"] = _normalize_time_text_to_biz_iso(ev.get("time"))
            items.append(
                {
                    "id": task_row.task_id,
                    "name": task_row.task_name,
                    "scene": detail.scene,
                    "scene_name": _scene_name(detail.scene),
                    "algorithm": detail.algorithm,
                    "params": json.loads(detail.params_json) if detail.params_json else {},
                    "dataset": json.loads(detail.dataset_json) if detail.dataset_json else None,
                    "status": detail.status or "running",
                    "created_at": _to_biz_iso(detail.created_at),
                    "finished_at": _to_biz_iso(fixed_finished),
                    "timeline": timeline,
                    "result_files": json.loads(detail.result_files_json) if detail.result_files_json else [],
                    "epc_memory_mb": detail.epc_memory_mb,
                    "node_name": detail.node_name,
                    "container_name": detail.container_name,
                }
            )
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        total = len(items)
        if limit_raw:
            lim = max(1, int(limit_raw))
            return jsonify({"code": 0, "data": {"items": items[:lim], "total": total}})
        p = max(1, page)
        s = max(1, min(size, 100))
        start_idx = (p - 1) * s
        paged = items[start_idx : start_idx + s]
        return jsonify({"code": 0, "data": {"items": paged, "total": total}})
    finally:
        db.close()


@app.route("/api/v1/tasks/<task_id>", methods=["GET"])
def task_detail(task_id):
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401

    db = get_session()
    try:
        row = db.execute(
            select(Task, TaskDetail)
            .join(TaskDetail, Task.task_id == TaskDetail.task_id, isouter=True)
            .where(Task.task_id == task_id)
        ).first()
        if not row:
            return jsonify({"code": 404, "message": "任务不存在"}), 404
        task_row, detail = row
        if int(task_row.account_id) != int(auth.get("account_id") or 0):
            return jsonify({"code": 403, "message": "无权查看该任务"}), 403
        detail = detail or TaskDetail(task_id=task_row.task_id)
        wiz_base = os.path.join(controller._controller_container_data_mount_point, "wizard", task_id)
        artifacts = {
            "attestation_report": os.path.isfile(os.path.join(wiz_base, "attestation_report.json")),
            "key_material": os.path.isfile(os.path.join(wiz_base, "key_material.json")),
        }
        fixed_finished = _normalize_finished_at_for_display(detail.created_at, detail.finished_at)
        timeline = json.loads(detail.timeline_json) if detail.timeline_json else []
        for ev in timeline:
            if isinstance(ev, dict):
                ev["time"] = _normalize_time_text_to_biz_iso(ev.get("time"))
        item = {
            "id": task_row.task_id,
            "name": task_row.task_name,
            "scene": detail.scene,
            "scene_name": _scene_name(detail.scene),
            "algorithm": detail.algorithm,
            "params": json.loads(detail.params_json) if detail.params_json else {},
            "dataset": json.loads(detail.dataset_json) if detail.dataset_json else None,
            "status": detail.status or "running",
            "created_at": _to_biz_iso(detail.created_at),
            "finished_at": _to_biz_iso(fixed_finished),
            "timeline": timeline,
            "result_files": json.loads(detail.result_files_json) if detail.result_files_json else [],
            "epc_memory_mb": detail.epc_memory_mb,
            "node_name": detail.node_name,
            "container_name": detail.container_name,
            "artifacts": artifacts,
        }
        return jsonify({"code": 0, "data": item})
    finally:
        db.close()


@app.route("/api/v1/tasks", methods=["POST"])
def task_create():
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401

    body = request.get_json(silent=True) or {}
    account_id = int(body.get("account_id") or auth.get("account_id"))
    task_name = str(body.get("name", "")).strip()
    if not task_name:
        return jsonify({"code": 400, "message": "任务名称不能为空"}), 400

    db = get_session()
    try:
        task_id = f"t-{uuid.uuid4().hex[:8]}"
        task = Task(task_id=task_id, account_id=account_id, task_name=task_name)
        detail = TaskDetail(
            task_id=task_id,
            scene=body.get("scene"),
            algorithm=body.get("algorithm"),
            params_json=json.dumps(body.get("params") or {}, ensure_ascii=False),
            dataset_json=json.dumps(body.get("dataset") or {}, ensure_ascii=False),
            status=body.get("status") or "running",
            timeline_json=json.dumps(body.get("timeline") or [], ensure_ascii=False),
            result_files_json=json.dumps(body.get("result_files") or [], ensure_ascii=False),
            epc_memory_mb=int(body.get("epc_memory_mb") or 0),
            node_name=body.get("node_name"),
            container_name=body.get("container_name"),
            finished_at=_parse_iso_datetime(body.get("finished_at", "")),
        )
        db.add(task)
        db.add(detail)
        db.commit()
        # 覆盖中间件默认 request_id，确保该请求审计落真实业务 task_id
        AuditContext.set_task_id(task_id)
        AuditContext.set_task_name(task_name[:255])
        _record_business_audit_event(
            operation_type="任务创建",
            object_type="task",
            object_id=task_id,
            actor=auth.get("username", "unknown"),
            result="success",
            task_id=task_id,
            detail_json={
                "task_id": task_id,
                "task_name": task_name,
                "account_id": str(account_id),
                "scene": body.get("scene"),
                "algorithm": body.get("algorithm"),
                "node_name": body.get("node_name") or "-",
                "container_name": body.get("container_name") or "-",
            },
        )
        return jsonify({"code": 0, "data": {"task_id": task_id}})
    except Exception as e:
        db.rollback()
        return jsonify({"code": 500, "message": f"任务创建失败: {e}"}), 500
    finally:
        db.close()


@app.route("/api/v1/tasks/<task_id>/result", methods=["GET"])
def task_result_download(task_id):
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401
    file_type = request.args.get("file_type", "model")
    account_id = int(auth.get("account_id") or 0)

    db = get_session()
    try:
        task_row = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
        if not task_row:
            return jsonify({"code": 404, "message": "任务不存在"}), 404
        if int(task_row.account_id) != account_id:
            return jsonify({"code": 403, "message": "无权下载该任务"}), 403
    finally:
        db.close()

    wiz_dir = os.path.join(controller._controller_container_data_mount_point, "wizard", task_id)

    def _audit_dl(extra=None):
        detail_json = {"task_id": task_id, "file_type": file_type}
        if extra:
            detail_json.update(extra)
        _record_business_audit_event(
            operation_type="结果下载",
            object_type="task",
            object_id=task_id,
            actor=auth.get("username", "unknown"),
            result="success",
            task_id=task_id,
            detail_json=detail_json,
        )

    if file_type == "attestation":
        p = os.path.join(wiz_dir, "attestation_report.json")
        if os.path.isfile(p):
            with open(p, "rb") as f:
                raw = f.read()
            _audit_dl({"source": "attestation_report"})
            return Response(
                raw,
                mimetype="application/json; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="attestation_{task_id}.json"'},
            )
        return jsonify({"code": 404, "message": "未找到远程证明材料，请在本环境重新完成向导「远程证明」"}), 404

    if file_type == "key":
        p = os.path.join(wiz_dir, "key_material.json")
        if os.path.isfile(p):
            with open(p, "rb") as f:
                raw = f.read()
            _audit_dl({"source": "key_material"})
            return Response(
                raw,
                mimetype="application/json; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="key_material_{task_id}.json"'},
            )
        return jsonify({"code": 404, "message": "未找到密钥材料，请重新完成向导「密钥注入」步骤"}), 404

    # 密态模型：与 /api/v1/wizard/model-download 一致
    if file_type == "model" and account_id:
        local_blob = wizpl.wizard_load_model_blob(task_id, account_id)
        if local_blob:
            raw, _meta = local_blob
            _audit_dl({"source": "wizard_model_local"})
            return Response(
                raw,
                mimetype="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="model_{task_id}.enc"'},
            )
        try:
            hex_model, _meta = wizpl.wizard_fetch_model_hex(task_id, account_id)
            if hex_model:
                raw = bytes.fromhex(hex_model)
                _audit_dl({"source": "wizard_model"})
                return Response(
                    raw,
                    mimetype="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="model_{task_id}.enc"'},
                )
        except Exception as ex:
            logger.info("task result model: 非向导内存态或训练容器已回收: %s", ex)
        return jsonify({"code": 404, "message": "未找到可下载模型，请确认训练已完成且模型文件已生成"}), 404

    return jsonify({"code": 400, "message": f"不支持的 file_type: {file_type}"}), 400


def _as_naive_utc_for_compare(dt: Optional[datetime]) -> Optional[datetime]:
    """与 MySQL 读出的 naive datetime 比较时，将带时区的 ISO 时间统一为 UTC naive。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _normalize_finished_at_for_display(created_at: Optional[datetime], finished_at: Optional[datetime]) -> Optional[datetime]:
    """
    兼容历史数据：容器内按 UTC 写入 finished_at、而 created_at 按本地时区写入时，
    前端会看到“完成时间比创建时间早约 8 小时”。此处在返回前做显示纠偏。
    """
    if not finished_at:
        return finished_at
    if not created_at:
        return finished_at
    try:
        if finished_at < created_at:
            diff = created_at - finished_at
            # 典型 8 小时时差（给一点容忍区间）
            if timedelta(hours=7) <= diff <= timedelta(hours=9):
                return finished_at + timedelta(hours=8)
    except Exception:
        return finished_at
    return finished_at


def _parse_iso_datetime(value: str):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


_BIZ_TZ = timezone(timedelta(hours=8))


def _to_biz_iso(dt: Optional[datetime]) -> Optional[str]:
    """
    对外返回无时区后缀的 ISO 字符串。
    MySQL/SQLAlchemy 读出的 naive datetime 在本项目中按「业务墙钟时间」存储（与 wizard 一致），
    不再做 +8 偏移，避免与用户已校正的前端显示重复加时。
    仅当 datetime 本身带 tzinfo 时才换算到东八区墙钟。
    """
    if not dt:
        return None
    try:
        if dt.tzinfo is None:
            return dt.replace(microsecond=0).isoformat(timespec="seconds")
        return dt.astimezone(_BIZ_TZ).replace(tzinfo=None).isoformat(timespec="seconds")
    except Exception:
        return dt.isoformat() if isinstance(dt, datetime) else str(dt)


def _normalize_time_text_to_biz_iso(text: Optional[str]) -> Optional[str]:
    """时间线字符串：无 Z 视为业务墙钟；带 Z 视为 UTC 再转东八区墙钟。"""
    if not text:
        return text
    raw = str(text).strip()
    if not raw:
        return raw
    parsed = _parse_iso_datetime(raw)
    if not parsed:
        return raw
    if raw.endswith("Z") or parsed.tzinfo is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(_BIZ_TZ).replace(tzinfo=None).isoformat(timespec="seconds")
    return parsed.replace(microsecond=0).isoformat(timespec="seconds")


def _display_tee_node_name(raw: Optional[str]) -> str:
    """管理端/审计展示用节点名：与机密容器列表一致，统一为 TEE节点A。"""
    s = (raw or "").strip()
    if not s or s.lower() in ("docker-host", "teea", "-"):
        return "TEE节点A"
    return s


def _step_labels_from_event_type(event_type: str) -> List[str]:
    s = str(event_type or "")
    # 用户要求：任务审计从“创建容器之后”开始，不展示“任务名称/任务创建”
    if "任务创建" in s or "任务已创建" in s:
        return []
    if "容器已创建" in s or "创建容器" in s:
        return ["创建容器"]
    if "远程证明" in s:
        return ["远程证明"]
    if "数据与算法" in s:
        return ["数据与算法"]
    if "DEK" in s and "密钥注入" in s:
        return ["DEK加密", "密钥注入"]
    if "DEK" in s or "数据加密" in s:
        return ["DEK加密"]
    if "密钥注入" in s:
        return ["密钥注入"]
    if "开始训练" in s:
        return ["开始训练"]
    if "训练失败" in s:
        return ["开始训练"]
    if "训练已完成" in s or "训练完成" in s:
        return ["开始训练"]
    if "结果下载" in s or "model-download" in s:
        return ["完成下载"]
    return []


def _timeline_items_from_task_detail(
    *,
    task_id: str,
    detail_row: Optional[TaskDetail],
    actor: str,
) -> List[dict]:
    if not detail_row or not detail_row.timeline_json:
        return []
    try:
        tl = json.loads(detail_row.timeline_json)
    except Exception:
        tl = []
    if not isinstance(tl, list):
        return []

    real_container_name = (detail_row.container_name if detail_row else None) or "-"
    real_node_name = _display_tee_node_name(detail_row.node_name if detail_row else None)
    items: List[dict] = []
    started = False
    for i, ev in enumerate(tl):
        if not isinstance(ev, dict):
            continue
        title = str(ev.get("title") or "")
        labels = _step_labels_from_event_type(title)
        if not labels:
            continue
        if "创建容器" in labels:
            started = True
        if not started:
            continue
        time_text = _normalize_time_text_to_biz_iso(ev.get("time"))
        result_text = "失败" if "失败" in title else "成功"
        result_raw = "fail" if result_text == "失败" else "success"
        for j, lbl in enumerate(labels):
            items.append(
                {
                    "event_id": f"wizard-{task_id}-{i}-{j}",
                    "time": time_text,
                    "type": lbl,
                    "result": result_text,
                    "result_raw": result_raw,
                    "node_name": real_node_name,
                    "container_name": real_container_name,
                    "task_id": task_id,
                    "actor": actor,
                }
            )
    return items


@app.route("/api/v1/admin/system-config", methods=["GET"])
def admin_get_system_config():
    auth = _require_admin_auth()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401
    if auth.get("forbidden") == "1":
        return jsonify({"code": 403, "message": "仅管理员可访问"}), 403
    db = get_session()
    try:
        cfg = _load_admin_system_config(db)
        return jsonify({"code": 0, "data": cfg})
    finally:
        db.close()


@app.route("/api/v1/admin/system-config", methods=["PATCH"])
def admin_patch_system_config():
    auth = _require_admin_auth()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401
    if auth.get("forbidden") == "1":
        return jsonify({"code": 403, "message": "仅管理员可访问"}), 403
    body = request.get_json(silent=True) or {}
    db = get_session()
    try:
        try:
            cfg = _save_admin_system_config(db, body, updated_by=str(auth.get("username") or "admin"))
        except ValueError as ve:
            db.rollback()
            return jsonify({"code": 400, "message": str(ve)}), 400
        return jsonify({"code": 0, "data": cfg})
    finally:
        db.close()


@app.route("/api/v1/admin/audit/logs", methods=["DELETE"])
def admin_clear_audit_logs():
    auth = _require_admin_auth()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401
    if auth.get("forbidden") == "1":
        return jsonify({"code": 403, "message": "仅管理员可访问"}), 403
    body = request.get_json(silent=True) or {}
    keep_days = body.get("keep_days")
    db = get_session()
    try:
        deleted_task_timeline = 0
        deleted_task_events = 0
        deleted_admin_events = 0
        deleted_chain_logs = 0

        if keep_days is not None:
            try:
                keep_days = int(keep_days)
            except (TypeError, ValueError):
                return jsonify({"code": 400, "message": "keep_days 必须为整数"}), 400
            if keep_days < 0:
                return jsonify({"code": 400, "message": "keep_days 不能小于 0"}), 400
            cutoff = datetime.now() - timedelta(days=keep_days)
            # task_details 无独立 event_time，这里按 created_at 近似清理其时间线
            stale_details = (
                db.execute(select(TaskDetail).where(TaskDetail.created_at < cutoff)).scalars().all()
            )
            for row in stale_details:
                if row.timeline_json:
                    row.timeline_json = None
                    deleted_task_timeline += 1
            deleted_task_events = db.execute(
                delete(TaskAuditEvent).where(TaskAuditEvent.event_time < cutoff)
            ).rowcount or 0
            deleted_admin_events = db.execute(
                delete(AdminAuditEvent).where(AdminAuditEvent.event_time < cutoff)
            ).rowcount or 0
            deleted_chain_logs = db.execute(
                delete(AuditLog).where(AuditLog.event_time < cutoff)
            ).rowcount or 0
        else:
            rows = db.execute(select(TaskDetail).where(TaskDetail.timeline_json.is_not(None))).scalars().all()
            for row in rows:
                row.timeline_json = None
                deleted_task_timeline += 1
            deleted_task_events = db.execute(delete(TaskAuditEvent)).rowcount or 0
            deleted_admin_events = db.execute(delete(AdminAuditEvent)).rowcount or 0
            deleted_chain_logs = db.execute(delete(AuditLog)).rowcount or 0

        db.commit()
        return jsonify(
            {
                "code": 0,
                "data": {
                    "cleared": {
                        "task_detail_timeline_rows": int(deleted_task_timeline),
                        "task_audit_events": int(deleted_task_events),
                        "admin_audit_events": int(deleted_admin_events),
                        "audit_log_chain_rows": int(deleted_chain_logs),
                    }
                },
            }
        )
    except Exception as e:
        db.rollback()
        logger.exception("clear audit logs failed")
        return jsonify({"code": 500, "message": f"清理失败: {e}"}), 500
    finally:
        db.close()


@app.route("/api/v1/audit/logs", methods=["GET"])
def audit_logs():
    """前端审计日志页查询接口：汇总所有用户任务的“创建容器之后”步骤审计。"""
    start_time = _parse_iso_datetime(request.args.get("start_time", ""))
    end_time = _parse_iso_datetime(request.args.get("end_time", ""))
    types_raw = request.args.get("types", "").strip()
    results_raw = request.args.get("results", "").strip()
    object_id_like = request.args.get("object_id_like", "").strip()
    task_id = request.args.get("task_id", "").strip() or None
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    try:
        size = int(request.args.get("size", 10))
    except ValueError:
        size = 10

    types = [x.strip() for x in types_raw.split(",") if x.strip()] if types_raw else []
    results = [x.strip() for x in results_raw.split(",") if x.strip()] if results_raw else []

    db = get_session()
    try:
        # 若配置了审计保留天数，则查询窗口自动受其限制（前端仍可额外传更窄时间）
        cfg = _load_admin_system_config(db)
        try:
            retention_days = int(cfg.get("audit_retention_days") or 30)
        except (TypeError, ValueError):
            retention_days = 30
        if retention_days > 0:
            retention_start = datetime.now() - timedelta(days=retention_days)
            if (start_time is None) or (start_time < retention_start):
                start_time = retention_start

        rows = (
            db.execute(
                select(Task, TaskDetail, Account)
                .join(TaskDetail, Task.task_id == TaskDetail.task_id, isouter=True)
                .join(Account, Task.account_id == Account.account_id, isouter=True)
            )
            .all()
        )
        all_items: List[dict] = []
        for task_row, detail_row, acc in rows:
            actor = (acc.account_name if acc else None) or f"account-{task_row.account_id}"
            for ev in _timeline_items_from_task_detail(
                task_id=task_row.task_id,
                detail_row=detail_row,
                actor=actor,
            ):
                all_items.append(
                    {
                        "id": ev["event_id"],
                        "time": ev["time"],
                        "operation_type": ev["type"],
                        "object_type": "task",
                        "object_id": task_row.task_id,
                        "actor": actor,
                        "result": ev["result_raw"],
                        "detail_json": json.dumps(
                            {
                                "task_id": task_row.task_id,
                                "task_name": task_row.task_name,
                                "node_name": ev["node_name"],
                                "container_name": ev["container_name"],
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    }
                )

        def _match_time(item: dict) -> bool:
            t = _parse_iso_datetime(item.get("time") or "")
            t_cmp = _as_naive_utc_for_compare(t)
            st_cmp = _as_naive_utc_for_compare(start_time)
            et_cmp = _as_naive_utc_for_compare(end_time)
            if st_cmp and t_cmp and t_cmp < st_cmp:
                return False
            if et_cmp and t_cmp and t_cmp > et_cmp:
                return False
            return True

        filtered = [x for x in all_items if _match_time(x)]
        if types:
            tset = set(types)
            filtered = [x for x in filtered if x.get("operation_type") in tset]
        if results:
            rset = {str(r).strip().lower() for r in results}
            filtered = [x for x in filtered if str(x.get("result") or "").lower() in rset]
        if object_id_like:
            key = object_id_like.lower()
            filtered = [x for x in filtered if key in str(x.get("object_id") or "").lower()]
        if task_id:
            filtered = [x for x in filtered if str(x.get("object_id") or "") == task_id]

        filtered.sort(key=lambda x: (x.get("time") or "", x.get("id") or ""), reverse=True)
        total = len(filtered)
        p = max(1, page)
        s = max(1, min(size, 100))
        start_idx = (p - 1) * s
        part = filtered[start_idx : start_idx + s]
        return jsonify({"code": 0, "data": {"items": part, "total": total}})
    finally:
        db.close()


@app.route("/api/v1/wizard/init", methods=["POST"])
def wizard_route_init():
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"code": 400, "message": "任务名称不能为空"}), 400
    try:
        account_id = int(body.get("account_id") or auth.get("account_id"))
    except (TypeError, ValueError):
        return jsonify({"code": 400, "message": "account_id 无效"}), 400
    if account_id != int(auth["account_id"]):
        return jsonify({"code": 403, "message": "账号不匹配"}), 403
    scene = str(body.get("scene") or "fraud").strip()
    try:
        tid = wizpl.wizard_init(account_id, name, scene)
        _record_business_audit_event(
            operation_type="任务创建",
            object_type="task",
            object_id=tid,
            actor=auth.get("username", "unknown"),
            result="success",
            task_id=tid,
            detail_json={
                "task_id": tid,
                "task_name": name,
                "account_id": str(account_id),
                "scene": scene,
            },
        )
        return jsonify({"code": 0, "data": {"task_id": tid}})
    except Exception as e:
        logger.error("wizard init: %s", e)
        return jsonify({"code": 500, "message": str(e)}), 500


@app.route("/api/v1/wizard/container", methods=["POST"])
def wizard_route_container():
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401
    body = request.get_json(silent=True) or {}
    task_id = str(body.get("task_id", "")).strip()
    if not task_id:
        return jsonify({"code": 400, "message": "缺少 task_id"}), 400
    try:
        account_id = int(auth["account_id"])
        resources = body.get("resources")
        data = wizpl.wizard_create_container(controller, task_id, account_id, resources)
        return jsonify({"code": 0, "data": data})
    except PermissionError as e:
        return jsonify({"code": 403, "message": str(e)}), 403
    except Exception as e:
        logger.exception("wizard container")
        return jsonify({"code": 500, "message": str(e)}), 500


@app.route("/api/v1/wizard/attest", methods=["POST"])
def wizard_route_attest():
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401
    body = request.get_json(silent=True) or {}
    task_id = str(body.get("task_id", "")).strip()
    if not task_id:
        return jsonify({"code": 400, "message": "缺少 task_id"}), 400
    try:
        account_id = int(auth["account_id"])
        data = wizpl.wizard_attest(task_id, account_id)
        return jsonify({"code": 0, "data": data})
    except PermissionError as e:
        return jsonify({"code": 403, "message": str(e)}), 403
    except Exception as e:
        logger.exception("wizard attest")
        return jsonify({"code": 500, "message": str(e)}), 500


@app.route("/api/v1/wizard/upload", methods=["POST"])
def wizard_route_upload():
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401
    task_id = str(request.form.get("task_id", "")).strip()
    if not task_id:
        return jsonify({"code": 400, "message": "缺少 task_id"}), 400
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"code": 400, "message": "请上传 CSV 文件"}), 400
    algorithm = str(request.form.get("algorithm") or "XGBoost 分类")
    try:
        params = json.loads(request.form.get("params") or "{}")
    except json.JSONDecodeError:
        return jsonify({"code": 400, "message": "params 需为 JSON"}), 400
    raw = f.read()
    if len(raw) < 10:
        return jsonify({"code": 400, "message": "文件过小"}), 400
    # 必须写 controller 容器内挂载点（如 /data），勿用 _get_host_bind_source 的宿主机路径：
    # 后者在容器进程命名空间内往往不可写或写到错误位置，导致训练容器挂载的 ./data 下无 .enc 文件。
    data_dir_in_container = controller._controller_container_data_mount_point
    try:
        account_id = int(auth["account_id"])
        data = wizpl.wizard_upload_csv(data_dir_in_container, task_id, account_id, f.filename, raw, algorithm, params)
        return jsonify({"code": 0, "data": data})
    except PermissionError as e:
        return jsonify({"code": 403, "message": str(e)}), 403
    except Exception as e:
        logger.exception("wizard upload")
        return jsonify({"code": 500, "message": str(e)}), 500


@app.route("/api/v1/wizard/protect-data", methods=["POST"])
def wizard_route_protect():
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401
    body = request.get_json(silent=True) or {}
    task_id = str(body.get("task_id", "")).strip()
    if not task_id:
        return jsonify({"code": 400, "message": "缺少 task_id"}), 400
    try:
        account_id = int(auth["account_id"])
        data = wizpl.wizard_inject_and_encrypt(task_id, account_id)
        return jsonify({"code": 0, "data": data})
    except PermissionError as e:
        return jsonify({"code": 403, "message": str(e)}), 403
    except Exception as e:
        logger.exception("wizard protect")
        return jsonify({"code": 500, "message": str(e)}), 500


@app.route("/api/v1/wizard/train", methods=["POST"])
def wizard_route_train():
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401
    body = request.get_json(silent=True) or {}
    task_id = str(body.get("task_id", "")).strip()
    if not task_id:
        return jsonify({"code": 400, "message": "缺少 task_id"}), 400
    try:
        account_id = int(auth["account_id"])
        wizpl.wizard_start_train_thread(controller, task_id, account_id)
        return jsonify({"code": 0, "data": {"accepted": True}})
    except PermissionError as e:
        return jsonify({"code": 403, "message": str(e)}), 403
    except RuntimeError as e:
        return jsonify({"code": 409, "message": str(e)}), 409
    except Exception as e:
        logger.exception("wizard train")
        return jsonify({"code": 500, "message": str(e)}), 500


@app.route("/api/v1/wizard/train-status", methods=["GET"])
def wizard_route_train_status():
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401
    task_id = str(request.args.get("task_id", "")).strip()
    if not task_id:
        return jsonify({"code": 400, "message": "缺少 task_id"}), 400
    try:
        account_id = int(auth["account_id"])
        data = wizpl.wizard_train_status(task_id, account_id)
        return jsonify({"code": 0, "data": data})
    except PermissionError as e:
        return jsonify({"code": 403, "message": str(e)}), 403
    except Exception as e:
        logger.error("wizard train-status: %s", e)
        return jsonify({"code": 500, "message": str(e)}), 500


@app.route("/api/v1/wizard/model-download", methods=["GET"])
def wizard_route_model_download():
    auth = _parse_auth_token()
    if not auth:
        return jsonify({"code": 401, "message": "未授权"}), 401
    task_id = str(request.args.get("task_id", "")).strip()
    if not task_id:
        return jsonify({"code": 400, "message": "缺少 task_id"}), 400
    try:
        account_id = int(auth["account_id"])
        local_blob = wizpl.wizard_load_model_blob(task_id, account_id)
        if local_blob:
            raw, metadata = local_blob
        else:
            hex_model, metadata = wizpl.wizard_fetch_model_hex(task_id, account_id)
            raw = bytes.fromhex(hex_model)
        _record_business_audit_event(
            operation_type="结果下载",
            object_type="task",
            object_id=task_id,
            actor=auth.get("username", "unknown"),
            result="success",
            task_id=task_id,
            detail_json={"task_id": task_id, "file_type": "model", "source": "wizard_model_download"},
        )
        return Response(
            raw,
            mimetype="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="model_{task_id}.enc"',
                "X-Model-Metadata": base64.b64encode(
                    json.dumps(metadata, ensure_ascii=False).encode("utf-8")
                ).decode("ascii")[:1024],
            },
        )
    except PermissionError as e:
        return jsonify({"code": 403, "message": str(e)}), 403
    except Exception as e:
        logger.exception("wizard model-download")
        return jsonify({"code": 500, "message": str(e)}), 500


@app.route("/api/v1/tasks/<task_id>/audit", methods=["GET"])
def task_audit(task_id):
    """任务详情审计摘要：优先读取业务任务审计事件。"""
    try:
        limit = int(request.args.get("limit", 200))
    except ValueError:
        limit = 200
    db = get_session()
    try:
        detail_row = db.execute(select(TaskDetail).where(TaskDetail.task_id == task_id)).scalar_one_or_none()

        # 向导任务优先：用 timeline_json 生成步骤事件（从“创建容器”开始）
        items = _timeline_items_from_task_detail(task_id=task_id, detail_row=detail_row, actor="user")
        if items:
            for x in items:
                x.pop("result_raw", None)
                x.pop("task_id", None)
                x.pop("actor", None)
            return jsonify({"code": 0, "data": {"items": items, "count": len(items)}})

        real_container_name = (detail_row.container_name if detail_row else None) or "-"
        real_node_name = _display_tee_node_name(detail_row.node_name if detail_row else None)

        rows = (
            db.execute(
                select(TaskAuditEvent)
                .where(TaskAuditEvent.task_id == task_id)
                .order_by(TaskAuditEvent.event_time.asc())
                .limit(max(1, min(limit, 500)))
            )
            .scalars()
            .all()
        )
        if rows:
            items = []
            for r in rows:
                labels = _step_labels_from_event_type(r.event_type)
                if not labels:
                    continue
                for idx, lbl in enumerate(labels):
                    items.append(
                        {
                            "event_id": f"{r.event_id}-{idx}",
                            "time": _to_biz_iso(r.event_time),
                            "type": lbl,
                            "result": "成功" if r.result == "success" else "失败",
                            "node_name": real_node_name,
                            "container_name": real_container_name,
                        }
                    )
            return jsonify({"code": 0, "data": {"items": items, "count": len(items)}})
    finally:
        db.close()

    # 兼容兜底：若尚无业务事件，回退到技术审计
    items = get_audit_service().get_task_audit_timeline(task_id, limit=limit)
    return jsonify({"code": 0, "data": {"items": items, "count": len(items)}})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)