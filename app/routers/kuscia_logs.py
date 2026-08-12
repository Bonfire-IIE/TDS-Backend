"""Kuscia Master 日志接口：文件枚举、尾部拉取、SSE 实时跟随、导出。

只覆盖 Master 自己的日志（原因见 app/services/kuscia_log.py 模块注释），
故路径里不再带节点标识。
"""
from __future__ import annotations

import asyncio
import contextlib
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from app.core.security import require_roles
from app.services import kuscia_log as svc

router = APIRouter(prefix="/logs", tags=["logs"])

# 组件日志含 KusciaAPI 请求详情、内部地址与证书路径，仅运营方/监管方可读
_reader = require_roles("operator", "supervisor")

# 无日志产出时的保活间隔：SSE 长时间静默会被中间代理判定为死连接
_HEARTBEAT_SECONDS = 15.0


def _wrap(data) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def _http(e: svc.KusciaLogError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/files")
def list_files(
    kind: str | None = Query(None, description="component | pod | all"),
    user: dict = Depends(_reader),
) -> dict:
    try:
        return _wrap(svc.list_files(kind))
    except svc.KusciaLogError as e:
        raise _http(e) from e


@router.get("/tail")
async def tail(
    file: str = Query(..., description="节点上的日志文件绝对路径"),
    lines: int = Query(500, ge=1, le=5000),
    keyword: str | None = Query(None, description="大小写不敏感子串过滤"),
    user: dict = Depends(_reader),
) -> dict:
    try:
        return _wrap(await svc.tail(file, lines, keyword))
    except svc.KusciaLogError as e:
        raise _http(e) from e


async def _sse_events(file: str, lines: int, keyword: str | None):
    """把日志行批次转成 SSE 帧，静默时补心跳。

    用队列而非直接 async for：需要在"等日志"和"发心跳"之间取舍，
    单纯迭代无法在无输出时插入保活帧。
    """
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue(maxsize=256)
    batches = svc.iter_lines(file, lines, keyword)

    async def produce() -> None:
        try:
            async for batch in batches:
                await queue.put(("lines", batch))
        except asyncio.CancelledError:
            raise
        except svc.KusciaLogError as exc:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(("error", exc.message))
        except Exception as exc:  # 读取中断（KusciaAPI 重启/连接异常）需要送达前端
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(("error", str(exc)))
        finally:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(("end", None))

    task = asyncio.create_task(produce())
    try:
        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if kind == "lines":
                yield f"data: {json.dumps({'lines': payload}, ensure_ascii=False)}\n\n"
            elif kind == "error":
                yield f"event: error\ndata: {json.dumps({'message': payload}, ensure_ascii=False)}\n\n"
            else:
                yield "event: end\ndata: {}\n\n"
                return
    finally:
        # 取消生产任务并关闭生成器，让到 KusciaAPI 的连接立刻断开——否则节点上
        # 的 tail 协程会一直等我们读，直到连接超时才退出。
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
        with contextlib.suppress(BaseException):
            await batches.aclose()


@router.get("/stream")
async def stream(
    file: str = Query(..., description="节点上的日志文件绝对路径"),
    lines: int = Query(200, ge=1, le=5000, description="建立连接时先回放的尾部行数"),
    keyword: str | None = Query(None),
    user: dict = Depends(_reader),
) -> StreamingResponse:
    return StreamingResponse(
        _sse_events(file, lines, keyword),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # nginx 默认缓冲响应体，会让实时日志攒够缓冲区才下发
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/download")
async def download(
    file: str = Query(..., description="节点上的日志文件绝对路径"),
    lines: int = Query(5000, ge=1, le=5000),
    user: dict = Depends(_reader),
) -> Response:
    try:
        data = await svc.tail(file, lines)
    except svc.KusciaLogError as e:
        raise _http(e) from e
    filename = f"master-{data['path'].rsplit('/', 1)[-1]}"
    return Response(
        content="\n".join(data["lines"]),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
