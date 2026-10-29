"""数据目录请求/响应模型。"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ColumnDef(BaseModel):
    name: str
    type: str = "string"
    comment: str = ""


class ResourcePublish(BaseModel):
    """连接器提交的标准资源目录投影；不接受任何 Kuscia 字段。"""
    resource_id: str = Field(..., min_length=1, max_length=64)
    resource_code: str | None = Field(None, max_length=80)
    resource_name: str = Field(..., max_length=128)
    resource_abstract: str = Field(..., min_length=1, max_length=1024)
    industry_code: str = Field(..., min_length=1, max_length=1)
    theme_code: str | None = None
    resource_owner_name: str = Field(..., max_length=128)
    resource_owner_id: str = Field(..., max_length=64)
    contact_name: str = Field(..., max_length=10)
    contact_information: str = Field(..., min_length=11, max_length=11)
    resource_format: str = Field(..., max_length=64)
    data_type: Literal["table", "file", "text", "image", "other"]
    data_source_type: Literal["01", "02", "03", "04", "05"]
    data_size: str | None = None
    time_range: str | None = None
    update_frequency: str = Field(..., max_length=16)
    update_method: Literal["全量", "增量"] | None = None
    version_no: str | None = None
    personal_information_level: Literal["0", "1", "2"]
    security_level: Literal["general_1", "general_2", "important"]
    resource_quality: Literal["01", "02", "03", "04"] | None = None
    high_quality_flag: Literal["01", "02", "03"] | None = None
    data_modalities: list[str] = Field(default_factory=list)
    contains_synthetic_data: Literal["01", "02", "03"] | None = None
    ai_readiness: Literal["01", "02", "03", "04"] | None = None
    ai_task_types: list[str] = Field(default_factory=list)
    annotation_info: dict | None = None
    ai_training_authorization: Literal["01", "02", "03", "04"] | None = None
    data_items: list[ColumnDef] = Field(default_factory=list)
    datasource_id: str = Field(..., min_length=1, max_length=64)
    datasource_name: str | None = Field(None, max_length=128)
    datasource_type: Literal["localfs", "oss", "jdbc", "sftp", "ftp"]
    datasource_uri: str | None = Field(None, max_length=512)
    relative_uri: str = Field(..., min_length=1, max_length=512)
    source_connector_id: str

    @model_validator(mode="after")
    def validate_standard_metadata(self):
        from app.resource_standard.metadata import ResourceMetadata
        normalized = ResourceMetadata.parse(self.model_dump()).to_dict()
        for key, value in normalized.items():
            setattr(self, key, value)
        return self

    @field_validator("industry_code")
    @classmethod
    def validate_industry_code(cls, value: str) -> str:
        value = value.upper()
        if not re.fullmatch(r"[A-T]", value):
            raise ValueError("行业分类必须使用 GB/T 4754 门类代码 A-T")
        return value

    @field_validator("theme_code")
    @classmethod
    def validate_theme_code(cls, value: str | None) -> str | None:
        if not value:
            return None
        value = value.upper()
        if not re.fullmatch(r"Z[A-W](?:[A-Z]00)?", value):
            raise ValueError("政务主题分类必须使用 GB/T 21063.4 一级或二级代码")
        return value

    @field_validator("update_frequency")
    @classmethod
    def validate_update_frequency(cls, value: str) -> str:
        value = value.strip()
        if value not in {"不更新", "其他"} and not re.fullmatch(r"[1-9]\d*(?:\.\d+)?次/(?:天|周|月|季度|年)", value):
            raise ValueError("更新频率应为次数/周期（如 1次/月）、不更新或其他")
        return value

    @field_validator("resource_format")
    @classmethod
    def validate_resource_format(cls, value: str) -> str:
        value = value.strip().upper()
        supported = {"CSV", "TSV", "JSON", "JSONL", "PARQUET", "ORC", "TABLE", "XLSX", "BINARY"}
        if value not in supported:
            raise ValueError("资源格式不在平台支持的标准格式中")
        return value


class ResourceBindingReport(BaseModel):
    platform_resource_id: str | None = None
    connector_id: str
    connector_resource_ref: str
    version: str | None = None
    metadata_snapshot: dict | None = None


class CatalogOut(BaseModel):
    id: str
    tds_code: str | None
    name: str
    description: str | None
    kind: str
    data_type: str
    provider_connector_id: str
    resource_category: str | None = None
    industry_code: str = ""
    theme_code: str | None = None
    resource_owner_name: str = ""
    resource_owner_id: str = ""
    contact_name: str = ""
    contact_information: str = ""
    resource_abstract: str = ""
    resource_format: str = ""
    data_size: str | None = None
    time_range: str | None = None
    update_method: str | None = None
    personal_information_level: str = "0"
    resource_quality: str | None = None
    high_quality_flag: str | None = None
    data_modalities: list | None = None
    contains_synthetic_data: str | None = None
    ai_readiness: str | None = None
    ai_task_types: list | None = None
    annotation_info: dict | None = None
    ai_training_authorization: str | None = None
    review_comment: str | None = None
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
    # Connector 发布资源时附带的数据源非敏感快照。
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
