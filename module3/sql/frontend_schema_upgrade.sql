-- 新版前端（/user + /admin）数据库增强脚本
-- 目标库：security_audit
-- 执行前请先备份

USE `security_audit`;

CREATE TABLE IF NOT EXISTS `user_notifications` (
  `notification_id` varchar(64) NOT NULL COMMENT '通知ID',
  `account_id` bigint unsigned NOT NULL COMMENT '所属账号ID',
  `title` varchar(255) NOT NULL COMMENT '通知标题',
  `content` text NULL COMMENT '通知内容',
  `is_read` tinyint(1) NOT NULL DEFAULT 0 COMMENT '是否已读',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '通知时间',
  PRIMARY KEY (`notification_id`),
  KEY `idx_user_notifications_account_time` (`account_id`, `created_at`),
  CONSTRAINT `fk_user_notifications_account` FOREIGN KEY (`account_id`) REFERENCES `accounts` (`account_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户通知';

CREATE TABLE IF NOT EXISTS `task_details` (
  `task_id` varchar(36) NOT NULL COMMENT '任务ID',
  `scene` varchar(64) NULL COMMENT '任务场景',
  `algorithm` varchar(128) NULL COMMENT '算法名称',
  `params_json` text NULL COMMENT '训练参数（JSON）',
  `dataset_json` text NULL COMMENT '数据集信息（JSON）',
  `status` varchar(32) NOT NULL DEFAULT 'running' COMMENT '任务状态',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `finished_at` datetime NULL COMMENT '完成时间',
  `timeline_json` text NULL COMMENT '任务时间线（JSON）',
  `result_files_json` text NULL COMMENT '结果文件列表（JSON）',
  `epc_memory_mb` int NULL COMMENT '任务占用EPC内存(MB)',
  `node_name` varchar(128) NULL COMMENT '关联TEE节点名',
  `container_name` varchar(128) NULL COMMENT '关联容器名',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`task_id`),
  KEY `idx_task_details_status_created` (`status`, `created_at`),
  KEY `idx_task_details_scene` (`scene`),
  CONSTRAINT `fk_task_details_task` FOREIGN KEY (`task_id`) REFERENCES `tasks` (`task_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='任务扩展信息';

CREATE TABLE IF NOT EXISTS `task_audit_events` (
  `event_id` varchar(64) NOT NULL COMMENT '任务审计事件ID',
  `task_id` varchar(36) NOT NULL COMMENT '任务ID',
  `event_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '事件时间',
  `event_type` varchar(64) NOT NULL COMMENT '事件类型',
  `result` varchar(32) NOT NULL DEFAULT 'success' COMMENT '事件结果',
  `node_name` varchar(128) NULL COMMENT 'TEE节点名',
  `container_name` varchar(128) NULL COMMENT 'TEE容器名',
  `detail_json` text NULL COMMENT '事件明细（JSON）',
  PRIMARY KEY (`event_id`),
  KEY `idx_task_audit_events_task_time` (`task_id`, `event_time`),
  KEY `idx_task_audit_events_type` (`event_type`),
  CONSTRAINT `fk_task_audit_events_task` FOREIGN KEY (`task_id`) REFERENCES `tasks` (`task_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='任务审计事件';

CREATE TABLE IF NOT EXISTS `tee_cluster_nodes` (
  `node_id` varchar(64) NOT NULL COMMENT '节点ID',
  `node_name` varchar(128) NOT NULL COMMENT '节点名称',
  `ip` varchar(64) NULL COMMENT '节点IP',
  `cpu_model` varchar(128) NULL COMMENT 'CPU型号',
  `tee_type` varchar(32) NOT NULL DEFAULT 'CSV' COMMENT 'TEE类型',
  `status` varchar(32) NOT NULL DEFAULT 'online' COMMENT '节点状态',
  `epc_total_mb` int NOT NULL DEFAULT 1024 COMMENT 'EPC总量(MB)',
  `epc_used_mb` int NOT NULL DEFAULT 0 COMMENT 'EPC已用(MB)',
  `csv_protected_size` int NULL COMMENT 'CSV保护区大小(MB)',
  `csv_protection_level` varchar(32) NULL COMMENT 'CSV保护级别',
  `hardware_json` text NULL COMMENT '硬件信息（JSON）',
  `recent_proofs_json` text NULL COMMENT '最近证明记录（JSON）',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`node_id`),
  KEY `idx_tee_cluster_nodes_status` (`status`),
  KEY `idx_tee_cluster_nodes_tee_type` (`tee_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='TEE节点池';

CREATE TABLE IF NOT EXISTS `confidential_containers` (
  `container_id` varchar(64) NOT NULL COMMENT '容器ID',
  `container_name` varchar(255) NOT NULL COMMENT '容器名称',
  `image` varchar(255) NOT NULL COMMENT '镜像',
  `status` varchar(32) NOT NULL DEFAULT 'Pending' COMMENT '容器状态',
  `node_id` varchar(64) NULL COMMENT '所在节点ID',
  `tee_type` varchar(32) NOT NULL DEFAULT 'CSV' COMMENT 'TEE类型',
  `epc_limit_mb` int NULL COMMENT 'EPC限制(MB)',
  `epc_used_mb` int NULL COMMENT 'EPC已用(MB)',
  `logs_json` text NULL COMMENT '容器日志（JSON）',
  `audit_json` text NULL COMMENT '容器审计信息（JSON）',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`container_id`),
  KEY `idx_confidential_containers_status` (`status`),
  KEY `idx_confidential_containers_node` (`node_id`),
  KEY `idx_confidential_containers_created` (`created_at`),
  CONSTRAINT `fk_confidential_containers_node` FOREIGN KEY (`node_id`) REFERENCES `tee_cluster_nodes` (`node_id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='机密容器';

CREATE TABLE IF NOT EXISTS `admin_audit_events` (
  `event_id` varchar(64) NOT NULL COMMENT '管理员审计事件ID',
  `event_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '事件时间',
  `operation_type` varchar(64) NOT NULL COMMENT '操作类型',
  `object_type` varchar(64) NOT NULL COMMENT '对象类型',
  `object_id` varchar(128) NOT NULL COMMENT '对象ID',
  `actor` varchar(64) NOT NULL DEFAULT 'system' COMMENT '操作者',
  `result` varchar(32) NOT NULL DEFAULT 'success' COMMENT '执行结果',
  `detail_json` text NULL COMMENT '事件详情（JSON）',
  PRIMARY KEY (`event_id`),
  KEY `idx_admin_audit_events_time` (`event_time`),
  KEY `idx_admin_audit_events_object` (`object_type`, `object_id`),
  KEY `idx_admin_audit_events_result` (`result`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='管理员审计事件';

CREATE TABLE IF NOT EXISTS `attestation_reports` (
  `report_id` varchar(64) NOT NULL COMMENT '证明报告ID',
  `node_id` varchar(64) NULL COMMENT '节点ID',
  `task_id` varchar(36) NULL COMMENT '任务ID',
  `report_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '报告时间',
  `validation_json` text NULL COMMENT '验证结果（JSON）',
  `evidence_json` text NULL COMMENT 'Evidence（JSON）',
  `quote_json` text NULL COMMENT 'Quote（JSON）',
  `benchmark_json` text NULL COMMENT '基准对比（JSON）',
  PRIMARY KEY (`report_id`),
  KEY `idx_attestation_reports_node_time` (`node_id`, `report_time`),
  KEY `idx_attestation_reports_task_time` (`task_id`, `report_time`),
  CONSTRAINT `fk_attestation_reports_node` FOREIGN KEY (`node_id`) REFERENCES `tee_cluster_nodes` (`node_id`) ON DELETE SET NULL,
  CONSTRAINT `fk_attestation_reports_task` FOREIGN KEY (`task_id`) REFERENCES `tasks` (`task_id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='远程证明报告';

CREATE TABLE IF NOT EXISTS `system_config` (
  `config_key` varchar(128) NOT NULL COMMENT '配置键',
  `config_value` text NULL COMMENT '配置值',
  `value_type` varchar(32) NOT NULL DEFAULT 'string' COMMENT '值类型',
  `description` varchar(255) NULL COMMENT '配置说明',
  `updated_by` varchar(64) NULL COMMENT '更新人',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`config_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统配置';

INSERT INTO `system_config` (`config_key`, `config_value`, `value_type`, `description`, `updated_by`)
VALUES
  ('cert_valid_until', DATE_FORMAT(DATE_ADD(CURDATE(), INTERVAL 90 DAY), '%Y-%m-%d'), 'string', '证书有效期', 'bootstrap'),
  ('audit_retention_days', '30', 'int', '审计保留天数', 'bootstrap'),
  ('tee_driver_path', '/dev/tee0', 'string', 'TEE驱动路径', 'bootstrap'),
  ('crypto_lib_version', 'v1.2.3', 'string', '算法库版本', 'bootstrap')
ON DUPLICATE KEY UPDATE
  `config_value` = VALUES(`config_value`),
  `value_type` = VALUES(`value_type`),
  `description` = VALUES(`description`),
  `updated_by` = VALUES(`updated_by`);
