"""数据目录请求/响应模型。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ColumnDef(BaseModel):
    name: str
    type: str = "str"
    comment: str = ""


class ResourceCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = None
    provider_connector_id: str
    # 平台仅承载 1-3 级数据（法律责任硬约束），>3 级后端拒绝
    security_level: str = Field(..., description="数据安全等级(仅允许1-3)，必填")
    # 数据类型：table(结构化，含列定义) / image / text / file / other
    data_type: str = "table"
    resource_category: str | None = None
    source_type: str | None = None
    delivery_form: str | None = None
    update_freq: str | None = None
    quality_level: str | None = None
    service_type: str | None = None
    topic_category: str | None = None
    tags: list[str] | None = None
    columns: list[ColumnDef] = Field(default_factory=list)
    relative_uri: str | None = None
    # 引用平台 DataSource.id；缺省 "default-data-source" 保持原行为
    datasource_id: str = "default-data-source"


class CatalogOut(BaseModel):
    id: str
    tds_code: str | None
    name: str
    description: str | None
    kind: str
    data_type: str
    provider_connector_id: str
    kuscia_domain_id: str
    kuscia_domaindata_id: str | None
    resource_category: str | None
    source_type: str | None
    delivery_form: str | None
    update_freq: str | None
    quality_level: str | None
    security_level: str
    service_type: str | None
    topic_category: str | None
    tags: list | None
    columns: list | None
    relative_uri: str | None
    datasource_id: str
    # 关联数据源展示信息（由服务层按 datasource_id 补充）
    datasource_name: str | None = None
    datasource_type: str | None = None
    datasource_uri: str | None = None
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    deletable: bool = False

    model_config = {"from_attributes": True}


class CodeOption(BaseModel):
    code: str
    name: str


class CodeTableOut(BaseModel):
    table_key: str
    label: str
    options: list[CodeOption]


# ---- 数据源 ----
class DataSourceCreate(BaseModel):
    name: str = Field(..., max_length=128)
    type: str = Field(..., description="localfs | oss")
    connector_id: str
    # localfs：节点内路径；oss：可选描述（未填则由 bucket 推导）
    uri: str | None = None
    # localfs：{"path": "..."}；oss：{endpoint,bucket,prefix,access_key_id,access_key_secret,...}
    info: dict = Field(default_factory=dict)
    access_directly: bool = True


class DataSourceReport(BaseModel):
    """连接器门户上报：数据源已在本地 Lite 创建，仅报送非密元数据供中心引用。"""
    name: str = Field(..., max_length=128)
    type: str = Field(..., description="localfs | oss")
    connector_id: str
    kuscia_datasource_id: str = Field(..., max_length=64)
    uri: str | None = None
    info: dict = Field(default_factory=dict)  # 非密字段；AK/SK 不得上报


class DataSourceOut(BaseModel):
    id: str
    name: str
    type: str
    connector_id: str
    kuscia_domain_id: str
    kuscia_datasource_id: str
    uri: str | None
    info: dict | None
    created_by: str
    created_at: datetime
    scope: str = "custom"
    deletable: bool = True

    model_config = {"from_attributes": True}
