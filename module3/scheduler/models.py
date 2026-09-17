from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class SchedulerJobStatus(str, Enum):
    QUEUED = "queued"
    PROVISIONING = "provisioning"
    ATTESTING = "attesting"
    INJECTING = "injecting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DESTROYING = "destroying"


@dataclass
class SchedulerJob:
    """单机多实例：一条调度作业对应一次机密容器上的密态训练全流程（可配置是否销毁容器）。"""

    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: SchedulerJobStatus = SchedulerJobStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    algorithm: str = "xgboost_classifier"
    data_uri: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    resources: Dict[str, Any] = field(default_factory=dict)
    task_data: Dict[str, Any] = field(default_factory=dict)

    perform_attestation: bool = True
    auto_generate_dek: bool = True
    dek_hex: Optional[str] = None
    wait_ready_seconds: float = 10.0
    # 默认 False：训练完成后保留容器，由 controller 空闲回收（默认 10 分钟无训练任务后删）；需立即删可 pipeline.destroy_container_on_finish=true
    destroy_container_on_finish: bool = False
    poll_interval_seconds: float = 5.0
    timeout_seconds: float = 600.0
    idle_timeout_seconds: Optional[float] = None
    idle_min_lifetime_seconds: Optional[float] = None
    idle_reap_enabled: Optional[bool] = None

    container_id: Optional[str] = None
    training_task_id: Optional[str] = None
    key_id: Optional[str] = None
    error: Optional[str] = None
    cancel_requested: bool = False

    attestation_base: Optional[str] = None
    training_base: Optional[str] = None

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "algorithm": self.algorithm,
            "data_uri": self.data_uri,
            "params": self.params,
            "resources": self.resources,
            "task_data": self.task_data,
            "perform_attestation": self.perform_attestation,
            "auto_generate_dek": self.auto_generate_dek,
            "dek_hex": ("***" if self.dek_hex else None),
            "wait_ready_seconds": self.wait_ready_seconds,
            "destroy_container_on_finish": self.destroy_container_on_finish,
            "idle_timeout_seconds": self.idle_timeout_seconds,
            "idle_min_lifetime_seconds": self.idle_min_lifetime_seconds,
            "idle_reap_enabled": self.idle_reap_enabled,
            "container_id": self.container_id,
            "training_task_id": self.training_task_id,
            "key_id": self.key_id,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
            "attestation_base": self.attestation_base,
            "training_base": self.training_base,
        }
