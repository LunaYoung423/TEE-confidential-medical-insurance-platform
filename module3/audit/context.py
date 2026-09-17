from contextvars import ContextVar
from typing import Any, Dict, Optional

# 使用 ContextVar：在 Uvicorn/async 下同一线程会并发处理多个协程请求，
# threading.local 会导致审计上下文串台（account_id 丢失等）；ContextVar 按协程隔离。
_audit_ctx: ContextVar[Optional[Dict[str, Any]]] = ContextVar("_audit_ctx", default=None)


class AuditContext:
    @classmethod
    def _get_context(cls) -> Dict[str, Any]:
        d = _audit_ctx.get()
        if d is None:
            d = {}
            _audit_ctx.set(d)
        return d

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        cls._get_context()[key] = value

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        return cls._get_context().get(key, default)

    @classmethod
    def get_all(cls) -> Dict[str, Any]:
        return cls._get_context().copy()

    @classmethod
    def clear(cls) -> None:
        _audit_ctx.set(None)

    @classmethod
    def set_user_id(cls, user_id: str) -> None:
        cls.set("user_id", user_id)

    @classmethod
    def get_user_id(cls) -> Optional[str]:
        return cls.get("user_id")

    @classmethod
    def set_client_ip(cls, client_ip: str) -> None:
        cls.set("client_ip", client_ip)

    @classmethod
    def get_client_ip(cls) -> Optional[str]:
        return cls.get("client_ip")

    @classmethod
    def set_service_name(cls, service_name: str) -> None:
        cls.set("service_name", service_name)

    @classmethod
    def get_service_name(cls) -> Optional[str]:
        return cls.get("service_name")

    @classmethod
    def set_request_id(cls, request_id: str) -> None:
        cls.set("request_id", request_id)

    @classmethod
    def get_request_id(cls) -> Optional[str]:
        return cls.get("request_id")

    @classmethod
    def set_extra(cls, extra: Dict[str, Any]) -> None:
        cls.set("extra", extra)

    @classmethod
    def get_extra(cls) -> Optional[Dict[str, Any]]:
        return cls.get("extra")

    @classmethod
    def set_audit_field(cls, key: str, value: Any) -> None:
        cls.set(key, value)

    @classmethod
    def get_audit_field(cls, key: str, default: Any = None) -> Any:
        return cls.get(key, default)

    @classmethod
    def set_account_id(cls, account_id: int) -> None:
        cls.set("account_id", account_id)

    @classmethod
    def get_account_id(cls) -> Optional[int]:
        return cls.get("account_id")

    @classmethod
    def set_task_id(cls, task_id: str) -> None:
        cls.set("task_id", task_id)

    @classmethod
    def get_task_id(cls) -> Optional[str]:
        return cls.get("task_id")

    @classmethod
    def set_task_name(cls, task_name: str) -> None:
        cls.set("task_name", task_name)

    @classmethod
    def get_task_name(cls) -> Optional[str]:
        return cls.get("task_name")

    @classmethod
    def set_container_id(cls, container_id: Optional[str]) -> None:
        cls.set("container_id", container_id)

    @classmethod
    def get_container_id(cls) -> Optional[str]:
        return cls.get("container_id")

    @classmethod
    def set_trust_evidence(cls, trust_evidence: Optional[str]) -> None:
        cls.set("trust_evidence", trust_evidence)

    @classmethod
    def get_trust_evidence(cls) -> Optional[str]:
        return cls.get("trust_evidence")
