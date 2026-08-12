"""Kuscia Master 自身的日志读取（文件枚举 / 尾部拉取 / 实时跟随）。

只读 Master 一个节点。日志经 Master 的 KusciaAPI（/api/v1/log/node/*）取得，
不再经 docker.sock exec：业务系统上线后平台后端不一定拿得到宿主机 Docker 权限，
而 KusciaAPI 的节点日志接口只读接收请求的那个节点，因此这里天然看不到任何
连接器的日志——连接器的日志由各自的连接器门户（connector_portal）查看。

master 上不跑 agent，正常只有组件日志（kuscia.log/k3s.log/envoy/*.log 等）；
kind 仍原样透传，便于 autonomy 形态复用同一套接口。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

from app.core.config import settings
from app.integrations.kuscia import KusciaError, get_kuscia_client

_KINDS = ("all", "component", "pod")


class KusciaLogError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code


def _int(value: object) -> int:
    """protojson 把 int64 序列化成字符串，size/modified_time 都要过一遍。"""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _normalize(entry: dict) -> dict:
    mtime = _int(entry.get("modified_time"))
    pod = entry.get("pod") or None
    return {
        "path": entry.get("path", ""),
        "name": entry.get("name", ""),
        "kind": entry.get("kind", "component"),
        "category": entry.get("category", "other"),
        "size": _int(entry.get("size")),
        "modified_at": (
            datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat() if mtime else None
        ),
        "rotated": bool(entry.get("rotated")),
        "compressed": bool(entry.get("compressed")),
        "pod": {
            "namespace": pod.get("namespace", ""),
            "pod_name": pod.get("pod_name", ""),
            "container": pod.get("container", ""),
            "restart_count": _int(pod.get("restart_count")),
        } if pod else None,
    }


def list_files(kind: str | None = None) -> dict:
    """枚举 master 上的日志文件，返回 {domain_id,node_name,run_mode,files[]}。"""
    if kind and kind not in _KINDS:
        raise KusciaLogError(f"非法的日志类别：{kind}", 400)
    try:
        data = get_kuscia_client().list_node_log_files(None if kind in (None, "all") else kind)
    except KusciaError as e:
        raise KusciaLogError(f"读取 Master 日志清单失败：{e}", 502) from e
    return {
        "domain_id": data.get("domain_id", ""),
        "node_name": data.get("node_name", ""),
        "run_mode": data.get("run_mode", ""),
        "files": [_normalize(f) for f in data.get("files", []) or []],
    }


def _clamp_lines(lines: int) -> int:
    return max(1, min(int(lines), settings.kuscia_log_max_lines))


def _require_path(path: str) -> str:
    """只挡明显非法的输入；越界与否由 KusciaAPI 按节点日志根目录判定。"""
    if not path or not path.startswith("/"):
        raise KusciaLogError("日志路径必须是节点上的绝对路径", 400)
    return path


def _payload(path: str, lines: int, follow: bool, keyword: str | None) -> dict:
    return {
        "path": path,
        "tail_lines": lines,
        "follow": follow,
        "keyword": keyword or "",
    }


def _chunk_lines(chunk: dict) -> list[str]:
    """从一个 QueryLogResponse 取出日志行，顺带把 Kuscia 的错误状态转成异常。

    流式响应走 encoding/json，code 为 0 时字段被省略，故「没有 code」即成功。
    """
    status = chunk.get("status") or {}
    code = status.get("code")
    if code not in (0, None):
        raise KusciaLogError(status.get("message") or f"Kuscia 返回错误码 {code}", 502)
    payload = chunk.get("log") or ""
    # 心跳是一条空 log，不产出任何行。
    return payload.split("\n") if payload else []


async def tail(path: str, lines: int = 500, keyword: str | None = None) -> dict:
    n = _clamp_lines(lines)
    target = _require_path(path)
    out: list[str] = []
    stream = get_kuscia_client().stream_node_log(_payload(target, n, False, keyword))
    try:
        async for chunk in stream:
            out.extend(_chunk_lines(chunk))
    except KusciaError as e:
        raise KusciaLogError(f"读取 Master 日志失败：{e}", 502) from e
    finally:
        await stream.aclose()
    return {
        "path": target,
        "lines": out[-n:],
        "requested_lines": n,
        "truncated": len(out) >= n,
    }


async def iter_lines(
    path: str, lines: int, keyword: str | None = None, follow: bool = True
) -> AsyncIterator[list[str]]:
    """流式产出日志行批次。

    调用方取消时必须关闭本生成器（见 router 的 aclose），否则到 KusciaAPI 的
    连接会一直挂着，节点上的 tail 协程也不会退出。
    """
    n = _clamp_lines(lines)
    target = _require_path(path)
    stream = get_kuscia_client().stream_node_log(_payload(target, n, follow, keyword))
    try:
        async for chunk in stream:
            batch = _chunk_lines(chunk)
            if batch:
                yield batch
    except KusciaError as e:
        raise KusciaLogError(f"读取 Master 日志失败：{e}", 502) from e
    finally:
        await stream.aclose()
