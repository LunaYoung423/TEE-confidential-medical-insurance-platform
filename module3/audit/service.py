import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, text, or_
from sqlalchemy.orm import Session

from module3.audit.models import AuditLog, TaskDetail, get_session, init_db
from module3.audit.signature import SM2Signature
from module3.audit.context import AuditContext
from module3.audit.utils import (
    generate_log_id,
    get_timestamp,
    get_user_id,
    get_client_ip,
    get_service_name,
    get_extra_data,
    serialize_data,
    calculate_sm3_hash,
    build_log_content,
)

logger = logging.getLogger(__name__)

# 跨进程（controller / training / attestation）写 audit_log 时必须串行取 prev，
# 否则 FOR UPDATE 只锁本连接内事务，多容器会读到相同「最后一条」导致链分叉。
def _audit_chain_lock_name() -> str:
    raw = os.environ.get("AUDIT_CHAIN_LOCK_NAME") or "cc_security_audit_chain"
    return str(raw)[:64]


def humanize_audit_operation_label(
    operation_type: Optional[str],
    _task_name: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> str:
    """
    将审计 operation_type（多为 HTTP 路径）转换为用户可读的简短说明，
    与用户端任务审计（时间线步骤语义）风格一致。
    operation_type 可能被截断至 64 字符，故同时参考 details.operation_desc。
    """
    raw = (operation_type or "").strip()
    desc = ""
    if isinstance(details, dict):
        desc = str(details.get("operation_desc") or "")
    blob = f"{raw} {desc}".strip().lower()
    if not blob:
        return "审计事件"

    # 优先使用上游显式业务描述，保证容器详情审计“类型”与用户端步骤语义一致
    if desc:
        desc_norm = desc.strip()
        key_hits = (
            "创建", "证明", "上传", "加密", "密钥", "训练", "下载", "查询训练任务状态", "获取训练任务结果"
        )
        if any(k in desc_norm for k in key_hits):
            return desc_norm[:48] + ("…" if len(desc_norm) > 48 else "")

    def _hit(*subs: str) -> bool:
        return all(s in blob for s in subs)

    # --- 训练服务（容器内 FastAPI /v1）---
    if "/v1/workload" in blob:
        return "查询训练服务负载"
    if _hit("/v1/tasks/", "/status"):
        return "查询训练任务状态"
    if _hit("/v1/tasks/", "/result"):
        return "获取训练任务结果"
    if re.search(r"\bpost\s+/v1/tasks\b", blob) and "/status" not in blob and "/result" not in blob:
        return "提交训练任务"
    if blob.startswith("delete ") and "/v1/tasks" in blob:
        return "删除训练任务"
    if "/v1/encrypt" in blob:
        return "请求数据加密"

    # --- 证明代理 ---
    if "/api/v1/attest" in blob:
        return "容器远程证明"
    if "/api/v1/verify" in blob:
        return "证明结果校验"

    # --- Controller / 向导 ---
    if "/wizard/init" in blob:
        return "创建向导任务"
    if "/wizard/container" in blob:
        return "创建训练容器"
    if "/wizard/attest" in blob:
        return "执行远程证明"
    if "/wizard/upload" in blob:
        return "上传训练数据"
    if "/wizard/protect-data" in blob:
        return "数据加密与密钥注入"
    if "/wizard/train-status" in blob:
        return "查询向导训练进度"
    if "/wizard/train" in blob:
        return "启动密态训练"
    if "/wizard/model-download" in blob:
        return "下载任务产物"
    if "/containers/" in blob and "/audit" in blob:
        return "查询容器审计记录"
    if "/containers/" in blob and "/logs" in blob:
        return "查询容器日志"
    if "/containers/" in blob and "/metrics" in blob:
        return "查询容器监控指标"
    if re.search(r"\bget\s+/api/v1/containers\b", blob) and "/api/v1/containers/" not in blob:
        return "查询容器列表"
    if "/scheduler/tasks" in blob:
        return "调度任务操作"
    if "/auth/login" in blob:
        return "用户登录"

    # --- 泛化 ---
    if raw.upper().startswith("GET "):
        return "读取接口数据"
    if raw.upper().startswith("POST "):
        return "提交接口请求"
    if raw.upper().startswith("DELETE "):
        return "删除接口资源"
    if raw.upper().startswith("PUT "):
        return "更新接口数据"
    return raw[:48] + ("…" if len(raw) > 48 else "")


def _training_task_ids_for_portal_task(portal_task_id: str) -> List[str]:
    """
    从 task_details.timeline_json / result_files_json 收集训练服务返回的 UUID（与 audit_log.task_id 一致）。
    门户任务 id（t-xxxx）与训练 task_id（UUID）不同，仅靠 task_id==portal 无法命中 module2 审计行。
    """
    pid = (portal_task_id or "").strip()
    if not pid:
        return []
    db: Session = get_session()
    try:
        row = db.execute(select(TaskDetail).where(TaskDetail.task_id == pid)).scalar_one_or_none()
        if not row:
            return []
        found: List[str] = []

        def _push(v: Any) -> None:
            if isinstance(v, str) and len(v.strip()) >= 8:
                found.append(v.strip())

        if row.timeline_json:
            try:
                tl = json.loads(row.timeline_json)
            except Exception:
                tl = []
            if isinstance(tl, list):
                for item in tl:
                    if not isinstance(item, dict):
                        continue
                    d = item.get("detail")
                    if isinstance(d, dict):
                        _push(d.get("training_task_id"))
        if row.result_files_json:
            try:
                files = json.loads(row.result_files_json)
            except Exception:
                files = []
            if isinstance(files, list):
                for f in files:
                    if isinstance(f, dict):
                        _push(f.get("training_task_id"))
        return list(dict.fromkeys(found))
    finally:
        db.close()


class AuditService:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if AuditService._initialized:
            return

        init_db(create_tables=True)
        self.signer = SM2Signature()
        AuditService._initialized = True

    def _get_last_log_hash_locked(self, db: Session) -> Optional[str]:
        """
        链尾必须以 log_id 为准：prev_log_hash 在串行锁下始终指向「当前最大 log_id」那一行的 cur。
        若按 event_time 取尾，会与验链遍历顺序（按时间排序）不一致，导致假「断链」。
        """
        try:
            stmt = (
                select(AuditLog)
                .order_by(AuditLog.log_id.desc())
                .limit(1)
                .with_for_update()
            )
            result = db.execute(stmt).scalar_one_or_none()
            if result:
                return result.cur_log_hash
            return None
        except Exception as e:
            logger.error(f"获取最后一条日志哈希失败: {e}")
            return None

    def _mysql_chain_lock_acquire(self, db: Session, timeout_sec: int = 20) -> bool:
        try:
            r = db.execute(
                text("SELECT GET_LOCK(:lock_name, :timeout)"),
                {"lock_name": _audit_chain_lock_name(), "timeout": int(timeout_sec)},
            ).scalar()
            return int(r or 0) == 1
        except Exception as e:
            logger.error(f"MySQL GET_LOCK 失败: {e}")
            return False

    def _mysql_chain_lock_release(self, db: Session) -> None:
        try:
            db.execute(
                text("SELECT RELEASE_LOCK(:lock_name)"),
                {"lock_name": _audit_chain_lock_name()},
            )
        except Exception as e:
            logger.warning(f"MySQL RELEASE_LOCK: {e}")

    def _use_mysql_chain_lock(self, db: Session) -> bool:
        try:
            return db.get_bind().dialect.name == "mysql"
        except Exception:
            return False

    @staticmethod
    def _db_status_to_hash_status(log: AuditLog) -> str:
        raw = getattr(log.status, "value", log.status)
        return "success" if str(raw).upper() == "SUCCESS" else "failed"

    def log_operation(
        self,
        operation_type: str,
        operation_desc: Optional[str] = None,
        request_data: Optional[Any] = None,
        response_data: Optional[Any] = None,
        status: str = "success",
        duration: Optional[int] = None,
        user_id: Optional[str] = None,
        client_ip: Optional[str] = None,
        service_name: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        db: Optional[Session] = None
        audit_trace_id = generate_log_id()
        timestamp = get_timestamp()

        user_id = user_id or get_user_id()
        client_ip = client_ip or get_client_ip()
        service_name = service_name or get_service_name()
        extra_data = extra_data or get_extra_data()

        request_str = serialize_data(request_data) if request_data else None
        response_str = serialize_data(response_data) if response_data else None
        extra_str = serialize_data(extra_data) if extra_data else None

        # audit_log.operation_type 列为 VARCHAR(64)，完整 URL 会超长
        operation_type = (operation_type or "")[:64]
        operation_desc = (operation_desc or operation_type)[:512]

        account_id = AuditContext.get_account_id()
        if account_id is None:
            raise ValueError(
                "必填字段缺失: account_id，请通过 AuditContext.set_account_id() 或 HTTP 默认设置"
            )

        task_id = AuditContext.get_task_id()
        if task_id is None:
            raise ValueError("必填字段缺失: task_id")

        task_name = AuditContext.get_task_name()
        if task_name is None:
            raise ValueError("必填字段缺失: task_name")
        task_name = str(task_name)[:255]

        container_id = AuditContext.get_container_id()
        trust_evidence = AuditContext.get_trust_evidence()

        db = get_session()
        lock_mysql = self._use_mysql_chain_lock(db)
        lock_held = False
        try:
            if lock_mysql:
                try:
                    # 默认等待不宜过长，否则 after_request 会阻塞响应并表现为前端“卡住”
                    lock_wait = max(2, int(os.environ.get("AUDIT_GET_LOCK_WAIT_SEC", "8")))
                except ValueError:
                    lock_wait = 8
                if not self._mysql_chain_lock_acquire(db, lock_wait):
                    raise RuntimeError("审计链全局锁获取超时（请重试或检查 MySQL GET_LOCK）")
                lock_held = True

            prev_log_hash = self._get_last_log_hash_locked(db)
            prev_log_hash_for_chain = prev_log_hash or "0" * 64

            log_content = build_log_content(
                log_id=audit_trace_id,
                timestamp=timestamp,
                user_id=user_id,
                client_ip=client_ip,
                service_name=service_name,
                operation_type=operation_type,
                operation_desc=operation_desc,
                request_data=request_str,
                response_data=response_str,
                status=status,
                duration=duration,
                prev_log_hash=prev_log_hash_for_chain,
                extra_data=extra_str,
            )

            cur_log_hash = calculate_sm3_hash(log_content)
            log_signature = self.signer.sign(cur_log_hash)

            details = {
                "audit_trace_id": audit_trace_id,
                "audit_user_id": user_id,
                "operation_desc": operation_desc,
                "request_data": (request_str[:4000] + "...<truncated>") if request_str and len(request_str) > 4000 else request_str,
                "response_data": (response_str[:8000] + "...<truncated>") if response_str and len(response_str) > 8000 else response_str,
                "service_name": service_name,
                "duration": duration,
                "extra_data": (extra_str[:4000] + "...<truncated>") if extra_str and len(extra_str) > 4000 else extra_str,
            }

            db_status = "SUCCESS" if status == "success" else "FAILURE"

            audit_log = AuditLog(
                event_time=timestamp,
                operation_type=operation_type,
                details=json.dumps(details, ensure_ascii=False),
                account_id=account_id,
                container_id=container_id,
                task_name=task_name,
                task_id=task_id,
                status=db_status,
                trust_evidence=trust_evidence,
                cur_log_hash=cur_log_hash,
                prev_log_hash=prev_log_hash_for_chain,
                log_signature=log_signature,
                source_ip=client_ip or "unknown",
            )

            db.add(audit_log)
            db.commit()
            db.refresh(audit_log)

            logger.info(f"审计日志记录成功: trace={audit_trace_id} db_log_id={audit_log.log_id}")
            return audit_trace_id

        except Exception as e:
            logger.error(f"记录审计日志失败: {e}")
            if db:
                db.rollback()
            raise
        finally:
            if db and lock_held:
                self._mysql_chain_lock_release(db)
            if db:
                db.close()

    def verify_chain_report(self, start_log_id: Optional[str] = None) -> Dict[str, Any]:
        """返回验链结果；失败时含 reason / fail_log_id，便于排查。"""
        try:
            db: Session = get_session()
            # 与写入侧一致：链顺序 = 自增 log_id（GET_LOCK 下即真实插入顺序）
            query = select(AuditLog).order_by(AuditLog.log_id.asc())

            if start_log_id:
                start_log = db.execute(
                    select(AuditLog).where(AuditLog.task_id == start_log_id)
                ).scalar_one_or_none()
                if start_log:
                    query = query.where(AuditLog.log_id >= start_log.log_id)

            logs = db.execute(query).scalars().all()
            db.close()

            if not logs:
                return {"valid": True, "checked": 0}

            prev_hash = None
            for log in logs:
                if prev_hash is not None and log.prev_log_hash != prev_hash:
                    logger.error(
                        "哈希链断裂: log_id=%s prev_log_hash 与前一记录 cur 不匹配",
                        log.log_id,
                    )
                    return {
                        "valid": False,
                        "reason": "prev_hash_mismatch",
                        "fail_log_id": log.log_id,
                        "expected_prev_tail": (prev_hash or "")[:16] + "...",
                        "got_prev_tail": (log.prev_log_hash or "")[:16] + "...",
                    }

                details = json.loads(log.details)
                trace_id = details.get("audit_trace_id") or log.task_id
                audit_user = details.get("audit_user_id") or str(log.account_id)

                log_content = build_log_content(
                    log_id=trace_id,
                    timestamp=log.event_time,
                    user_id=audit_user,
                    client_ip=log.source_ip,
                    service_name=details.get("service_name"),
                    operation_type=log.operation_type,
                    operation_desc=details.get("operation_desc"),
                    request_data=details.get("request_data"),
                    response_data=details.get("response_data"),
                    status=self._db_status_to_hash_status(log),
                    duration=details.get("duration"),
                    prev_log_hash=log.prev_log_hash,
                    extra_data=details.get("extra_data"),
                )

                calculated_hash = calculate_sm3_hash(log_content)
                if calculated_hash != log.cur_log_hash:
                    logger.error("哈希校验失败: log_id=%s", log.log_id)
                    return {
                        "valid": False,
                        "reason": "content_hash_mismatch",
                        "fail_log_id": log.log_id,
                        "calculated_tail": calculated_hash[:16] + "...",
                        "stored_tail": (log.cur_log_hash or "")[:16] + "...",
                    }

                if not self.signer.verify(log.cur_log_hash, log.log_signature):
                    logger.error("签名校验失败: log_id=%s", log.log_id)
                    return {
                        "valid": False,
                        "reason": "signature_mismatch",
                        "fail_log_id": log.log_id,
                    }

                prev_hash = log.cur_log_hash

            return {"valid": True, "checked": len(logs)}

        except Exception as e:
            logger.error("验证日志链失败: %s", e)
            return {"valid": False, "reason": "exception", "message": str(e)}

    def verify_log_chain(self, start_log_id: Optional[str] = None) -> bool:
        return bool(self.verify_chain_report(start_log_id).get("valid"))

    def get_log_by_task_id(self, task_id: str) -> Optional[AuditLog]:
        try:
            db: Session = get_session()
            log = db.execute(
                select(AuditLog).where(AuditLog.task_id == task_id)
            ).scalar_one_or_none()
            db.close()
            return log
        except Exception as e:
            logger.error(f"获取日志失败: {e}")
            return None

    def list_recent_logs(self, limit: int = 50):
        db: Session = get_session()
        try:
            rows = (
                db.execute(
                    select(AuditLog)
                    .order_by(AuditLog.event_time.desc(), AuditLog.log_id.desc())
                    .limit(min(max(limit, 1), 500))
                )
                .scalars()
                .all()
            )
            out = []
            for r in rows:
                out.append(
                    {
                        "db_log_id": r.log_id,
                        "event_time": r.event_time.isoformat() if r.event_time else None,
                        "operation_type": r.operation_type,
                        "account_id": r.account_id,
                        "task_id": r.task_id,
                        "task_name": r.task_name,
                        "status": r.status,
                        "source_ip": r.source_ip,
                    }
                )
            return out
        finally:
            db.close()

    @staticmethod
    def _status_to_frontend(status: Any) -> str:
        raw = getattr(status, "value", status)
        return "success" if str(raw).upper() == "SUCCESS" else "fail"

    @staticmethod
    def _parse_details(details: Any) -> Dict[str, Any]:
        if isinstance(details, dict):
            return details
        if not details:
            return {}
        try:
            return json.loads(details)
        except Exception:
            return {}

    @staticmethod
    def _display_tee_node_name(raw: Any) -> str:
        s = str(raw or "").strip()
        if not s or s.lower() in ("docker-host", "teea", "-"):
            return "TEE节点A"
        return s

    def query_audit_logs(
        self,
        *,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        types: Optional[List[str]] = None,
        object_id_like: str = "",
        results: Optional[List[str]] = None,
        page: int = 1,
        size: int = 10,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """按前端所需格式查询审计日志（直接读 audit_log）。"""
        db: Session = get_session()
        try:
            query = select(AuditLog)
            if start_time:
                query = query.where(AuditLog.event_time >= start_time)
            if end_time:
                query = query.where(AuditLog.event_time <= end_time)
            if types:
                query = query.where(AuditLog.operation_type.in_(types))
            if task_id:
                query = query.where(AuditLog.task_id == task_id)

            if results:
                normalized = {"SUCCESS" if str(r).lower() == "success" else "FAILURE" for r in results}
                query = query.where(AuditLog.status.in_(list(normalized)))

            if object_id_like:
                like = f"%{object_id_like}%"
                query = query.where(
                    (AuditLog.task_id.like(like))
                    | (AuditLog.container_id.like(like))
                    | (AuditLog.task_name.like(like))
                )

            all_rows = db.execute(
                query.order_by(AuditLog.event_time.desc(), AuditLog.log_id.desc())
            ).scalars().all()
            total = len(all_rows)

            p = max(1, int(page))
            s = max(1, min(int(size), 500))
            start_idx = (p - 1) * s
            rows = all_rows[start_idx : start_idx + s]

            items = []
            for r in rows:
                details_obj = self._parse_details(r.details)
                object_type = "task" if r.task_id else ("container" if r.container_id else "system")
                object_id = r.task_id or r.container_id or str(r.log_id)
                detail_payload = {
                    "task_id": r.task_id,
                    "task_name": r.task_name,
                    "container_id": r.container_id,
                    "source_ip": r.source_ip,
                    **details_obj,
                }
                if "node_name" in detail_payload:
                    detail_payload["node_name"] = self._display_tee_node_name(
                        detail_payload.get("node_name")
                    )
                items.append(
                    {
                        "id": f"audit-{r.log_id}",
                        "time": r.event_time.isoformat() if r.event_time else None,
                        "operation_type": r.operation_type,
                        "object_type": object_type,
                        "object_id": object_id,
                        "actor": str(r.account_id),
                        "result": self._status_to_frontend(r.status),
                        "detail_json": json.dumps(
                            detail_payload,
                            ensure_ascii=False,
                            indent=2,
                        ),
                    }
                )
            return {"items": items, "total": total}
        finally:
            db.close()

    def query_audit_logs_for_container(
        self,
        container_id: str,
        portal_task_id: Optional[str] = None,
        *,
        page: int = 1,
        size: int = 200,
    ) -> Dict[str, Any]:
        """
        管理端「容器详情」：按 Docker 容器 ID、门户任务 id（t-xxx）、以及任务时间线中的训练 task_id（UUID）
        关联 audit_log（module2 审计行使用训练 UUID，与门户 id 不一致，需从 task_details 解析）。
        """
        db: Session = get_session()
        try:
            cid = (container_id or "").strip()
            if not cid:
                return {"items": [], "total": 0}
            tid = (portal_task_id or "").strip() or None

            conds = [AuditLog.container_id == cid]
            if tid:
                conds.append(AuditLog.task_id == tid)
                for tt in _training_task_ids_for_portal_task(tid):
                    conds.append(AuditLog.task_id == tt)
                # controller / 中间件在 details 中可能含门户任务 id
                conds.append(AuditLog.details.like(f"%{tid}%"))

            query = select(AuditLog).where(or_(*conds))

            all_rows = db.execute(
                query.order_by(AuditLog.event_time.desc(), AuditLog.log_id.desc())
            ).scalars().all()
            total = len(all_rows)
            p = max(1, int(page))
            s = max(1, min(int(size), 500))
            start_idx = (p - 1) * s
            rows = all_rows[start_idx : start_idx + s]

            noise_types = {
                "读取接口数据",
                "提交接口请求",
                "更新接口数据",
                "删除接口资源",
                "审计事件",
                "查询容器列表",
                "查询容器日志",
                "查询容器监控指标",
                "查询容器审计记录",
            }
            items = []
            for r in rows:
                d_obj = self._parse_details(r.details)
                audit_type = humanize_audit_operation_label(
                    r.operation_type, r.task_name, d_obj
                )
                if audit_type in noise_types:
                    continue
                items.append(
                    {
                        "id": f"audit-{r.log_id}",
                        "time": r.event_time.isoformat() if r.event_time else None,
                        "type": audit_type,
                        "result": self._status_to_frontend(r.status),
                    }
                )
            return {"items": items, "total": len(items)}
        finally:
            db.close()

    def get_task_audit_timeline(self, task_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        """任务详情页审计摘要，直接来自 audit_log。"""
        db: Session = get_session()
        try:
            rows = (
                db.execute(
                    select(AuditLog)
                    .where(AuditLog.task_id == task_id)
                    .order_by(AuditLog.event_time.asc(), AuditLog.log_id.asc())
                    .limit(max(1, min(int(limit), 1000)))
                )
                .scalars()
                .all()
            )
            result = []
            for r in rows:
                d_obj = self._parse_details(r.details)
                result.append(
                    {
                        "event_id": f"task-{task_id}-audit-{r.log_id}",
                        "time": r.event_time.isoformat() if r.event_time else None,
                        "type": humanize_audit_operation_label(
                            r.operation_type, r.task_name, d_obj
                        ),
                        "result": "成功" if self._status_to_frontend(r.status) == "success" else "失败",
                        "node_name": self._display_tee_node_name("-"),
                        "container_name": r.container_id or "-",
                    }
                )
            return result
        finally:
            db.close()


def get_audit_service() -> AuditService:
    return AuditService()
