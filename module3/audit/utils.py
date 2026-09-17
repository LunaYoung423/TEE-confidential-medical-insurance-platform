import uuid
import json
from typing import Any, Optional, Dict
from datetime import datetime, timedelta, timezone
from module3.audit.pysmx_SM3 import digest as sm3_digest
from module3.audit.context import AuditContext


def generate_log_id() -> str:
    return str(uuid.uuid4())


def get_timestamp() -> datetime:
    # 业务统一使用北京时间墙钟（naive），避免前端把 UTC-naive 当本地时间显示导致偏差 8 小时
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)


def get_user_id() -> Optional[str]:
    user_id = AuditContext.get_user_id()
    if not user_id:
        user_id = "anonymous"
    return user_id


def get_client_ip() -> Optional[str]:
    return AuditContext.get_client_ip()


def get_service_name() -> Optional[str]:
    return AuditContext.get_service_name()


def get_request_id() -> Optional[str]:
    request_id = AuditContext.get_request_id()
    if not request_id:
        request_id = str(uuid.uuid4())
    return request_id


def get_extra_data() -> Optional[Dict[str, Any]]:
    return AuditContext.get_extra()


def serialize_data(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        return str(data)


def calculate_sm3_hash(data: str) -> str:
    if isinstance(data, str):
        data_bytes = data.encode("utf-8")
    else:
        data_bytes = data
    hash_bytes = sm3_digest(data_bytes)
    return hash_bytes.hex()


def build_log_content(
    log_id: str,
    timestamp: datetime,
    user_id: Optional[str],
    client_ip: Optional[str],
    service_name: Optional[str],
    operation_type: str,
    operation_desc: Optional[str],
    request_data: Optional[str],
    response_data: Optional[str],
    status: str,
    duration: Optional[int],
    prev_log_hash: Optional[str],
    extra_data: Optional[str],
) -> str:
    content_dict = {
        "log_id": log_id,
        "timestamp": timestamp.isoformat(),
        "user_id": user_id,
        "client_ip": client_ip,
        "service_name": service_name,
        "operation_type": operation_type,
        "operation_desc": operation_desc,
        "request_data": request_data,
        "response_data": response_data,
        "status": status,
        "duration": duration,
        "prev_log_hash": prev_log_hash,
        "extra_data": extra_data,
    }
    return json.dumps(content_dict, sort_keys=True, ensure_ascii=False)
