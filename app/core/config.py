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

    # Kuscia Master 地址与凭据引用由运营方在引导页配置并存入数据库；环境变量
    # 只定义后端保存上传凭据的根目录。
    kuscia_credential_root: str = ""
    # 数据源(DomainDataSource)含加密 info，master 无权操作，须经各连接器(domain)自身的
    # Lite KusciaAPI 下发。dev 环境两个 Lite 的 KusciaAPI 经宿主机端口(-k)暴露，
    # 证书/令牌置于 <lite_cert_base>/<domain_id>/ 下（copy 自各 Lite 容器 /home/kuscia/var/certs）。
    kuscia_lite_cert_base: str = ""
    kuscia_lite_endpoints: dict[str, str] = {}
    # Lite 连接器容器名前缀（host 网络下作业路由 endpoint.host 用；用户名前缀取自部署环境）
    kuscia_lite_ctr_prefix: str = ""
    kuscia_master_ctr_name: str = ""

    # Kuscia Master 组件日志（kuscia.log / kusciaapi.log / k3s.log / envoy/*.log 等）
    # 经 master 自身的 KusciaAPI /api/v1/log/node/* 读取，该接口只读本节点，
    # 因此平台侧看不到连接器的日志（连接器日志由连接器门户查看）。
    # 单次拉取行数上限：kuscia.log/k3s.log 可达数百 MB，必须始终按 tail 取尾部。
    kuscia_log_max_lines: int = 5000
    # 连接器部署指引所需（dev 占位，可用环境变量覆盖）
    kuscia_image: str = ""
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


settings = Settings()
