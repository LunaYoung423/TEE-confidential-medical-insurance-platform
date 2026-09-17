"""
用户向导「8 步」背后的真实机密计算编排（在 controller 进程内执行）。

浏览器无法访问宿主机上映射的 training/attestation 端口，因此证明、注入、训练
均由本模块通过 Docker 网络可达的地址发起 HTTP 请求完成。
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import importlib.util
import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy import select
from werkzeug.utils import secure_filename

from module3.audit.models import Task, TaskDetail, get_session

logger = logging.getLogger(__name__)

WIZARD_LOCK = threading.RLock()
WIZARD_STATE: Dict[str, Dict[str, Any]] = {}

_ic_script_mod = None
_WizardIntegratedClientCls = None


def _biz_now_naive() -> datetime:
    """
    统一业务落库时间为北京时间（naive），避免容器默认 UTC 导致 finished_at 早 8 小时。
    """
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)


def _integrated_client_script_path() -> str:
    """
    解析 scripts/integrated_client.py 路径。
    Docker 中仅挂载 /app/wizard_pipeline.py 时，dirname/.. 会变成文件系统根目录，
    误指向 /scripts/...；因此向上查找含 scripts 的目录，并支持环境变量覆盖。
    """
    env = (os.environ.get("INTEGRATED_CLIENT_SCRIPT") or "").strip()
    if env and os.path.isfile(env):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    cur = here
    for _ in range(8):
        cand = os.path.join(cur, "scripts", "integrated_client.py")
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    # compose 挂载 ./scripts -> /app/scripts
    docker_cand = "/app/scripts/integrated_client.py"
    if os.path.isfile(docker_cand):
        return docker_cand
    raise FileNotFoundError(
        "找不到 scripts/integrated_client.py。请在 docker-compose 的 controller 服务增加卷 "
        "'./scripts:/app/scripts'，或设置环境变量 INTEGRATED_CLIENT_SCRIPT 为脚本的绝对路径。"
    )


def _load_integrated_client_module():
    """动态加载 scripts/integrated_client.py（不修改该文件）。"""
    global _ic_script_mod
    if _ic_script_mod is not None:
        return _ic_script_mod
    path = _integrated_client_script_path()
    spec = importlib.util.spec_from_file_location("_platform_integrated_client", path)
    mod = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError("无法加载 integrated_client 模块")
    spec.loader.exec_module(mod)
    _ic_script_mod = mod
    return _ic_script_mod


def _wizard_integrated_client_class():
    """
    返回 scripts/integrated_client.py 中的 IntegratedClient 类（证明 / 加密 / 训练 HTTP 仍走脚本逻辑）。
    创建训练容器由 wizard_create_container 直接调控制器 EnvironmentController，避免同进程嵌套 HTTP 死等超时。
    """
    global _WizardIntegratedClientCls
    if _WizardIntegratedClientCls is not None:
        return _WizardIntegratedClientCls
    mod = _load_integrated_client_module()
    _WizardIntegratedClientCls = mod.IntegratedClient
    return _WizardIntegratedClientCls


def _make_wizard_ic():
    """与 integrated_client 一致的控制器/证明服务 URL（在 controller 容器内请设 CONTROLLER_URL=http://127.0.0.1:8080）。"""
    cls = _wizard_integrated_client_class()
    ctrl = os.environ.get("CONTROLLER_URL", "http://127.0.0.1:8080").rstrip("/")
    verify = (
        os.environ.get("VERIFY_URL")
        or os.environ.get("INTERNAL_VERIFY_URL")
        or os.environ.get("ATTESTATION_SERVER", "http://attestation-service:8081")
    )
    verify = str(verify).rstrip("/")
    return cls(controller_url=ctrl, verify_url=verify)


def _norm_resources_for_ic(res: Optional[dict]) -> dict:
    r = dict(res or {"cpu": 2, "memory": "4096M"})
    cpu = int(r.get("cpu", 2))
    mem = r.get("memory", "4096M")
    if isinstance(mem, (int, float)):
        mem = f"{int(mem)}M"
    elif isinstance(mem, str) and mem.lower().endswith("g"):
        try:
            g = float(mem.lower().replace("g", "").strip())
            mem = f"{int(g * 1024)}M"
        except ValueError:
            mem = "4096M"
    return {"cpu": cpu, "memory": mem}


def _http_base_from_localhost(addr: str) -> str:
    """与 module3.scheduler.service._localhost_addr_to_http_base 一致。"""
    use_local = os.environ.get("SCHEDULER_DYNAMIC_USE_LOCALHOST", "").lower() in ("1", "true", "yes")
    if not addr:
        return ""
    if addr.startswith("http://") or addr.startswith("https://"):
        return addr.rstrip("/")
    host, sep, port = addr.partition(":")
    if not sep or not port:
        return f"http://{addr}"
    if use_local and host.lower() in ("localhost", "127.0.0.1"):
        return f"http://{host}:{port}"
    if host.lower() in ("localhost", "127.0.0.1"):
        # compose 建议 extra_hosts: host.docker.internal:host-gateway；仅老环境可设 HOST_GATEWAY_IP=172.17.0.1
        gw = os.environ.get("HOST_GATEWAY_IP", "host.docker.internal")
        return f"http://{gw}:{port}"
    return f"http://{addr}"


def _dynamic_service_host_port_for_container(addr: str) -> str:
    """
    Docker API 返回的动态端口形如 localhost:32770，端口实际发布在宿主机上。
    在 controller 容器内必须用宿主机网关（或 host.docker.internal）访问，否则 Connection refused。
    IntegratedClient / ConfidentialComputeClient 使用 host:port 拼 URL，故返回不含 scheme 的 host:port。
    """
    if not (addr or "").strip():
        return addr
    s = str(addr).strip()
    base = _http_base_from_localhost(s)
    if base.startswith("http://"):
        return base[len("http://") :].rstrip("/")
    if base.startswith("https://"):
        return base[len("https://") :].rstrip("/")
    return s


def _attest_agent_ready_seconds() -> float:
    try:
        return float(os.environ.get("ATTEST_AGENT_READY_SECONDS", "60") or "60")
    except ValueError:
        return 60.0


def _attest_agent_health_timeout() -> float:
    try:
        return float(os.environ.get("ATTEST_AGENT_HEALTH_TIMEOUT", "10") or "10")
    except ValueError:
        return 10.0


def _wait_attestation_agent_ready(host_port: str) -> None:
    """
    动态容器启动命令里 attestation_agent 与 uvicorn 有先后，避免立刻 POST /api/v1/attest 收到 RST。
    仅轮询 HTTP /api/v1/health，不改变证明逻辑，也不依赖 CSV 模拟。
    """
    hp = (host_port or "").strip()
    if not hp:
        return
    url = f"http://{hp}/api/v1/health"
    deadline = time.time() + max(5.0, _attest_agent_ready_seconds())
    interval = 0.5
    last_err: Optional[str] = None
    health_timeout = max(3.0, min(_attest_agent_health_timeout(), 60.0))
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=health_timeout)
            if r.status_code == 200:
                logger.info("证明代理已就绪: %s", url)
                return
            last_err = f"HTTP {r.status_code}"
        except requests.exceptions.RequestException as ex:
            last_err = str(ex)
        time.sleep(interval)
    raise RuntimeError(f"证明代理在 {_attest_agent_ready_seconds():.0f}s 内未就绪: {hp}（{last_err}）")


def _wizard_data_root() -> str:
    """controller 容器内数据根目录（与 docker-compose ./data:/data 对应）。"""
    r = (os.environ.get("WIZARD_DATA_ROOT") or os.environ.get("CONTROLLER_DATA_MOUNT") or "/data").strip().rstrip("/")
    return r or "/data"


def _wizard_task_dir_abs(root: str, task_id: str) -> str:
    return os.path.join(root, "wizard", task_id)


def _json_safe_dump(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


def _tail_dynamic_container_logs(container_id: str, tail: int = 120) -> str:
    """
    读取动态训练容器最近日志，辅助定位 /v1/tasks 500 根因。
    """
    cid = str(container_id or "").strip()
    if not cid:
        return ""
    try:
        import docker  # 延迟导入，避免无 Docker 运行环境影响主流程

        cli = docker.from_env()
        c = cli.containers.get(cid)
        raw = c.logs(tail=tail)
        txt = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
        return txt.strip()
    except Exception as ex:
        logger.warning("读取训练容器日志失败 cid=%s: %s", cid, ex)
        return ""


def map_algorithm_ui(ui: str) -> str:
    """向导中文选项 → module2 get_algorithm 使用的标识。"""
    s = (ui or "").strip()
    if s == "逻辑回归":
        return "logistic_regression"
    if s in ("XGBoost 回归", "XGBoost（回归）"):
        return "xgboost"
    # 旧版「XGBoost」、新版「XGBoost 分类」及文档里常见的 xgboost-classify 写法
    if s in (
        "XGBoost",
        "XGBoost 分类",
        "XGBoost（分类）",
        "xgboost_classifier",
        "xgboost-classify",
        "xgboost-classifier",
        "xgoost-classify",
        "xgoost-classifier",
    ):
        return "xgboost_classifier"
    return "xgboost_classifier"


def map_params_for_backend(algorithm_backend: str, params: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(params or {})
    if algorithm_backend in ("xgboost_classifier", "xgboost"):
        out = {
            "n_estimators": int(p.get("iterations", p.get("n_estimators", 100))),
            "max_depth": int(p.get("max_depth", 6)),
            "learning_rate": float(p.get("learning_rate", 0.1)),
        }
        return out
    return {
        "max_iter": int(p.get("iterations", p.get("max_iter", 200))),
        "C": float(p.get("C", 1.0)),
    }


def _append_timeline(task_id: str, title: str, detail: Optional[dict] = None) -> None:
    db = get_session()
    try:
        row = db.execute(select(TaskDetail).where(TaskDetail.task_id == task_id)).scalar_one_or_none()
        if not row:
            return
        tl = []
        if row.timeline_json:
            try:
                tl = json.loads(row.timeline_json)
            except Exception:
                tl = []
        tl.append(
            {
                "title": title,
                # 统一写北京时间（naive ISO），避免前端再次按 UTC 转换导致“晚 8 小时”
                "time": _biz_now_naive().isoformat(timespec="seconds"),
                "detail": detail or {},
            }
        )
        row.timeline_json = json.dumps(tl, ensure_ascii=False)
        db.commit()
    except Exception as e:
        logger.warning("append_timeline failed: %s", e)
        db.rollback()
    finally:
        db.close()


def wizard_state_get(task_id: str) -> Optional[Dict[str, Any]]:
    with WIZARD_LOCK:
        return WIZARD_STATE.get(task_id)


def wizard_state_clear(task_id: str) -> None:
    with WIZARD_LOCK:
        WIZARD_STATE.pop(task_id, None)


def wizard_init(account_id: int, name: str, scene: str) -> str:
    task_id = f"t-{uuid.uuid4().hex[:8]}"
    # tasks.uk_account_task：同一账号下 task_name 唯一；用户多次填「test」会触发 IntegrityError → 500
    base = (name or "").strip()[:200] or "未命名任务"
    task_name = f"{base} ({task_id})"[:255]
    db = get_session()
    try:
        task = Task(task_id=task_id, account_id=account_id, task_name=task_name)
        detail = TaskDetail(
            task_id=task_id,
            scene=scene or "fraud",
            status="running",
            timeline_json=json.dumps([], ensure_ascii=False),
        )
        db.add(task)
        db.add(detail)
        db.commit()
    finally:
        db.close()

    with WIZARD_LOCK:
        WIZARD_STATE[task_id] = {
            "account_id": account_id,
            "train_phase": "idle",
            "train_progress": 0,
            "train_error": "",
        }
    _append_timeline(task_id, "任务已创建", {"task_id": task_id})
    return task_id


def _assert_task_account(task_id: str, account_id: int) -> None:
    db = get_session()
    try:
        t = db.execute(select(Task).where(Task.task_id == task_id)).scalar_one_or_none()
        if not t or int(t.account_id) != int(account_id):
            raise PermissionError("任务不存在或无权访问")
    finally:
        db.close()


def wizard_create_container(ec: Any, task_id: str, account_id: int, resources: Optional[dict]) -> Dict[str, Any]:
    _assert_task_account(task_id, account_id)
    # 直接调控制器 create_training_container（与 POST /api/v1/containers mode=training 等价），避免 Flask 单线程下自调 HTTP 读超时
    task_data: Dict[str, Any] = {
        "algorithm": "xgboost_classifier",
        "min_samples": 2000,
        "portal_task_id": str(task_id),
    }
    cid, info = ec.create_training_container(
        resources=_norm_resources_for_ic(resources),
        task_data=task_data,
    )
    cinfo = dict(info)
    cinfo["container_id"] = cid
    att = _http_base_from_localhost(cinfo.get("attestation_address") or "")
    trn = _http_base_from_localhost(cinfo.get("training_address") or "")
    with WIZARD_LOCK:
        st = WIZARD_STATE.setdefault(task_id, {})
        st.update(
            {
                "container_id": cid,
                "container_info": cinfo,
                "attestation_address_raw": cinfo.get("attestation_address"),
                "training_address_raw": cinfo.get("training_address"),
                "attestation_base": att,
                "training_base": trn,
            }
        )

    db = get_session()
    try:
        row = db.execute(select(TaskDetail).where(TaskDetail.task_id == task_id)).scalar_one_or_none()
        if row:
            row.container_name = cinfo.get("name") or str(cid)[:12]
            row.node_name = "TEE节点A"
            db.commit()
    finally:
        db.close()

    _append_timeline(task_id, "训练容器已创建", {"container_id": str(cid)[:12]})
    return {
        "container_id": cid,
        "container_status": cinfo.get("status", "running"),
        "image": cinfo.get("image"),
    }


def wizard_attest(task_id: str, account_id: int) -> Dict[str, Any]:
    _assert_task_account(task_id, account_id)
    with WIZARD_LOCK:
        st = WIZARD_STATE.get(task_id) or {}
    raw_att = st.get("attestation_address_raw")
    if not raw_att:
        raise RuntimeError("缺少容器证明地址，请先创建容器")
    attest_addr = _dynamic_service_host_port_for_container(raw_att)
    _wait_attestation_agent_ready(attest_addr)
    # 与 scripts/integrated_client.perform_remote_attestation 完全一致（内部使用 module1.client.ConfidentialComputeClient）
    ic = _make_wizard_ic()
    ok, pubkey_pem = ic.perform_remote_attestation(attest_addr)
    if not ok or not pubkey_pem:
        raise RuntimeError("远程证明未通过")
    ev_hash = hashlib.sha256(pubkey_pem.encode("utf-8")).hexdigest()[:16]
    with WIZARD_LOCK:
        WIZARD_STATE.setdefault(task_id, {})["pubkey_pem"] = pubkey_pem

    try:
        root = _wizard_data_root()
        tdir = _wizard_task_dir_abs(root, task_id)
        os.makedirs(tdir, exist_ok=True)
        bundle = getattr(ic, "_last_attestation_report", None) or {}
        report = {
            "format_version": 3,
            "task_id": task_id,
            "flow": "scripts/integrated_client.IntegratedClient.perform_remote_attestation "
            "-> module1.client.ConfidentialComputeClient.attest_container "
            "-> 容器证明代理 /api/v1/attest 与证明服务 /api/v1/verify",
            "proof_id": f"prf-{ev_hash}",
            "proof_digest": f"sha256:{ev_hash}",
            "public_key_pem": pubkey_pem,
            "attestation_address_raw": raw_att,
            "attestation_address_used": attest_addr,
            "controller_url": getattr(ic, "controller_url", ""),
            "verify_url": getattr(ic, "verify_url", ""),
            # 与 integrated_client 内一次成功证明一致的材料（evidence / verify_result 来自 module1.client 真实响应）
            "verify_result": bundle.get("verify_result"),
            "evidence": bundle.get("evidence"),
            "notes": [
                "本文件由向导在 perform_remote_attestation 成功后落盘；非手写模拟。",
                "evidence 为证明代理返回的取证结构；verify_result 为（或含）证明服务校验结果。",
                "若 ALLOW_CSV_SIMULATION=1 且环境无 CSV 设备，evidence 中可能出现模拟类型，以证据字段为准。",
            ],
        }
        _json_safe_dump(os.path.join(tdir, "attestation_report.json"), report)
    except Exception as ex:
        logger.warning("写入 attestation_report.json 失败: %s", ex)

    _append_timeline(task_id, "远程证明已通过", {"evidence_hash": ev_hash})
    return {
        "proof_id": f"prf-{ev_hash}",
        "proof_digest": f"sha256:{ev_hash}",
    }


def wizard_upload_csv(
    host_data_dir: str, task_id: str, account_id: int, filename: str, raw: bytes, algorithm_ui: str, params: dict
) -> Dict[str, Any]:
    """host_data_dir：在 controller 容器内为数据卷挂载点（如 /data），勿传入宿主机 bind 源路径。"""
    _assert_task_account(task_id, account_id)
    if not host_data_dir:
        raise RuntimeError("未解析到数据卷挂载路径，无法保存上传文件")
    safe = secure_filename(filename) or "input.csv"
    rel_dir = os.path.join("wizard", task_id)
    abs_dir = os.path.join(host_data_dir, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    rel_path = os.path.join(rel_dir, safe).replace("\\", "/")
    abs_path = os.path.join(host_data_dir, rel_path)
    with open(abs_path, "wb") as f:
        f.write(raw)

    backend_alg = map_algorithm_ui(algorithm_ui)
    backend_params = map_params_for_backend(backend_alg, params)
    with WIZARD_LOCK:
        WIZARD_STATE.setdefault(task_id, {}).update(
            {
                "plaintext_rel": rel_path.replace("\\", "/"),
                "algorithm_backend": backend_alg,
                "params_backend": backend_params,
                "dataset_name": safe,
                "_host_data_dir": host_data_dir,
            }
        )

    db = get_session()
    try:
        row = db.execute(select(TaskDetail).where(TaskDetail.task_id == task_id)).scalar_one_or_none()
        if row:
            row.algorithm = algorithm_ui
            row.params_json = json.dumps(params or {}, ensure_ascii=False)
            row.dataset_json = json.dumps({"name": safe, "bytes": len(raw)}, ensure_ascii=False)
            db.commit()
    finally:
        db.close()

    _append_timeline(task_id, "数据与算法已提交", {"file": safe, "algorithm": algorithm_ui})
    return {"stored_as": rel_path, "bytes": len(raw)}


def wizard_inject_and_encrypt(task_id: str, account_id: int) -> Dict[str, Any]:
    _assert_task_account(task_id, account_id)
    with WIZARD_LOCK:
        st = dict(WIZARD_STATE.get(task_id) or {})
    raw_att = st.get("attestation_address_raw")
    pubkey_pem = st.get("pubkey_pem")
    plain_rel = st.get("plaintext_rel")
    host_data = st.get("_host_data_dir")
    if not raw_att or not pubkey_pem or not plain_rel:
        raise RuntimeError("状态不完整：请先完成证明与数据上传")

    if not host_data:
        raise RuntimeError("缺少数据目录上下文，请重新上传数据文件")
    plain_abs = os.path.join(host_data, plain_rel.replace("/", os.sep))
    if not os.path.isfile(plain_abs):
        raise RuntimeError("上传的明文文件不存在")

    enc_name = os.path.splitext(os.path.basename(plain_rel))[0] + ".enc"
    enc_rel = os.path.join(os.path.dirname(plain_rel), enc_name).replace("\\", "/")
    enc_abs = os.path.join(host_data, enc_rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(enc_abs), exist_ok=True)

    # 与 scripts/integrated_client：generate_dek -> encrypt_data_file -> inject_key(attestation_address, pubkey)
    ic = _make_wizard_ic()
    ic.generate_dek()
    ic.encrypt_data_file(plain_abs, enc_abs)
    inject_addr = _dynamic_service_host_port_for_container(raw_att)
    ic.inject_key(inject_addr, pubkey_pem)
    key_id = ic.key_id
    dek = ic.dek
    if not key_id or not dek:
        raise RuntimeError("密钥注入未完成")

    public_key = serialization.load_pem_public_key(pubkey_pem.encode(), backend=default_backend())
    encrypted_key = public_key.encrypt(
        dek,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    b64 = base64.b64encode(encrypted_key).decode()

    dek_id = hashlib.sha256(dek).hexdigest()[:12]
    with WIZARD_LOCK:
        WIZARD_STATE.setdefault(task_id, {}).update(
            {
                "dek": dek,
                "key_id": key_id,
                "ciphertext_rel": enc_rel,
            }
        )

    # 供用户离线解密 CSV/理解链路的真实材料（含 SM4 DEK 与 RSA 信封；须按组织制度保管）
    try:
        rel_dir = os.path.dirname(enc_rel.replace("\\", "/"))
        tdir = os.path.join(host_data, rel_dir.replace("/", os.sep))
        os.makedirs(tdir, exist_ok=True)
        key_material = {
            "format_version": 1,
            "task_id": task_id,
            "key_id": key_id,
            "dek_hex": dek.hex(),
            "wrapped_dek_base64": b64,
            "cipher_csv_relative": enc_rel.replace("\\", "/"),
            "algorithm": "SM4-128-ECB + PKCS7 padding（与训练侧 inject-key 会话一致）",
            "notes": [
                "dek_hex 为本次任务 SM4 数据加密密钥；可用于离线解密 wizard 目录下 CSV .enc（ECB+PKCS7）。",
                "训练服务内模型密文由证明代理按同一 key_id 经 SM4 封装，离线解密需调用代理 decrypt 或自行与训练侧约定格式。",
                "wrapped_dek_base64 为注入前 RSA-OAEP(SHA256) 包裹的 DEK，仅持有容器内 RSA 私钥一方可直接解出 DEK。",
            ],
        }
        _json_safe_dump(os.path.join(tdir, "key_material.json"), key_material)
    except Exception as ex:
        logger.warning("写入 key_material.json 失败: %s", ex)

    _append_timeline(
        task_id,
        "DEK 已生成并完成数据加密与密钥注入",
        {"dek_id": dek_id, "cipher_file": enc_rel},
    )
    return {"dek_id": dek_id, "encryption_status": "已加密", "key_id": key_id}


def wizard_start_train_thread(ec: Any, task_id: str, account_id: int) -> None:
    _assert_task_account(task_id, account_id)
    with WIZARD_LOCK:
        st0 = WIZARD_STATE.get(task_id) or {}
        ph0 = st0.get("train_phase", "idle")
        if ph0 in ("starting", "running", "done"):
            raise RuntimeError("训练已启动或已完成，请勿重复提交")

    def runner():
        try:
            with WIZARD_LOCK:
                st = dict(WIZARD_STATE.get(task_id) or {})
            tr = st.get("training_base")
            key_id = st.get("key_id")
            alg = st.get("algorithm_backend")
            params = st.get("params_backend") or {}
            enc_rel = st.get("ciphertext_rel")
            if not tr or not key_id or not alg or not enc_rel:
                raise RuntimeError("训练前置状态不完整")

            data_uri = f"file:///app/data/{enc_rel.lstrip('/')}"

            with WIZARD_LOCK:
                WIZARD_STATE.setdefault(task_id, {}).update({"train_phase": "starting", "train_progress": 5})

            ic = _make_wizard_ic()
            ic.dek = st.get("dek")
            ic.key_id = key_id
            enc_abs = os.path.join(st.get("_host_data_dir") or "", enc_rel.replace("/", os.sep))
            training_endpoint = f"{tr.rstrip('/')}/v1/tasks"
            ttid = ic.submit_training_task(
                training_endpoint,
                enc_abs,
                alg,
                params,
                data_uri_override=data_uri,
            )
            if not ttid:
                raise RuntimeError("训练服务未返回 task_id")

            with WIZARD_LOCK:
                WIZARD_STATE.setdefault(task_id, {}).update(
                    {"training_task_id": ttid, "train_phase": "running", "train_progress": 20}
                )
            _append_timeline(task_id, "开始训练", {"training_task_id": ttid})

            def cb(p):
                with WIZARD_LOCK:
                    if task_id in WIZARD_STATE:
                        WIZARD_STATE[task_id]["train_progress"] = p

            cb(30)
            ok, st_mon = ic.monitor_training_task(
                training_endpoint,
                ttid,
                timeout=int(float(os.environ.get("WIZARD_TRAIN_TIMEOUT", "600"))),
            )
            if not ok:
                err = (st_mon or {}).get("error") if isinstance(st_mon, dict) else None
                raise RuntimeError(err or "训练失败")
            cb(100)

            with WIZARD_LOCK:
                WIZARD_STATE.setdefault(task_id, {}).update(
                    {"train_phase": "done", "train_progress": 100}
                )

            # 将密态模型缓存到本地任务目录，避免训练容器回收后下载失败。
            try:
                model_hex, model_meta = wizard_fetch_model_hex(task_id, account_id)
                if model_hex:
                    model_bytes = bytes.fromhex(model_hex)
                    model_rel = f"wizard/{task_id}/model_{ttid}.enc"
                    model_abs = os.path.join(st.get("_host_data_dir") or "", model_rel.replace("/", os.sep))
                    os.makedirs(os.path.dirname(model_abs), exist_ok=True)
                    with open(model_abs, "wb") as mf:
                        mf.write(model_bytes)
                    with WIZARD_LOCK:
                        WIZARD_STATE.setdefault(task_id, {}).update(
                            {"model_enc_rel": model_rel, "model_metadata": model_meta or {}}
                        )
            except Exception as ex:
                logger.warning("训练完成后缓存模型失败 task=%s: %s", task_id, ex)

            db = get_session()
            try:
                row = db.execute(select(TaskDetail).where(TaskDetail.task_id == task_id)).scalar_one_or_none()
                if row:
                    row.status = "success"
                    row.finished_at = _biz_now_naive()
                    files = [{"type": "model", "name": f"model_{ttid}.enc", "training_task_id": ttid}]
                    row.result_files_json = json.dumps(files, ensure_ascii=False)
                    db.commit()
            finally:
                db.close()

            _append_timeline(task_id, "训练已完成", {"training_task_id": ttid})

            with WIZARD_LOCK:
                cid2 = (WIZARD_STATE.get(task_id) or {}).get("container_id")
            # 默认保留容器：供管理员在「机密容器管理」中查看；空闲约 10 分钟后由 controller idle_reaper 回收
            # 若需训练结束立刻删容器，可设环境变量 WIZARD_DESTROY_CONTAINER_AFTER_TRAIN=1
            if cid2:
                try:
                    ec.touch_container_activity(cid2)
                except Exception as ex:
                    logger.warning("训练完成后刷新容器活动时间失败: %s", ex)
            if cid2 and os.environ.get("WIZARD_DESTROY_CONTAINER_AFTER_TRAIN", "0").lower() in (
                "1",
                "true",
                "yes",
            ):
                try:
                    ec.destroy_container(cid2)
                except Exception as ex:
                    logger.warning("训练完成后销毁容器失败: %s", ex)
        except Exception as e:
            logger.exception("wizard train failed task=%s", task_id)
            err_msg = str(e)
            if "提交训练任务失败" in err_msg:
                with WIZARD_LOCK:
                    cid_dbg = (WIZARD_STATE.get(task_id) or {}).get("container_id")
                tail_logs = _tail_dynamic_container_logs(cid_dbg, tail=160)
                if tail_logs:
                    err_msg = f"{err_msg}\n--- dynamic-container logs tail ---\n{tail_logs[-2500:]}"
            with WIZARD_LOCK:
                WIZARD_STATE.setdefault(task_id, {}).update(
                    {"train_phase": "error", "train_error": err_msg, "train_progress": 0}
                )
            db = get_session()
            try:
                row = db.execute(select(TaskDetail).where(TaskDetail.task_id == task_id)).scalar_one_or_none()
                if row:
                    row.status = "failed"
                    row.finished_at = _biz_now_naive()
                    db.commit()
            finally:
                db.close()
            _append_timeline(task_id, "训练失败", {"error": err_msg})

    threading.Thread(target=runner, name=f"wizard-train-{task_id}", daemon=True).start()


def wizard_train_status(task_id: str, account_id: int) -> Dict[str, Any]:
    _assert_task_account(task_id, account_id)
    with WIZARD_LOCK:
        st = dict(WIZARD_STATE.get(task_id) or {})
    return {
        "phase": st.get("train_phase", "idle"),
        "progress": int(st.get("train_progress", 0)),
        "error": st.get("train_error", ""),
        "training_task_id": st.get("training_task_id", ""),
    }


def wizard_fetch_model_hex(task_id: str, account_id: int) -> Tuple[str, dict]:
    _assert_task_account(task_id, account_id)
    with WIZARD_LOCK:
        st = dict(WIZARD_STATE.get(task_id) or {})
    tr = st.get("training_base")
    ttid = st.get("training_task_id")
    if not tr or not ttid:
        raise RuntimeError("暂无可下载的训练任务")
    r = requests.get(f"{tr.rstrip('/')}/v1/tasks/{ttid}/result", timeout=120)
    r.raise_for_status()
    j = r.json()
    return j.get("model", ""), j.get("metadata") or {}


def wizard_load_model_blob(task_id: str, account_id: int) -> Optional[Tuple[bytes, dict]]:
    """
    优先返回训练完成时落盘的加密模型，避免训练容器回收后 /v1/tasks/{id}/result 不可达导致下载 500。
    """
    _assert_task_account(task_id, account_id)
    with WIZARD_LOCK:
        st = dict(WIZARD_STATE.get(task_id) or {})
    host_data = st.get("_host_data_dir")
    rel = st.get("model_enc_rel")
    if not host_data or not rel:
        return None
    p = os.path.join(host_data, str(rel).replace("/", os.sep))
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        raw = f.read()
    meta = st.get("model_metadata") if isinstance(st.get("model_metadata"), dict) else {}
    return raw, meta
