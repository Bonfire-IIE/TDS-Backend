"""AppImage = 一种可被 Kuscia 调度的计算能力（PSI/联合统计/训练…）。

平台把"应用能力"建模为一等概念：登记进平台库并可注册到 Kuscia。
MVP 先纳管 Kuscia 已有的 SecretFlow 内置镜像（scope=builtin），
封装自定义镜像为进阶（scope=custom）。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AppImage(Base):
    """应用能力（= Kuscia AppImage 在平台侧的管理对象）。"""
    __tablename__ = "app_image"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # 唯一，即 Kuscia AppImage name
    name: Mapped[str] = mapped_column(String(128), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 能力类别：psi / stats / train / custom / general …
    capability: Mapped[str] = mapped_column(String(32))
    # 操作属性：该应用对数据执行的操作(合约操作词表子集，如 read/process)；空视为 ["process"]
    operations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 使用控制能力：该应用具备的保障(ephemeral 阅后即焚 / watermark / no_download …)
    uc_capabilities: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # 镜像坐标
    image_name: Mapped[str] = mapped_column(String(512))
    image_tag: Mapped[str] = mapped_column(String(128))
    # platform=平台 Harbor；third_party=外部 OCI/Docker Registry。
    registry_source: Mapped[str] = mapped_column(
        String(16), default="third_party", server_default="third_party"
    )
    registry: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Kuscia AppImage 结构（deploy_templates 必填；config_templates 可空）
    deploy_templates: Mapped[list | None] = mapped_column(JSON, nullable=True)
    config_templates: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    job_template: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Workflow port contract: {inputs:[{name,kind}], outputs:[{name,kind}]}.
    io_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    party_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parameter_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ui_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    task_input_template: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="registered")  # registered/delisted
    scope: Mapped[str] = mapped_column(String(16), default="custom")  # builtin/custom
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
