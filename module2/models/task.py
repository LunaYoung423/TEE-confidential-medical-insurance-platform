import uuid
import time
from enum import Enum

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class Task:
    def __init__(self, algorithm: str, params: dict, data_uri: str):
        self.task_id = str(uuid.uuid4())
        self.algorithm = algorithm
        self.params = params
        self.data_uri = data_uri
        self.status = TaskStatus.PENDING
        self.created_at = time.time()
        self.started_at = None
        self.completed_at = None
        self.error = None
        self.result_uri = None
        self.result_metadata = None   # 新增字段