"""应用配置（12-factor：环境变量优先，.env 兜底）。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="", extra="ignore", case_sensitive=False
    )

    app_name: str = "Bonfire-TDS Backend"
    api_prefix: str = "/api/v1"
    debug: bool = True

    # 数据存储（k3s NodePort，经 127.0.0.1 访问）
    database_url: str = "postgresql+psycopg://bonfire:bonfire_dev_pw@127.0.0.1:30432/bonfire_tds"
    redis_url: str = "redis://127.0.0.1:30379/0"

    # OPA 使用控制 PDP（k3s NodePort）。OPA 不可用时作业准入失败关闭。
    opa_url: str = "http://127.0.0.1:30818"
    opa_decision_path: str = "bonfire/usage/decision"

    # 服务平台镜像仓库（开发环境 Harbor HTTP NodePort）。
    platform_registry: str = "10.26.174.75:30002"
    platform_registry_project: str = "bonfire"

    # Kuscia KusciaAPI（HTTP + mTLS + Token）——master 经 center 模式发布到宿主机 18081
    kuscia_api_endpoint: str = "https://127.0.0.1:18081"
    kuscia_cert_dir: str = "./secrets/kuscia"
    # 数据源(DomainDataSource)含加密 info，master 无权操作，须经各连接器(domain)自身的
    # Lite KusciaAPI 下发。dev 环境两个 Lite 的 KusciaAPI 经宿主机端口(-k)暴露，
    # 证书/令牌置于 <lite_cert_base>/<domain_id>/ 下（copy 自各 Lite 容器 /home/kuscia/var/certs）。
    kuscia_lite_cert_base: str = "./secrets/kuscia/lite"
    kuscia_lite_endpoints: dict[str, str] = {
        "alice": "https://127.0.0.1:28081",
        "bob": "https://127.0.0.1:38081",
    }
    # M0 已知节点（后续由 connector 模块从 DB 动态获取）
    kuscia_domains: list[str] = ["kuscia-system", "alice", "bob"]
    # Lite 连接器容器名前缀（host 网络下作业路由 endpoint.host 用；用户名前缀取自部署环境）
    kuscia_lite_ctr_prefix: str = "chenxudong-kuscia-lite-"
    # 连接器部署指引所需（dev 占位，可用环境变量覆盖）
    kuscia_image: str = "secretflow-registry.cn-hangzhou.cr.aliyuncs.com/secretflow/kuscia:1.2.0b0"
    # 连接器主机访问 master 的地址：master 的节点认证端口(容器内 1080)已发布到宿主机 18080，
    # 经宿主机可路由 IP 对外，支持跨机连接器接入。跨网段时改为对连接器可达的地址。
    kuscia_master_deploy_endpoint: str = "https://10.26.174.75:18080"
    # TDS 标识码生成用：主体标识码(18位)与区域/行业代码(4位)。org 正式模型建好前用平台占位。
    tds_default_subject_code: str = "91110000000000000X"
    tds_default_region_industry: str = "1101"

    # Keycloak（身份提供方 IdP）
    keycloak_base_url: str = "http://127.0.0.1:30880"
    keycloak_realm: str = "bonfire"
    keycloak_client_id: str = "bonfire-tds"
    keycloak_client_secret: str = "bonfire-tds-secret"
    # 服务账号：经 Admin API 建用户（scoped manage-users）
    keycloak_admin_client_id: str = "bonfire-admin"
    keycloak_admin_client_secret: str = "bonfire-admin-secret"

    @property
    def keycloak_realm_url(self) -> str:
        return f"{self.keycloak_base_url}/realms/{self.keycloak_realm}"

    # CORS（前端 Vite 默认端口）
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


settings = Settings()
