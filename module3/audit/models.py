import os
from sqlalchemy import (
    Column,
    BigInteger,
    Integer,
    String,
    Text,
    DateTime,
    Enum,
    Boolean,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, scoped_session
from sqlalchemy import create_engine
from pathlib import Path
from dotenv import load_dotenv

_module3_root = Path(__file__).resolve().parent.parent
_env_file = _module3_root / ".env"
if _env_file.is_file():
    load_dotenv(_env_file)
else:
    load_dotenv()

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    user_id = Column(
        BigInteger().with_variant(BigInteger, "mysql"),
        primary_key=True,
        autoincrement=True,
        comment="用户ID",
    )
    username = Column(String(64), unique=True, nullable=False, comment="用户名")
    password_hash = Column(String(255), nullable=False, comment="密码哈希")
    real_name = Column(String(100), nullable=True, comment="真实姓名")
    email = Column(String(100), nullable=True, comment="邮箱")
    phone = Column(String(20), nullable=True, comment="手机号")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )


class Account(Base):
    __tablename__ = "accounts"

    account_id = Column(
        BigInteger().with_variant(BigInteger, "mysql"),
        primary_key=True,
        autoincrement=True,
        comment="账号ID",
    )
    user_id = Column(
        BigInteger().with_variant(BigInteger, "mysql"),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        comment="所属用户ID",
    )
    account_name = Column(String(128), nullable=False, comment="账号名称")
    is_logged_in = Column(Boolean, nullable=False, default=False, comment="是否登录")
    last_login_ip = Column(String(45), nullable=True, comment="最后登录IP")
    last_login_time = Column(DateTime, nullable=True, comment="最后登录时间")
    status = Column(Boolean, nullable=False, default=True, comment="状态：1-启用 0-禁用")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")

    user = relationship("User", backref="accounts")
    tasks = relationship("Task", back_populates="account", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("user_id", "account_name", name="uk_user_account"),
        Index("idx_user", "user_id"),
    )


class Task(Base):
    __tablename__ = "tasks"

    task_id = Column(String(36), primary_key=True, comment="任务唯一编号（UUID）")
    account_id = Column(
        BigInteger().with_variant(BigInteger, "mysql"),
        ForeignKey("accounts.account_id", ondelete="CASCADE"),
        nullable=False,
        comment="所属账号ID",
    )
    task_name = Column(String(255), nullable=False, comment="任务名称")

    account = relationship("Account", back_populates="tasks")

    __table_args__ = (UniqueConstraint("account_id", "task_name", name="uk_account_task"),)


class UserNotification(Base):
    __tablename__ = "user_notifications"

    notification_id = Column(String(64), primary_key=True, comment="通知ID")
    account_id = Column(
        BigInteger().with_variant(BigInteger, "mysql"),
        ForeignKey("accounts.account_id", ondelete="CASCADE"),
        nullable=False,
        comment="所属账号ID",
    )
    title = Column(String(255), nullable=False, comment="通知标题")
    content = Column(Text, nullable=True, comment="通知内容")
    is_read = Column(Boolean, nullable=False, default=False, comment="是否已读")
    created_at = Column(DateTime, server_default=func.now(), comment="通知时间")

    account = relationship("Account")

    __table_args__ = (Index("idx_user_notifications_account_time", "account_id", "created_at"),)


class TaskDetail(Base):
    __tablename__ = "task_details"

    task_id = Column(
        String(36),
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        primary_key=True,
        comment="任务ID",
    )
    scene = Column(String(64), nullable=True, comment="任务场景")
    algorithm = Column(String(128), nullable=True, comment="算法名称")
    params_json = Column(Text, nullable=True, comment="训练参数（JSON）")
    dataset_json = Column(Text, nullable=True, comment="数据集信息（JSON）")
    status = Column(String(32), nullable=False, default="running", comment="任务状态")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    finished_at = Column(DateTime, nullable=True, comment="完成时间")
    timeline_json = Column(Text, nullable=True, comment="任务时间线（JSON）")
    result_files_json = Column(Text, nullable=True, comment="结果文件列表（JSON）")
    epc_memory_mb = Column(Integer, nullable=True, comment="任务占用EPC内存(MB)")
    node_name = Column(String(128), nullable=True, comment="关联TEE节点名")
    container_name = Column(String(128), nullable=True, comment="关联容器名")
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    task = relationship("Task")

    __table_args__ = (
        Index("idx_task_details_status_created", "status", "created_at"),
        Index("idx_task_details_scene", "scene"),
    )


class TaskAuditEvent(Base):
    __tablename__ = "task_audit_events"

    event_id = Column(String(64), primary_key=True, comment="任务审计事件ID")
    task_id = Column(
        String(36),
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        nullable=False,
        comment="任务ID",
    )
    event_time = Column(DateTime, server_default=func.now(), nullable=False, comment="事件时间")
    event_type = Column(String(64), nullable=False, comment="事件类型")
    result = Column(String(32), nullable=False, default="success", comment="事件结果")
    node_name = Column(String(128), nullable=True, comment="TEE节点名")
    container_name = Column(String(128), nullable=True, comment="TEE容器名")
    detail_json = Column(Text, nullable=True, comment="事件明细（JSON）")

    task = relationship("Task")

    __table_args__ = (
        Index("idx_task_audit_events_task_time", "task_id", "event_time"),
        Index("idx_task_audit_events_type", "event_type"),
    )


class TEEClusterNode(Base):
    __tablename__ = "tee_cluster_nodes"

    node_id = Column(String(64), primary_key=True, comment="节点ID")
    node_name = Column(String(128), nullable=False, comment="节点名称")
    ip = Column(String(64), nullable=True, comment="节点IP")
    cpu_model = Column(String(128), nullable=True, comment="CPU型号")
    tee_type = Column(String(32), nullable=False, default="CSV", comment="TEE类型")
    status = Column(String(32), nullable=False, default="online", comment="节点状态")
    epc_total_mb = Column(Integer, nullable=False, default=1024, comment="EPC总量(MB)")
    epc_used_mb = Column(Integer, nullable=False, default=0, comment="EPC已用(MB)")
    csv_protected_size = Column(Integer, nullable=True, comment="CSV保护区大小(MB)")
    csv_protection_level = Column(String(32), nullable=True, comment="CSV保护级别")
    hardware_json = Column(Text, nullable=True, comment="硬件信息（JSON）")
    recent_proofs_json = Column(Text, nullable=True, comment="最近证明记录（JSON）")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_tee_cluster_nodes_status", "status"),
        Index("idx_tee_cluster_nodes_tee_type", "tee_type"),
    )


class ConfidentialContainer(Base):
    __tablename__ = "confidential_containers"

    container_id = Column(String(64), primary_key=True, comment="容器ID")
    container_name = Column(String(255), nullable=False, comment="容器名称")
    image = Column(String(255), nullable=False, comment="镜像")
    status = Column(String(32), nullable=False, default="Pending", comment="容器状态")
    node_id = Column(
        String(64),
        ForeignKey("tee_cluster_nodes.node_id", ondelete="SET NULL"),
        nullable=True,
        comment="所在节点ID",
    )
    tee_type = Column(String(32), nullable=False, default="CSV", comment="TEE类型")
    epc_limit_mb = Column(Integer, nullable=True, comment="EPC限制(MB)")
    epc_used_mb = Column(Integer, nullable=True, comment="EPC已用(MB)")
    logs_json = Column(Text, nullable=True, comment="容器日志（JSON）")
    audit_json = Column(Text, nullable=True, comment="容器审计信息（JSON）")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    node = relationship("TEEClusterNode")

    __table_args__ = (
        Index("idx_confidential_containers_status", "status"),
        Index("idx_confidential_containers_node", "node_id"),
        Index("idx_confidential_containers_created", "created_at"),
    )


class AdminAuditEvent(Base):
    __tablename__ = "admin_audit_events"

    event_id = Column(String(64), primary_key=True, comment="管理员审计事件ID")
    event_time = Column(DateTime, server_default=func.now(), nullable=False, comment="事件时间")
    operation_type = Column(String(64), nullable=False, comment="操作类型")
    object_type = Column(String(64), nullable=False, comment="对象类型")
    object_id = Column(String(128), nullable=False, comment="对象ID")
    actor = Column(String(64), nullable=False, default="system", comment="操作者")
    result = Column(String(32), nullable=False, default="success", comment="执行结果")
    detail_json = Column(Text, nullable=True, comment="事件详情（JSON）")

    __table_args__ = (
        Index("idx_admin_audit_events_time", "event_time"),
        Index("idx_admin_audit_events_object", "object_type", "object_id"),
        Index("idx_admin_audit_events_result", "result"),
    )


class AttestationReport(Base):
    __tablename__ = "attestation_reports"

    report_id = Column(String(64), primary_key=True, comment="证明报告ID")
    node_id = Column(
        String(64),
        ForeignKey("tee_cluster_nodes.node_id", ondelete="SET NULL"),
        nullable=True,
        comment="节点ID",
    )
    task_id = Column(
        String(36),
        ForeignKey("tasks.task_id", ondelete="SET NULL"),
        nullable=True,
        comment="任务ID",
    )
    report_time = Column(DateTime, server_default=func.now(), nullable=False, comment="报告时间")
    validation_json = Column(Text, nullable=True, comment="验证结果（JSON）")
    evidence_json = Column(Text, nullable=True, comment="Evidence（JSON）")
    quote_json = Column(Text, nullable=True, comment="Quote（JSON）")
    benchmark_json = Column(Text, nullable=True, comment="基准对比（JSON）")

    node = relationship("TEEClusterNode")
    task = relationship("Task")

    __table_args__ = (
        Index("idx_attestation_reports_node_time", "node_id", "report_time"),
        Index("idx_attestation_reports_task_time", "task_id", "report_time"),
    )


class SystemConfig(Base):
    __tablename__ = "system_config"

    config_key = Column(String(128), primary_key=True, comment="配置键")
    config_value = Column(Text, nullable=True, comment="配置值")
    value_type = Column(String(32), nullable=False, default="string", comment="值类型")
    description = Column(String(255), nullable=True, comment="配置说明")
    updated_by = Column(String(64), nullable=True, comment="更新人")
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    log_id = Column(
        BigInteger().with_variant(BigInteger, "mysql"),
        primary_key=True,
        autoincrement=True,
        comment="日志ID",
    )
    event_time = Column(
        DateTime(6),
        nullable=False,
        server_default=func.now(6),
        comment="操作时间（微秒）",
    )
    operation_type = Column(String(64), nullable=False, comment="操作类型")
    details = Column(Text, nullable=False, comment="操作详情")
    account_id = Column(
        BigInteger().with_variant(BigInteger, "mysql"),
        ForeignKey("accounts.account_id", ondelete="RESTRICT"),
        nullable=False,
        comment="操作用户账号ID",
    )
    container_id = Column(String(64), nullable=True, comment="容器ID")
    task_name = Column(String(255), nullable=False, comment="任务名")
    task_id = Column(String(36), nullable=False, comment="任务ID")
    status = Column(Enum("SUCCESS", "FAILURE"), nullable=False, comment="操作状态")
    trust_evidence = Column(String(512), nullable=True, comment="可信证据")
    cur_log_hash = Column(String(64), nullable=False, comment="当前记录的哈希")
    prev_log_hash = Column(String(64), nullable=False, comment="上一条记录的哈希")
    log_signature = Column(String(512), nullable=False, comment="SM2签名")
    source_ip = Column(String(45), nullable=False, comment="操作来源IP")

    account = relationship("Account")

    __table_args__ = (
        Index("idx_account", "account_id"),
        Index("idx_time", "event_time"),
    )


def get_database_url():
    default_url = os.getenv("DATABASE_URL", None)
    if default_url:
        return default_url
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    database = os.getenv("DB_NAME", "security_audit")
    charset = "utf8mb4"
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset={charset}"


def init_db(create_tables=True):
    database_url = get_database_url()
    engine = create_engine(
        database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        echo=False,
    )
    if create_tables:
        Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    return engine, SessionFactory


_engine, _SessionFactory = init_db(create_tables=False)


def get_session():
    return _SessionFactory()


ScopedSession = scoped_session(_SessionFactory)
