import pytest

from app.integrations.kuscia import ChunkedJsonParser
from app.services import kuscia_log as svc


class FakeClient:
    """替身 KusciaAPI 客户端：只实现日志相关的两个方法。"""

    def __init__(self, files: dict | None = None, chunks: list[dict] | None = None) -> None:
        self.files = files or {}
        self.chunks = chunks or []
        self.kinds: list[str | None] = []
        self.payloads: list[dict] = []
        self.closed = False

    def list_node_log_files(self, kind=None):
        self.kinds.append(kind)
        return self.files

    async def stream_node_log(self, payload):
        self.payloads.append(payload)
        try:
            for chunk in self.chunks:
                yield chunk
        finally:
            self.closed = True


@pytest.fixture
def patch_client(monkeypatch):
    def _install(client):
        monkeypatch.setattr(svc, "get_kuscia_client", lambda: client)
        return client

    return _install


# ---- chunked JSON 切分 ----

def test_parser_splits_back_to_back_objects():
    parser = ChunkedJsonParser()
    assert parser.feed('{"log":"a"}{"log":"b"}') == [{"log": "a"}, {"log": "b"}]


def test_parser_buffers_partial_object_across_chunks():
    parser = ChunkedJsonParser()
    assert parser.feed('{"log":"a') == []
    assert parser.feed('bc"}') == [{"log": "abc"}]


def test_parser_ignores_braces_inside_strings():
    parser = ChunkedJsonParser()
    payload = '{"log":"{\\"nested\\": 1} and \\\\ trailing"}'
    assert parser.feed(payload) == [{"log": '{"nested": 1} and \\ trailing'}]


def test_parser_handles_byte_at_a_time_input():
    parser = ChunkedJsonParser()
    text = '{"status":{"message":"success"},"log":"x\\ny"}{"log":""}'
    out = []
    for ch in text:
        out.extend(parser.feed(ch))
    assert out == [{"status": {"message": "success"}, "log": "x\ny"}, {"log": ""}]


# ---- 文件清单 ----

def test_list_files_normalizes_protojson_int64_strings(patch_client):
    # protojson 把 int64 序列化成字符串，size/modified_time/restart_count 都要转回整数
    client = patch_client(FakeClient(files={
        "domain_id": "kuscia-system",
        "node_name": "master",
        "run_mode": "master",
        "files": [
            {
                "path": "/home/kuscia/var/logs/kuscia.log", "name": "kuscia.log",
                "kind": "component", "category": "kuscia",
                "size": "2048", "modified_time": "1786000000",
            },
            {
                "path": "/home/kuscia/var/stdout/pods/alice_job_x/psi/0.log",
                "name": "alice_job_x/psi/0.log", "kind": "pod", "category": "pod",
                "size": "10", "modified_time": "0", "rotated": True, "compressed": True,
                "pod": {
                    "namespace": "alice", "pod_name": "job-x", "container": "psi",
                    "restart_count": "2",
                },
            },
        ],
    }))

    out = svc.list_files()

    assert client.kinds == [None]  # all 不该透传成 kind 参数
    assert out["domain_id"] == "kuscia-system"
    component, pod = out["files"]
    assert component["size"] == 2048
    assert component["modified_at"].startswith("2026-")
    assert component["rotated"] is False and component["pod"] is None
    assert pod["pod"]["restart_count"] == 2
    assert pod["compressed"] is True
    # modified_time 为 0（未知）时不编造时间
    assert pod["modified_at"] is None


def test_list_files_passes_kind_through(patch_client):
    client = patch_client(FakeClient(files={"files": []}))
    svc.list_files("component")
    assert client.kinds == ["component"]


def test_list_files_rejects_unknown_kind(patch_client):
    patch_client(FakeClient())
    with pytest.raises(svc.KusciaLogError) as e:
        svc.list_files("../etc")
    assert e.value.status_code == 400


# ---- 尾部拉取 ----

@pytest.mark.anyio
async def test_tail_joins_chunks_and_clamps_lines(patch_client):
    client = patch_client(FakeClient(chunks=[
        {"status": {"message": "success"}, "log": "line1\nline2"},
        {"log": ""},  # 心跳，不产出行
        {"log": "line3"},
    ]))

    out = await svc.tail("/home/kuscia/var/logs/kuscia.log", lines=2)

    assert out["lines"] == ["line2", "line3"]
    assert out["requested_lines"] == 2 and out["truncated"] is True
    assert client.payloads == [{
        "path": "/home/kuscia/var/logs/kuscia.log",
        "tail_lines": 2, "follow": False, "keyword": "",
    }]
    assert client.closed is True


@pytest.mark.anyio
async def test_tail_rejects_relative_path(patch_client):
    patch_client(FakeClient())
    with pytest.raises(svc.KusciaLogError) as e:
        await svc.tail("../certs/ca.crt")
    assert e.value.status_code == 400


@pytest.mark.anyio
async def test_tail_surfaces_kuscia_error_status(patch_client):
    patch_client(FakeClient(chunks=[{"status": {"code": 11404, "message": "no such file"}}]))
    with pytest.raises(svc.KusciaLogError) as e:
        await svc.tail("/home/kuscia/var/logs/nope.log")
    assert "no such file" in e.value.message


# ---- 跟随 ----

@pytest.mark.anyio
async def test_iter_lines_yields_batches_and_skips_heartbeats(patch_client):
    client = patch_client(FakeClient(chunks=[
        {"log": "a\nb"}, {"log": ""}, {"log": "c"},
    ]))

    batches = [b async for b in svc.iter_lines("/home/kuscia/var/logs/kuscia.log", 100, "a")]

    assert batches == [["a", "b"], ["c"]]
    assert client.payloads[0]["follow"] is True
    assert client.payloads[0]["keyword"] == "a"


@pytest.mark.anyio
async def test_iter_lines_closes_upstream_when_consumer_stops(patch_client):
    """提前 aclose 必须传导到上游，否则节点上的 tail 会一直等我们读。"""
    client = patch_client(FakeClient(chunks=[{"log": "a"}, {"log": "b"}]))

    gen = svc.iter_lines("/home/kuscia/var/logs/kuscia.log", 100)
    assert await gen.__anext__() == ["a"]
    await gen.aclose()

    assert client.closed is True
