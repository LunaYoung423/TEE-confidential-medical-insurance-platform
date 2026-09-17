"""为 HTTP 审计中间件填充默认必填上下文（account_id / task_id / task_name）。"""
import os
import re
import uuid
from typing import Optional

from module3.audit.context import AuditContext


def _extract_task_id_from_path(path: str) -> Optional[str]:
    if not path:
        return None
    # 优先匹配任务详情/审计/下载等路径：/api/v1/tasks/<task_id>/...
    m = re.search(r"/api/v1/tasks/([^/]+)", path)
    if m and m.group(1):
        return m.group(1)
    return None


def ensure_default_audit_http_context(method: str, path: str) -> None:
    """
    在设置好 request_id 后调用。
    业务处理中可再次覆盖 task_id / task_name（如训练任务的真实 task_id）。
    """
    if AuditContext.get_account_id() is None:
        raw = (os.environ.get("AUDIT_DEFAULT_ACCOUNT_ID") or "1").strip() or "1"
        try:
            AuditContext.set_account_id(int(raw))
        except ValueError:
            AuditContext.set_account_id(1)
    rid: Optional[str] = AuditContext.get_request_id()
    task_id_from_path = _extract_task_id_from_path(path)
    if AuditContext.get_task_id() is None:
        AuditContext.set_task_id(task_id_from_path or rid or str(uuid.uuid4()))
    if AuditContext.get_task_name() is None:
        AuditContext.set_task_name(f"{method} {path}"[:255])
