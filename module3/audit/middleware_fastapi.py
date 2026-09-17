import time
import uuid
import logging
import json
from typing import Optional, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from module3.audit.context import AuditContext
from module3.audit.service import get_audit_service
from module3.audit.http_defaults import ensure_default_audit_http_context

logger = logging.getLogger(__name__)


class AuditMiddlewareFastAPI(BaseHTTPMiddleware):
    def __init__(self, app, service_name: Optional[str] = None):
        super().__init__(app)
        self.service_name = service_name
        if self.service_name:
            AuditContext.set_service_name(self.service_name)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start_time = time.time()

        AuditContext.set_request_id(request_id)

        client_ip = self._get_client_ip(request)
        AuditContext.set_client_ip(client_ip)

        user_id = self._get_user_id(request)
        if user_id:
            AuditContext.set_user_id(user_id)

        if self.service_name:
            AuditContext.set_service_name(self.service_name)

        ensure_default_audit_http_context(request.method, request.url.path)

        request_body = await self._get_request_body(request)

        path = request.url.path.rstrip("/")

        def _skip_audit() -> bool:
            # 训练任务创建接口要求快速返回 task_id，避免审计链锁竞争放大为业务超时/500
            if request.method == "POST" and path == "/v1/tasks":
                return True
            if path == "/v1/workload":
                return True
            # 探活/根路径不写审计，避免 GET_LOCK 与 account_id 上下文问题
            if request.method == "GET" and path in ("", "/"):
                return True
            if request.method == "GET" and path.endswith("/status"):
                return True
            if request.method == "GET" and path.endswith("/result"):
                return True
            return False

        try:
            response = await call_next(request)

            if _skip_audit():
                return response

            response_body = await self._get_response_body(response)

            duration = int((time.time() - start_time) * 1000)

            operation_type = f"{request.method} {request.url.path}"
            operation_desc = f"HTTP请求: {request.method} {request.url.path}"

            status = "success" if 200 <= response.status_code < 400 else "failed"

            extra_data = AuditContext.get_all()

            try:
                audit_service = get_audit_service()
                audit_service.log_operation(
                    operation_type=operation_type,
                    operation_desc=operation_desc,
                    request_data=request_body,
                    response_data=response_body,
                    status=status,
                    duration=duration,
                    extra_data=extra_data,
                )
            except Exception as log_err:
                logger.error("训练服务审计写入失败（不影响业务响应）: %s", log_err)

            return response

        except Exception as e:
            logger.error(f"审计中间件处理请求异常: {e}")
            duration = int((time.time() - start_time) * 1000)

            if not _skip_audit():
                try:
                    audit_service = get_audit_service()
                    operation_type = f"{request.method} {request.url.path}"
                    operation_desc = f"HTTP请求: {request.method} {request.url.path}"
                    extra_data = AuditContext.get_all()
                    audit_service.log_operation(
                        operation_type=operation_type,
                        operation_desc=operation_desc,
                        request_data=request_body,
                        response_data={"error": str(e)},
                        status="failed",
                        duration=duration,
                        extra_data=extra_data,
                    )
                except Exception as log_err:
                    logger.error("训练服务审计写入失败（异常路径）: %s", log_err)
            raise
        finally:
            AuditContext.clear()

    def _get_client_ip(self, request: Request) -> str:
        if "x-forwarded-for" in request.headers:
            ip = request.headers["x-forwarded-for"].split(",")[0].strip()
        elif "x-real-ip" in request.headers:
            ip = request.headers["x-real-ip"]
        else:
            ip = request.client.host if request.client else "unknown"
        return ip

    def _get_user_id(self, request: Request) -> Optional[str]:
        return request.headers.get("X-User-ID")

    async def _get_request_body(self, request: Request) -> Optional[dict]:
        try:
            # POST /v1/tasks 由路由自行 await request.json() 解析 params，避免与中间件重复读 body
            p = request.url.path.rstrip("/")
            if request.method == "POST" and p == "/v1/tasks":
                return None
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                body = await request.body()
                if body:
                    return json.loads(body.decode("utf-8"))
        except Exception:
            pass
        return None

    async def _get_response_body(self, response: Response) -> Optional[dict]:
        try:
            if hasattr(response, "body"):
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    if isinstance(response.body, bytes):
                        return json.loads(response.body.decode("utf-8"))
        except Exception:
            pass
        return None
