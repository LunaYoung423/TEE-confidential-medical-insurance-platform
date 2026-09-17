from __future__ import annotations

import base64
import hashlib
import logging
import os
import queue
import threading
import time
from typing import Any, Dict, List, Optional

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from module3.scheduler.models import SchedulerJob, SchedulerJobStatus

logger = logging.getLogger(__name__)

_scheduler_singleton: Optional["LifecycleSchedulerService"] = None
_scheduler_lock = threading.Lock()


def _localhost_addr_to_http_base(addr: str) -> str:
    """
    controller 返回的 training_address 形如 localhost:32768。
    在 controller 容器内访问宿主机映射端口时使用 HOST_GATEWAY_IP（默认 172.17.0.1）。
    """
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
        gw = os.environ.get("HOST_GATEWAY_IP", "172.17.0.1")
        return f"http://{gw}:{port}"
    return f"http://{addr}"


def get_scheduler_service(env_controller: Any) -> "LifecycleSchedulerService":
    global _scheduler_singleton
    with _scheduler_lock:
        if _scheduler_singleton is None:
            _scheduler_singleton = LifecycleSchedulerService(env_controller)
        return _scheduler_singleton


class LifecycleSchedulerService:
    """
    单机多实例：队列 + 并发上限 + 每作业独立机密容器 +（可选）远程证明与密钥注入 + 训练轮询 + 容器回收。
    """

    def __init__(self, env_controller: Any):
        self._ec = env_controller
        qmax = int(os.environ.get("SCHEDULER_QUEUE_MAX", "100") or "100")
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, qmax))
        self._jobs: Dict[str, SchedulerJob] = {}
        self._jobs_lock = threading.RLock()
        self._max_concurrent = max(1, int(os.environ.get("SCHEDULER_MAX_CONCURRENT", "2") or "2"))
        self._active = 0
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._dispatcher = threading.Thread(target=self._dispatcher_loop, name="scheduler-dispatcher", daemon=True)
        self._dispatcher.start()

    def shutdown(self) -> None:
        self._stop.set()

    def set_max_concurrent(self, n: int) -> int:
        n = max(1, min(32, int(n)))
        with self._cond:
            self._max_concurrent = n
            self._cond.notify_all()
        return self._max_concurrent

    def get_config(self) -> Dict[str, Any]:
        with self._jobs_lock:
            depth = self._queue.qsize()
        with self._cond:
            active = self._active
            cap = self._max_concurrent
        return {
            "max_concurrent_jobs": cap,
            "active_jobs": active,
            "queue_depth": depth,
            "queue_max": self._queue.maxsize,
        }

    def submit(self, payload: Dict[str, Any]) -> SchedulerJob:
        job = self._build_job(payload)
        with self._jobs_lock:
            self._jobs[job.job_id] = job
        try:
            self._queue.put_nowait(job)
        except queue.Full as e:
            with self._jobs_lock:
                self._jobs.pop(job.job_id, None)
            raise RuntimeError("调度队列已满，请稍后重试或扩容队列上限") from e
        logger.info("作业已入队 job_id=%s algorithm=%s", job.job_id, job.algorithm)
        return job

    def get_job(self, job_id: str) -> Optional[SchedulerJob]:
        with self._jobs_lock:
            return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 50) -> List[SchedulerJob]:
        with self._jobs_lock:
            items = list(self._jobs.values())
        items.sort(key=lambda j: j.created_at, reverse=True)
        return items[: max(1, min(200, limit))]

    def cancel_job(self, job_id: str) -> bool:
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            job.cancel_requested = True
            if job.status == SchedulerJobStatus.QUEUED:
                job.status = SchedulerJobStatus.CANCELLED
                job.finished_at = time.time()
                return True
        if job.container_id:
            try:
                self._ec.destroy_container(job.container_id)
            except Exception as e:
                logger.warning("取消作业时销毁容器失败 job=%s: %s", job_id, e)
        return True

    def collect_metrics(self) -> Dict[str, Any]:
        import docker

        client = docker.from_env()
        out: Dict[str, Any] = {"containers": [], "scheduler": self.get_config()}
        try:
            for c in client.containers.list(all=True, filters={"name": "csv-"}):
                try:
                    st = c.stats(stream=False)
                    cpu = self._cpu_percent_from_stats(st)
                    mem = st.get("memory_stats", {}) or {}
                    out["containers"].append(
                        {
                            "id": c.id[:12],
                            "name": c.name,
                            "status": c.status,
                            "cpu_percent": cpu,
                            "mem_usage_bytes": mem.get("usage"),
                            "mem_limit_bytes": mem.get("limit"),
                        }
                    )
                except Exception as e:
                    out["containers"].append({"id": c.id[:12], "name": c.name, "error": str(e)})
        except Exception as e:
            out["error"] = str(e)
        return out

    @staticmethod
    def _cpu_percent_from_stats(st: Dict[str, Any]) -> Optional[float]:
        try:
            cpu_stats = st.get("cpu_stats", {}) or {}
            precpu = st.get("precpu_stats", {}) or {}
            cpu_usage = cpu_stats.get("cpu_usage", {}) or {}
            total_usage = cpu_usage.get("total_usage")
            system_usage = cpu_stats.get("system_cpu_usage")
            prev_total = (precpu.get("cpu_usage", {}) or {}).get("total_usage")
            prev_system = precpu.get("system_cpu_usage")
            if not all([total_usage, system_usage, prev_total, prev_system]):
                return None
            delta_total = total_usage - prev_total
            delta_sys = system_usage - prev_system
            if delta_sys <= 0:
                return None
            ncpus = len(cpu_usage.get("percpu_usage", []) or []) or 1
            return round((delta_total / delta_sys) * ncpus * 100.0, 2)
        except Exception:
            return None

    def _build_job(self, payload: Dict[str, Any]) -> SchedulerJob:
        pipe = payload.get("pipeline") or {}
        res = payload.get("resources") or {"cpu": 2, "memory": "4g"}
        return SchedulerJob(
            algorithm=payload.get("algorithm") or "xgboost_classifier",
            data_uri=payload.get("data_uri") or "",
            params=payload.get("params") or {},
            resources=res,
            task_data=payload.get("task_data") or {},
            perform_attestation=bool(pipe.get("perform_attestation", True)),
            auto_generate_dek=bool(pipe.get("auto_generate_dek", True)),
            dek_hex=pipe.get("dek_hex"),
            wait_ready_seconds=float(pipe.get("wait_ready_seconds", 10)),
            destroy_container_on_finish=bool(pipe.get("destroy_container_on_finish", False)),
            poll_interval_seconds=float(pipe.get("poll_interval_seconds", 5)),
            timeout_seconds=float(pipe.get("timeout_seconds", 600)),
            idle_timeout_seconds=pipe.get("idle_timeout_seconds"),
            idle_min_lifetime_seconds=pipe.get("idle_min_lifetime_seconds"),
            idle_reap_enabled=pipe.get("idle_reap_enabled"),
        )

    def _dispatcher_loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if job.cancel_requested:
                self._mark(job, SchedulerJobStatus.CANCELLED, error=None)
                continue
            with self._cond:
                while self._active >= self._max_concurrent and not self._stop.is_set():
                    self._cond.wait(timeout=0.5)
                if self._stop.is_set():
                    break
                self._active += 1
            threading.Thread(target=self._run_job_wrapper, args=(job,), daemon=True).start()

    def _run_job_wrapper(self, job: SchedulerJob) -> None:
        try:
            self._run_job(job)
        finally:
            with self._cond:
                self._active -= 1
                self._cond.notify_all()

    def _mark(self, job: SchedulerJob, status: SchedulerJobStatus, error: Optional[str] = None) -> None:
        job.status = status
        if error is not None:
            job.error = error
        if status in (
            SchedulerJobStatus.SUCCEEDED,
            SchedulerJobStatus.FAILED,
            SchedulerJobStatus.CANCELLED,
        ):
            job.finished_at = time.time()

    def _run_job(self, job: SchedulerJob) -> None:
        if job.cancel_requested:
            self._mark(job, SchedulerJobStatus.CANCELLED)
            return
        if not job.data_uri:
            self._mark(job, SchedulerJobStatus.FAILED, error="缺少 data_uri")
            return

        verify_base = (
            os.environ.get("INTERNAL_VERIFY_URL")
            or os.environ.get("ATTESTATION_SERVER")
            or "http://attestation-service:8081"
        ).rstrip("/")

        try:
            self._mark(job, SchedulerJobStatus.PROVISIONING)
            td = dict(job.task_data)
            td.setdefault("algorithm", job.algorithm)
            lc = {
                k: v
                for k, v in (
                    ("idle_timeout_seconds", job.idle_timeout_seconds),
                    ("idle_min_lifetime_seconds", job.idle_min_lifetime_seconds),
                    ("idle_reap_enabled", job.idle_reap_enabled),
                )
                if v is not None
            }
            cid, info = self._ec.create_training_container(
                job.resources, td, lc if lc else None
            )
            job.container_id = cid
            att = info.get("attestation_address") or ""
            trn = info.get("training_address") or ""
            job.attestation_base = _localhost_addr_to_http_base(att)
            job.training_base = _localhost_addr_to_http_base(trn)

            time.sleep(max(0.0, job.wait_ready_seconds))

            if job.cancel_requested:
                self._cleanup_container(job)
                self._mark(job, SchedulerJobStatus.CANCELLED)
                return

            if job.perform_attestation:
                self._mark(job, SchedulerJobStatus.ATTESTING)
                pubkey_pem = self._remote_attest(job, verify_base)
            else:
                raise ValueError("当前实现要求 perform_attestation=true 以获取注入公钥")

            if job.cancel_requested:
                self._cleanup_container(job)
                self._mark(job, SchedulerJobStatus.CANCELLED)
                return

            self._mark(job, SchedulerJobStatus.INJECTING)
            key_id = self._inject_session_key(job, pubkey_pem)
            job.key_id = key_id

            if job.cancel_requested:
                self._cleanup_container(job)
                self._mark(job, SchedulerJobStatus.CANCELLED)
                return

            self._mark(job, SchedulerJobStatus.RUNNING)
            task_id = self._start_training_task(job)
            job.training_task_id = task_id

            ok, err = self._wait_training(job)
            if job.cancel_requested:
                self._cleanup_container(job)
                self._mark(job, SchedulerJobStatus.CANCELLED)
                return
            if not ok:
                self._mark(job, SchedulerJobStatus.FAILED, error=err or "训练失败或超时")
            else:
                self._mark(job, SchedulerJobStatus.SUCCEEDED)
                # 不立即销毁时：从「训练结束」起算空闲 10 分钟（与 idle_reaper 对齐）
                if job.container_id and not job.destroy_container_on_finish:
                    try:
                        self._ec.touch_container_activity(job.container_id)
                    except Exception:
                        pass
        except Exception as e:
            logger.exception("作业执行异常 job_id=%s", job.job_id)
            self._mark(job, SchedulerJobStatus.FAILED, error=str(e))
        finally:
            if job.destroy_container_on_finish and job.container_id:
                try:
                    self._ec.destroy_container(job.container_id)
                except Exception as e:
                    logger.warning("销毁容器失败 job=%s cid=%s: %s", job.job_id, job.container_id, e)

    def _cleanup_container(self, job: SchedulerJob) -> None:
        if job.container_id:
            try:
                self._ec.destroy_container(job.container_id)
            except Exception:
                pass
            job.container_id = None

    def _remote_attest(self, job: SchedulerJob, verify_base: str) -> str:
        assert job.attestation_base
        challenge = base64.b64encode(os.urandom(16)).decode()
        r = requests.post(
            f"{job.attestation_base}/api/v1/attest",
            json={"challenge": challenge},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        evidence = data.get("evidence") or (data.get("data") or {}).get("evidence")
        pubkey_pem = data.get("public_key") or (data.get("data") or {}).get("public_key")
        if not evidence or not pubkey_pem:
            raise ValueError("证明响应缺少 evidence 或 public_key")

        vr = requests.post(
            f"{verify_base}/api/v1/verify",
            json={"evidence": evidence},
            timeout=20,
        )
        vr.raise_for_status()
        body = vr.json()
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        valid = data.get("valid", body.get("valid"))
        if valid is not True:
            raise ValueError(f"远程证明验证未通过: {body}")

        public_key = serialization.load_pem_public_key(pubkey_pem.encode(), backend=default_backend())
        pubkey_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        ph = hashlib.sha256(pubkey_bytes).hexdigest()
        if evidence.get("pubkey_hash") and ph != evidence["pubkey_hash"]:
            raise ValueError("公钥哈希与证据不一致")

        return pubkey_pem

    def _inject_session_key(self, job: SchedulerJob, pubkey_pem: str) -> str:
        if job.auto_generate_dek:
            dek = os.urandom(16)
        elif job.dek_hex:
            dek = bytes.fromhex(job.dek_hex)
            if len(dek) != 16:
                raise ValueError("dek_hex 必须为 32 位十六进制（16 字节 SM4 密钥）")
        else:
            raise ValueError("auto_generate_dek=false 时必须提供 pipeline.dek_hex")

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
        r = requests.post(
            f"{job.attestation_base}/api/v1/inject-key",
            json={"encrypted_key": b64},
            timeout=20,
        )
        r.raise_for_status()
        body = r.json()
        if body.get("code") != 0:
            raise ValueError(body.get("message") or "inject-key 失败")
        key_id = (body.get("data") or {}).get("key_id")
        if not key_id:
            raise ValueError("inject-key 响应缺少 key_id")
        return key_id

    def _start_training_task(self, job: SchedulerJob) -> str:
        assert job.training_base and job.key_id
        r = requests.post(
            f"{job.training_base}/v1/tasks",
            params={"algorithm": job.algorithm, "data_uri": job.data_uri, "key_id": job.key_id},
            json={"params": job.params},
            timeout=60,
        )
        r.raise_for_status()
        body = r.json()
        tid = body.get("task_id")
        if not tid:
            raise ValueError("训练服务未返回 task_id")
        return tid

    def _wait_training(self, job: SchedulerJob) -> tuple:
        assert job.training_base and job.training_task_id
        url = f"{job.training_base}/v1/tasks/{job.training_task_id}/status"
        deadline = time.time() + job.timeout_seconds
        while time.time() < deadline:
            if job.cancel_requested:
                return False, "cancelled"
            try:
                r = requests.get(url, timeout=10)
                if r.status_code != 200:
                    time.sleep(job.poll_interval_seconds)
                    continue
                st = r.json().get("status")
                if st == "completed":
                    return True, None
                if st == "failed":
                    return False, r.json().get("error") or "failed"
            except requests.RequestException:
                pass
            time.sleep(job.poll_interval_seconds)
        return False, "timeout"
