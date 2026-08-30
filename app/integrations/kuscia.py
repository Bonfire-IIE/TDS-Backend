"""KusciaAPI 客户端封装（HTTP + mTLS + Token）。

证书取自 Kuscia master 容器 /home/kuscia/var/certs/：
  kusciaapi-server.crt / kusciaapi-server.key / ca.crt / token
中心化模式下作业无审批（Initialized -> Pending -> Running -> Succeeded）。
"""
from __future__ import annotations

import json
import os
import ssl
from functools import lru_cache
from typing import AsyncIterator

import httpx

from app.core.config import settings


class KusciaError(RuntimeError):
    def __init__(self, message: str, *, code: str = "KUSCIA_ERROR", diagnostic: str | None = None):
        super().__init__(message)
        self.code = code
        self.diagnostic = diagnostic


def _kuscia_request_error(exc: httpx.HTTPError) -> KusciaError:
    if isinstance(exc, httpx.TimeoutException):
        return KusciaError("Kuscia Master 响应超时，请检查节点状态和网络", code="KUSCIA_TIMEOUT", diagnostic=repr(exc))
    if isinstance(exc, httpx.ConnectError):
        return KusciaError("无法连接 Kuscia Master，请检查地址、端口和网络", code="KUSCIA_UNREACHABLE", diagnostic=repr(exc))
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return KusciaError("Kuscia Master 拒绝认证，请检查证书和令牌", code="KUSCIA_AUTH_FAILED", diagnostic=repr(exc))
        return KusciaError(f"Kuscia Master 返回异常状态（HTTP {status}）", code="KUSCIA_UPSTREAM_ERROR", diagnostic=repr(exc))
    return KusciaError("Kuscia Master 请求失败", diagnostic=repr(exc))


class ChunkedJsonParser:
    """增量切分 chunked 响应里背靠背的 JSON 对象。

    Kuscia 的流式接口既不换行分隔也不套外层数组，故按 raw_decode 逐个吃掉对象，
    尾部不完整的部分留到下一个 chunk。
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._decoder = json.JSONDecoder()

    def feed(self, chunk: str) -> list[dict]:
        self._buffer += chunk
        out: list[dict] = []
        while True:
            self._buffer = self._buffer.lstrip()
            if not self._buffer:
                break
            try:
                obj, end = self._decoder.raw_decode(self._buffer)
            except ValueError:
                break  # 尾部还不是一个完整对象，等下一个 chunk
            self._buffer = self._buffer[end:]
            out.append(obj)
        return out


class KusciaClient:
    def __init__(self, endpoint: str, cert_dir: str, domain_id: str | None = None) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.domain_id = domain_id
        crt = os.path.join(cert_dir, "kusciaapi-server.crt")
        key = os.path.join(cert_dir, "kusciaapi-server.key")
        ca = os.path.join(cert_dir, "ca.crt")
        token_path = os.path.join(cert_dir, "token")
        with open(token_path) as f:
            token = f.read().strip()
        # 显式 SSLContext：用 Kuscia CA 校验服务端 + 挂载客户端证书(mTLS)。
        # 关闭 hostname 校验——我们经桥接 IP 访问，服务端证书 CN 与 IP 不一致；
        # 服务端证书仍由 CA 强校验，安全性不受影响。
        ssl_ctx = ssl.create_default_context(cafile=ca)
        ssl_ctx.check_hostname = False
        ssl_ctx.load_cert_chain(certfile=crt, keyfile=key)
        # 留存凭据：流式接口要另开一个 AsyncClient（见 stream_node_log）。
        self._ssl_ctx = ssl_ctx
        self._headers = {"Token": token, "Content-Type": "application/json"}
        self._client = httpx.Client(
            base_url=self.endpoint,
            verify=ssl_ctx,
            trust_env=False,
            headers=self._headers,
            timeout=10.0,
        )

    def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = self._client.post(path, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as e:  # 网络/TLS/HTTP 错误
            raise _kuscia_request_error(e) from e
        try:
            data = resp.json()
        except ValueError as e:
            raise KusciaError("Kuscia Master 返回了无法解析的响应", code="KUSCIA_INVALID_RESPONSE", diagnostic=repr(e)) from e
        status = data.get("status", {})
        if status.get("code") not in (0, None):
            raise KusciaError(status.get("message", "kuscia api error"))
        return data

    # ---- Domain（连接器/节点）----
    def query_domain(self, domain_id: str) -> dict:
        return self._post("/api/v1/domain/query", {"domain_id": domain_id})

    def batch_query_domains(self, domain_ids: list[str]) -> list[dict]:
        data = self._post("/api/v1/domain/batchQuery", {"domain_ids": domain_ids})
        return data.get("data", {}).get("domains", [])

    def create_domain(self, domain_id: str, role: str = "") -> None:
        """建 Kuscia Domain（中心化内部节点 role=""）。已存在则幂等忽略。"""
        try:
            self._post("/api/v1/domain/create", {"domain_id": domain_id, "role": role})
        except KusciaError as e:
            if "exist" not in str(e).lower():
                raise

    def delete_domain(self, domain_id: str) -> None:
        self._post("/api/v1/domain/delete", {"domain_id": domain_id})

    def get_deploy_token(self, domain_id: str) -> str | None:
        """取该域未使用的 lite 部署令牌（实时，从不落我们自己的库）。"""
        data = self.query_domain(domain_id).get("data", {})
        for t in data.get("deploy_token_statuses", []) or []:
            if t.get("state") == "unused":
                return t.get("token")
        return None

    def create_domaindata(
        self, domain_id: str, domaindata_id: str, name: str, relative_uri: str,
        columns: list[dict], attributes: dict | None = None,
        datasource_id: str = "default-data-source", vendor: str = "bonfire",
        kuscia_type: str = "table",
    ) -> None:
        """在指定 domain 下登记数据对象元数据（不含真实文件）。

        kuscia_type：table(结构化，带 columns) / unknown(非结构化，columns 传 [])。
        """
        self._post("/api/v1/domaindata/create", {
            "domain_id": domain_id,
            "domaindata_id": domaindata_id,
            "name": name,
            "type": kuscia_type,
            "relative_uri": relative_uri,
            "datasource_id": datasource_id,
            "columns": columns,
            "attributes": {k: str(v) for k, v in (attributes or {}).items()},
            "vendor": vendor,
        })

    def delete_domaindata(self, domain_id: str, domaindata_id: str) -> None:
        self._post("/api/v1/domaindata/delete",
                   {"domain_id": domain_id, "domaindata_id": domaindata_id})

    # ---- DomainDataSource（数据源）----
    # 注意：这些接口只能由 domain 自身的 Lite KusciaAPI 处理（info 需域私钥加密），
    # master 会返回 "master's kuscia api can't operate domain data source"。
    # 故须用 get_kuscia_lite_client(domain_id) 取得对应 Lite 客户端后调用。
    def create_domaindatasource(
        self, domain_id: str, datasource_id: str, ds_type: str, name: str,
        info: dict, access_directly: bool = True,
    ) -> None:
        """在指定 domain 下登记数据源。

        info 按类型二选一：
          localfs -> {"localfs": {"path": "<节点内路径>"}}
          oss     -> {"oss": {"endpoint","bucket","prefix","access_key_id",
                              "access_key_secret","storage_type","virtualhost","version"}}
        """
        self._post("/api/v1/domaindatasource/create", {
            "domain_id": domain_id,
            "datasource_id": datasource_id,
            "type": ds_type,
            "name": name,
            "info": info,
            "access_directly": access_directly,
        })

    def delete_domaindatasource(self, domain_id: str, datasource_id: str) -> None:
        self._post("/api/v1/domaindatasource/delete",
                   {"domain_id": domain_id, "datasource_id": datasource_id})

    # ---- AppImage（应用能力）----
    # AppImage 为集群级资源，由 master 的 KusciaAPI 操作（端口 18081）。
    def create_appimage(
        self, name: str, image_name: str, image_tag: str,
        deploy_templates: list[dict], config_templates: dict | None = None,
    ) -> None:
        """创建 Kuscia AppImage。

        注意扁平结构：containers 直接置于 deploy_template 下（不套 spec），
        字段名 restart_policy（下划线）。
        """
        payload: dict = {
            "name": name,
            "image": {"name": image_name, "tag": image_tag},
            "deploy_templates": deploy_templates,
        }
        if config_templates:
            payload["config_templates"] = config_templates
        self._post("/api/v1/appimage/create", payload)

    def query_appimage(self, name: str) -> dict:
        """查询单个 AppImage，返回 data{name,image,config_templates,deploy_templates}。"""
        return self._post("/api/v1/appimage/query", {"name": name}).get("data", {})

    def delete_appimage(self, name: str) -> None:
        self._post("/api/v1/appimage/delete", {"name": name})

    def update_appimage(self, name: str, image_name: str, image_tag: str,
                        deploy_templates: list[dict], config_templates: dict | None = None) -> None:
        payload: dict = {"name": name, "image": {"name": image_name, "tag": image_tag}, "deploy_templates": deploy_templates}
        if config_templates is not None:
            payload["config_templates"] = config_templates
        self._post("/api/v1/appimage/update", payload)

    def domain_online(self, domain_id: str) -> bool:
        """有就绪工作节点即视为 online。"""
        data = self.query_domain(domain_id).get("data", {})
        return len(data.get("node_statuses", []) or []) > 0

    # ---- ClusterDomainRoute（连接器间通信路由）----
    def create_cluster_route(
        self, src: str, dst: str, dst_host: str, port: int = 1080,
    ) -> None:
        """建立 src -> dst 的单向 ClusterDomainRoute（Token/RSA-GEN，明文 HTTP）。

        dst_host = 对端 Lite 容器名（host 网络下经容器名可达）；port 默认 1080
        （Lite 节点内部网关端口）。路由已存在则幂等忽略。
        """
        try:
            self._post("/api/v1/route/create", {
                "source": src,
                "destination": dst,
                "authentication_type": "Token",
                "endpoint": {
                    "host": dst_host,
                    "ports": [{
                        "name": "http", "port": port,
                        "protocol": "HTTP", "isTLS": False,
                    }],
                },
                "token_config": {"token_gen_method": "RSA-GEN"},
            })
        except KusciaError as e:
            # 已存在（clusterdomainroutes ... already exists）则视为成功
            if "exist" not in str(e).lower():
                raise

    def query_route(self, src: str, dst: str) -> dict | None:
        """查询 src -> dst 的 ClusterDomainRoute，返回 data（dict）。

        路由不存在（not found / not exist）返回 None，其它异常抛出。
        """
        try:
            data = self._post("/api/v1/route/query", {"source": src, "destination": dst})
        except KusciaError as e:
            msg = str(e).lower()
            if "not found" in msg or "not exist" in msg:
                return None
            raise
        return data.get("data")

    def route_status(self, src: str, dst: str) -> str | None:
        """返回 src -> dst 路由状态字符串（如 "Succeeded"）；路由不存在返回 None。"""
        data = self.query_route(src, dst)
        if not data:
            return None
        return (data.get("status") or {}).get("status")

    def delete_route(self, src: str, dst: str) -> None:
        """删除 src -> dst 的 ClusterDomainRoute（幂等：不存在则忽略）。

        用于纠正 endpoint 有误的旧路由：create 幂等，无法更新已存在路由，
        故先删后按正确物理地址重建。
        """
        try:
            self._post("/api/v1/route/delete", {"source": src, "destination": dst})
        except KusciaError as e:
            low = str(e).lower()
            if "not found" not in low and "not exist" not in low:
                raise

    # ---- DomainDataGrant（跨域元数据授权）----
    def create_domaindatagrant(
        self, domain_id: str, domaindata_id: str, grant_domain: str,
    ) -> str | None:
        """把 domain_id 下的 domaindata 授权给 grant_domain（元数据搬运）。

        返回新建授权的 domaindatagrant_id（供后续回收）。
        """
        resp = self._post("/api/v1/domaindatagrant/create", {
            "domain_id": domain_id,
            "domaindata_id": domaindata_id,
            "grant_domain": grant_domain,
        })
        return (resp.get("data") or {}).get("domaindatagrant_id")

    def delete_domaindatagrant(self, domain_id: str, domaindatagrant_id: str) -> None:
        """删除一条 DomainDataGrant。授权不存在（not found）则幂等吞掉，其它抛出。"""
        try:
            self._post("/api/v1/domaindatagrant/delete", {
                "domain_id": domain_id,
                "domaindatagrant_id": domaindatagrant_id,
            })
        except KusciaError as e:
            if "not found" not in str(e).lower():
                raise

    # ---- KusciaJob（隐私计算作业生命周期）----
    def create_job(self, job: dict) -> dict:
        """提交一个 KusciaJob（body 结构见 design/psi-job-reference.json）。"""
        return self._post("/api/v1/job/create", job)

    def query_job(self, job_id: str) -> dict:
        """查询单个作业全量详情，返回 data{job_id,status{state,...},...}。"""
        return self._post("/api/v1/job/query", {"job_id": job_id}).get("data", {})

    def query_job_status(self, job_ids: list[str]) -> list[dict]:
        """批量查询作业状态，返回 [{job_id,status{state,...}}...]。"""
        data = self._post("/api/v1/job/status/batchQuery", {"job_ids": job_ids})
        return data.get("data", {}).get("jobs", [])

    def delete_job(self, job_id: str) -> None:
        self._post("/api/v1/job/delete", {"job_id": job_id})

    # ---- 节点日志 ----
    # /api/v1/log/node/* 只读取「接收请求的这个节点」上的日志，从不转发。用 master
    # 的 KusciaAPI 调用即只能拿到 master 自己的组件日志，看不到任何连接器的日志。
    def list_node_log_files(self, kind: str | None = None) -> dict:
        """列出本节点日志文件，返回 data{domain_id,node_name,run_mode,files[]}。

        kind: component（节点组件日志）/ pod（任务容器日志）/ all，缺省 all。
        """
        payload = {"kind": kind} if kind else {}
        return self._post("/api/v1/log/node/files", payload).get("data", {})

    async def stream_node_log(self, payload: dict) -> AsyncIterator[dict]:
        """流式读取本节点某个日志文件，逐个产出 QueryLogResponse{status,log}。

        Kuscia 以 chunked 回一串**背靠背的 JSON 对象**（无分隔符、也没有外层
        数组），切分见 ChunkedJsonParser。
        """
        parser = ChunkedJsonParser()
        # timeout=None：跟随流本就长时间无数据，任何读超时都会误杀连接。
        async with httpx.AsyncClient(
            base_url=self.endpoint,
            verify=self._ssl_ctx,
            trust_env=False,
            headers=self._headers,
            timeout=None,
        ) as client:
            async with client.stream(
                "POST", "/api/v1/log/node/log/query", json=payload
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise KusciaError(f"KusciaAPI 返回 {resp.status_code}：{body[:500]}")
                async for chunk in resp.aiter_text():
                    for obj in parser.feed(chunk):
                        yield obj

    # ---- 健康探测 ----
    def ping(self) -> bool:
        """能成功查到当前 Master 自身的 Domain 即视为 KusciaAPI 可用。"""
        if not self.domain_id:
            raise KusciaError("未配置 Kuscia Master Domain ID")
        self.query_domain(self.domain_id)
        return True

    def close(self) -> None:
        self._client.close()


def get_kuscia_client() -> KusciaClient:
    """从数据库读取中心平台当前启用的 Master（唯一配置来源）。"""
    try:
        from sqlalchemy import select
        from app.core.db import SessionLocal
        from app.models.kuscia_master import KusciaMaster

        with SessionLocal() as db:
            master = db.scalars(
                select(KusciaMaster)
                .where(
                    KusciaMaster.enabled.is_(True),
                    KusciaMaster.credential_ref.is_not(None),
                )
                .order_by(KusciaMaster.created_at.desc())
            ).first()
            if master and master.credential_ref.startswith("file:"):
                endpoint = f"{master.scheme}://{master.deployment_ip}:{master.api_port}"
                return KusciaClient(
                    endpoint=endpoint,
                    cert_dir=master.credential_ref[5:],
                    domain_id=master.domain_id,
                )
    except Exception as exc:
        raise KusciaError(f"无法读取 Kuscia Master 配置: {exc}") from exc
    raise KusciaError("尚未完成 Kuscia Master 接入，请先完成中心平台初始化向导")


def get_kuscia_master_deploy_endpoint() -> str:
    """返回连接器部署使用的 Master 网关地址（数据库唯一来源）。"""
    try:
        from sqlalchemy import select
        from app.core.db import SessionLocal
        from app.models.kuscia_master import KusciaMaster

        with SessionLocal() as db:
            master = db.scalars(
                select(KusciaMaster)
                .where(KusciaMaster.enabled.is_(True))
                .order_by(KusciaMaster.created_at.desc())
            ).first()
            if master:
                if master.deploy_endpoint:
                    return master.deploy_endpoint.rstrip("/")
                return f"https://{master.deployment_ip}:18080"
    except Exception as exc:
        raise KusciaError(f"无法读取 Kuscia Master 部署地址: {exc}") from exc
    raise KusciaError("尚未配置 Kuscia Master 部署地址")


def kuscia_master_configured() -> bool:
    """健康诊断用：数据库是否存在启用且已上传凭据的 Master。"""
    try:
        from sqlalchemy import select
        from app.core.db import SessionLocal
        from app.models.kuscia_master import KusciaMaster
        with SessionLocal() as db:
            return db.scalars(
                select(KusciaMaster.id).where(
                    KusciaMaster.enabled.is_(True),
                    KusciaMaster.credential_ref.is_not(None),
                ).limit(1)
            ).first() is not None
    except Exception:
        return False


@lru_cache
def get_kuscia_lite_client(domain_id: str, endpoint: str | None = None) -> KusciaClient:
    """取得某连接器(domain)的 Lite KusciaAPI 客户端，用于数据源等只能由 Lite 处理的操作。"""
    endpoint = endpoint or settings.kuscia_lite_endpoints.get(domain_id)
    if not endpoint:
        raise KusciaError(f"未配置连接器 '{domain_id}' 的 Lite KusciaAPI 端点，无法操作数据源")
    cert_dir = os.path.join(settings.kuscia_lite_cert_base, domain_id)
    if not os.path.isfile(os.path.join(cert_dir, "token")):
        raise KusciaError(f"缺少连接器 '{domain_id}' 的 Lite KusciaAPI 证书({cert_dir})")
    return KusciaClient(endpoint=endpoint, cert_dir=cert_dir, domain_id=domain_id)
