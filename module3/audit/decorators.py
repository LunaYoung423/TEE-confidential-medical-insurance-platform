import time
import functools
import inspect
from typing import Callable, Optional, Any

from module3.audit.service import get_audit_service
from module3.audit.context import AuditContext


def audited(
    operation_type: Optional[str] = None,
    operation_desc: Optional[str] = None,
    log_request: bool = True,
    log_response: bool = True,
    capture_exceptions: bool = True,
):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            audit_service = get_audit_service()

            op_type = operation_type or func.__name__
            op_desc = operation_desc or f"执行函数: {func.__name__}"

            start_time = time.time()
            status = "success"
            result = None
            error = None

            request_data = None
            if log_request:
                request_data = {"args": str(args), "kwargs": str(kwargs)}

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                status = "failed"
                error = str(e)
                if capture_exceptions:
                    raise
                return None
            finally:
                duration = int((time.time() - start_time) * 1000)

                response_data = None
                if log_response:
                    if error:
                        response_data = {"error": error}
                    else:
                        try:
                            response_data = {"result": str(result)}
                        except Exception:
                            response_data = {"result": "unserializable"}

                extra_data = AuditContext.get_all()

                audit_service.log_operation(
                    operation_type=op_type,
                    operation_desc=op_desc,
                    request_data=request_data,
                    response_data=response_data,
                    status=status,
                    duration=duration,
                    extra_data=extra_data,
                )

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            audit_service = get_audit_service()

            op_type = operation_type or func.__name__
            op_desc = operation_desc or f"执行函数: {func.__name__}"

            start_time = time.time()
            status = "success"
            result = None
            error = None

            request_data = None
            if log_request:
                request_data = {"args": str(args), "kwargs": str(kwargs)}

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "failed"
                error = str(e)
                if capture_exceptions:
                    raise
                return None
            finally:
                duration = int((time.time() - start_time) * 1000)

                response_data = None
                if log_response:
                    if error:
                        response_data = {"error": error}
                    else:
                        try:
                            response_data = {"result": str(result)}
                        except Exception:
                            response_data = {"result": "unserializable"}

                extra_data = AuditContext.get_all()

                audit_service.log_operation(
                    operation_type=op_type,
                    operation_desc=op_desc,
                    request_data=request_data,
                    response_data=response_data,
                    status=status,
                    duration=duration,
                    extra_data=extra_data,
                )

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return wrapper

    return decorator
