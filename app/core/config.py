"""应用配置（12-factor：环境变量优先，.env 兜底）。"""
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="", extra="ignore", case_sensitive=False
    )

    app_name: str = "Bonfire-TDS Backend"
    api_prefix: str = "/api/v1"
    # API 错误响应不得包含堆栈、SQL、凭据或内部路径；开发时也应显式 DEBUG=true 才开启。
    debug: bool = False
    # 一键切换传输模式：http（开发默认）/ https（生产，经 TLS 反代）。
    transport_mode: str = "http"
    # 旧部署兼容开关；新部署优先设置 TRANSPORT_MODE=https。
    require_https: bool = False

    @property
    def https_enabled(self) -> bool:
        return self.transport_mode.lower() == "https" or self.require_https

    # 数据存储（k3s NodePort，经 127.0.0.1 访问）
    database_url: str = ""
    redis_url: str = ""

    # OPA 使用控制 PDP（k3s NodePort）。OPA 不可用时作业准入失败关闭。
    opa_url: str = ""
    opa_decision_path: str = "bonfire/usage/decision"
    rekor_url: str = ""
    rekor_worker_interval: int = 30

    # 服务平台镜像仓库（开发环境 Harbor HTTP NodePort）。
    platform_registry_enabled: bool = False
    platform_registry: str = ""
    platform_registry_project: str = ""

    # 连接器身份 CA。生产环境应挂载受控目录；开发环境按需生成本地 CA。
    connector_ca_dir: str = ".data/connector-ca"
    # 数字合约用户签名私钥。生产环境必须指向持久化、受限访问的目录。
    signing_key_root: str = ".data/signing-keys"
    connector_certificate_days: int = 365
    connector_portal_image: str = "ghcr.io/bonfire-iie/bonfire-connector-portal:2.0.0"
    connector_seatunnel_image: str = "ghcr.io/bonfire-iie/seatunnel:2.3.8-s3-runtime"
    connector_kuscia_image: str = "ghcr.io/hangzhuanplus/bonfire-kuscia-bundle:1.2.0b0-fs0.1.0"
    connector_platform_api_public_url: str = "http://127.0.0.1:8000/api/v1"
    # TDS 标识码生成用：主体标识码(18位)与区域/行业代码(4位)。org 正式模型建好前用平台占位。
    tds_default_subject_code: str = "91110000000000000X"
    tds_default_region_industry: str = "1101"

    # Keycloak（身份提供方 IdP）
    keycloak_base_url: str = ""
    keycloak_realm: str = "bonfire"
    keycloak_client_id: str = "bonfire-tds"
    keycloak_client_secret: str = ""
    # 服务账号：经 Admin API 建用户（scoped manage-users）
    keycloak_admin_client_id: str = "bonfire-admin"
    keycloak_admin_client_secret: str = ""

    @property
    def keycloak_realm_url(self) -> str:
        return f"{self.keycloak_base_url}/realms/{self.keycloak_realm}"

    # CORS（前端 Vite 默认端口）
    cors_origins: list[str] = []
    # Internal execution channel; disabled until an explicit secret is provisioned.
    execution_auth_mode: str = Field(default="signature", validation_alias=AliasChoices("BONFIRE_EXECUTION_AUTH_MODE", "EXECUTION_AUTH_MODE"))
    execution_dispatch_secret: str = Field(
        default="",
        validation_alias=AliasChoices(
            "EXECUTION_DISPATCH_SECRET",
            "BONFIRE_EXECUTION_DISPATCH_SECRET",
        ),
    )
    # Dispatch runs after the API response; allow extraction and engine setup
    # to complete without tying the timeout to the browser request lifetime.
    pets_scheduler_mode: str = "master-lite"
    kuscia_master_endpoint: str = ""
    kuscia_master_cert_dir: str = ""
    kuscia_master_deploy_endpoint: str = ""
    execution_dispatch_timeout_seconds: float = 600
    execution_status_poll_seconds: float = 2


settings = Settings()
