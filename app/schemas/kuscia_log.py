"""Kuscia Master 日志相关 DTO。"""
from __future__ import annotations

from pydantic import BaseModel


class PodLogRefOut(BaseModel):
    """任务容器日志的归属信息（master 上通常没有，见 services/kuscia_log.py）。"""

    namespace: str
    pod_name: str
    container: str
    restart_count: int


class LogFileOut(BaseModel):
    path: str
    name: str
    # component（节点组件日志）| pod（任务容器 stdout）
    kind: str
    # kuscia / kusciaapi / k3s / containerd / datamesh / envoy / other
    category: str
    size: int
    modified_at: str | None
    # 历史轮转文件（*.log.gz、*.log.20260809-12 等），非当前写入文件
    rotated: bool
    compressed: bool
    pod: PodLogRefOut | None = None


class LogFilesOut(BaseModel):
    """节点身份 + 其上的日志文件清单。"""

    domain_id: str
    node_name: str
    # lite | master | autonomy
    run_mode: str
    files: list[LogFileOut]


class LogTailOut(BaseModel):
    path: str
    lines: list[str]
    # 请求的行数上限；返回行数达到该值说明上方仍有更早的日志
    requested_lines: int
    truncated: bool
