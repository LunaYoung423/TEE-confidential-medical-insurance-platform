from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import JSONResponse
import threading
import time
import os
import uuid
from module2.models.task import Task, TaskStatus
from module2.crypto_interface import CryptoInterface
from module2.algorithms import get_algorithm
from module2.utils.data_loader import load_data_from_bytes
from module2.utils.logger import logger
from module2.config import Config
from module3.audit.context import AuditContext
from module3.audit.middleware_fastapi import AuditMiddlewareFastAPI

app = FastAPI(title="密态训练支撑服务")
app.add_middleware(
    AuditMiddlewareFastAPI,
    service_name=os.environ.get("AUDIT_SERVICE_NAME_TRAINING", "training-service"),
)

tasks = {}
crypto = CryptoInterface(attestation_agent_url="http://localhost:8006")   # 与证明代理同容器

os.makedirs(Config.STORAGE_PATH, exist_ok=True)


def _audit_apply_training(request: Request, task_id: str, task_name: str) -> None:
    raw = request.headers.get("X-Account-Id") or os.environ.get("AUDIT_DEFAULT_ACCOUNT_ID", "1")
    try:
        account_id = int(raw)
    except ValueError:
        account_id = 1
    AuditContext.set_account_id(account_id)
    AuditContext.set_task_id(task_id)
    AuditContext.set_task_name(task_name[:255])


def _run_training(task: Task, key_id: str):
    try:
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        logger.info(f"Task {task.task_id} started with key_id {key_id}")

        data_bytes = crypto.decrypt_data(task.data_uri, key_id)
        X, y = load_data_from_bytes(data_bytes)

        if len(X) < Config.MIN_SAMPLES:
            raise ValueError(f"样本数 {len(X)} 小于 {Config.MIN_SAMPLES}")

        algo = get_algorithm(task.algorithm)
        model = algo.train(X, y, task.params)

        model_bytes = algo.save_model(model)
        cipher_model, metadata = crypto.encrypt_model(model_bytes, key_id)

        result_filename = f"model_{task.task_id}.enc"
        result_path = os.path.join(Config.STORAGE_PATH, result_filename)
        with open(result_path, "wb") as f:
            f.write(cipher_model)
        task.result_uri = f"file://{result_path}"
        task.result_metadata = metadata

        task.status = TaskStatus.COMPLETED
        task.completed_at = time.time()
        logger.info(f"Task {task.task_id} completed")
    except Exception as e:
        task.status = TaskStatus.FAILED
        task.error = str(e)
        logger.error(f"Task {task.task_id} failed: {e}")
    finally:
        crypto.cleanup_task(task.task_id)

@app.get("/")
async def root():
    return {"message": "密态训练支撑服务运行正常"}


@app.get("/v1/workload")
async def workload():
    """供 controller 空闲回收：是否存在排队或运行中的训练任务。"""
    active = 0
    busy = False
    for t in tasks.values():
        if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            busy = True
            active += 1
    return {"busy": busy, "active_tasks": active, "total_tasks": len(tasks)}


@app.post("/v1/tasks", response_class=JSONResponse)
async def create_task(
    request: Request,
    algorithm: str = Query(..., description="logistic_regression | xgboost | xgboost_classifier"),
    data_uri: str = Query(..., description="加密数据 file URI"),
    key_id: str = Query(..., description="密钥注入返回的 key_id"),
):
    params: dict = {}
    try:
        body = await request.json()
        if isinstance(body, dict):
            params = body.get("params") or {}
    except Exception:
        pass
    task = Task(algorithm, params, data_uri)
    tasks[task.task_id] = task
    _audit_apply_training(request, task.task_id, f"train:{algorithm}")

    thread = threading.Thread(target=_run_training, args=(task, key_id))
    thread.start()

    return {"task_id": task.task_id, "status": task.status.value}

@app.get("/v1/tasks/{task_id}/status")
async def get_task_status(request: Request, task_id: str):
    task = tasks.get(task_id)
    name = task.algorithm if task else "task-status"
    _audit_apply_training(request, task_id, name)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "error": task.error
    }

@app.get("/v1/tasks/{task_id}/result")
async def get_task_result(request: Request, task_id: str):
    task = tasks.get(task_id)
    name = task.algorithm if task else "task-result"
    _audit_apply_training(request, task_id, name)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail=f"Task not completed")
    path = task.result_uri.replace('file://', '')
    if not os.path.exists(path):
        raise HTTPException(status_code=500, detail="Result file missing")
    with open(path, "rb") as f:
        content = f.read()
    return JSONResponse(content={
        "model": content.hex(),
        "metadata": task.result_metadata
    })

@app.delete("/v1/tasks/{task_id}")
async def delete_task(request: Request, task_id: str):
    task = tasks.pop(task_id, None)
    _audit_apply_training(request, task_id, "task-delete")
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    crypto.cleanup_task(task_id)
    if task.result_uri:
        path = task.result_uri.replace('file://', '')
        if os.path.exists(path):
            os.remove(path)
    return {"message": "Task deleted"}