import time
import uuid
import logging
from typing import Optional

from flask import request, g

from module3.audit.context import AuditContext
from module3.audit.service import get_audit_service
from module3.audit.http_defaults import ensure_default_audit_http_context

logger = logging.getLogger(__name__)


class AuditMiddleware:
    def __init__(self, app=None, service_name: Optional[str] = None):
        self.service_name = service_name
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        app.before_request(self.before_request)
        app.after_request(self.after_request)
        app.teardown_request(self.teardown_request)

        if self.service_name:
            AuditContext.set_service_name(self.service_name)

    def before_request(self):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        g.request_id = request_id
        g.start_time = time.time()

        AuditContext.set_request_id(request_id)

        client_ip = self._get_client_ip()
        AuditContext.set_client_ip(client_ip)

        user_id = self._get_user_id()
        if user_id:
            AuditContext.set_user_id(user_id)

        if self.service_name:
            AuditContext.set_service_name(self.service_name)

        ensure_default_audit_http_context(request.method, request.path)

    def after_request(self, response):
        try:
            # 噪音控制：预检请求和审计查询接口不再写技术审计，避免日志风暴与链锁竞争
            if request.method == "OPTIONS" or request.path.startswith("/api/v1/audit/logs"):
                return response
            if not request.path.startswith("/api/"):
                return response
            if request.path.startswith("/api/v1/wizard/"):
                return response
            if request.path.startswith("/api/v1/auth/login"):
                return response
            # 高频只读接口不写审计链，避免 GET_LOCK 排队导致全站请求超时
            p = request.path.rstrip("/")
            if request.method == "GET" and (
                p.startswith("/api/v1/notifications")
                or p.startswith("/api/v1/accounts")
                or p == "/api/v1/tasks"
                or p == "/api/v1/containers"
                or p == "/api/v1/health"
                or ("/tasks/" in p and p.endswith("/audit"))
            ):
                return response
            # 单容器只读：详情 /audit /logs /metrics（路径含长 Docker ID，写库会超 operation_type 64 且放大锁竞争）
            if request.method == "GET" and p.startswith("/api/v1/containers/"):
                rest = p[len("/api/v1/containers/") :]
                if rest:
                    segs = rest.split("/")
                    if len(segs) == 1 or (len(segs) == 2 and segs[1] in ("audit", "logs", "metrics")):
                        return response
            # 管理端 TEE 资源池轮询较频，避免审计链锁放大延迟
            if p.startswith("/api/v1/admin/nodes"):
                return response
            duration = int((time.time() - g.start_time) * 1000)

            audit_service = get_audit_service()

            operation_type = f"{request.method} {request.path}"
            operation_desc = f"HTTP请求: {request.method} {request.path}"

            request_data = None
            if request.content_type and "application/json" in request.content_type:
                try:
                    request_data = request.get_json(silent=True)
                except Exception:
                    pass

            response_data = None
            if response.content_type and "application/json" in response.content_type:
                try:
                    response_data = response.get_json(silent=True)
                except Exception:
                    pass

            status = "success" if 200 <= response.status_code < 400 else "failed"

            extra_data = AuditContext.get_all()

            audit_service.log_operation(
                operation_type=operation_type,
                operation_desc=operation_desc,
                request_data=request_data,
                response_data=response_data,
                status=status,
                duration=duration,
                extra_data=extra_data,
            )
        except Exception as e:
            logger.error(f"审计中间件记录请求失败: {e}")

        return response

    def teardown_request(self, exception=None):
        AuditContext.clear()

    def _get_client_ip(self) -> str:
        if "X-Forwarded-For" in request.headers:
            ip = request.headers["X-Forwarded-For"].split(",")[0].strip()
        elif "X-Real-IP" in request.headers:
            ip = request.headers["X-Real-IP"]
        else:
            ip = request.remote_addr or "unknown"
        return ip

    def _get_user_id(self) -> Optional[str]:
        user_id = request.headers.get("X-User-ID")
        if not user_id and hasattr(g, "user") and hasattr(g.user, "id"):
            user_id = str(g.user.id)
        return user_id
