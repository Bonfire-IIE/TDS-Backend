"""Standard catalog description of a data resource (数据目录描述要求 附录A 表A.1)."""
from dataclasses import asdict, dataclass, field
from datetime import date
import re
from typing import Any, Mapping

from . import standard
from .errors import ValidationFailed

_FREQUENCY = re.compile(r"[1-9]\d*(?:\.\d+)?次/(?:" + "|".join(standard.UPDATE_FREQUENCY_UNITS) + ")")
_TIME_RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})至(\d{4}-\d{2}-\d{2})")
_PHONE = re.compile(r"\d{11}")


def _text(raw: Mapping[str, Any], name: str, limit: int, *, required: bool = True) -> str | None:
    value = raw.get(name)
    value = "" if value is None else str(value).strip()
    if not value:
        if required:
            raise ValidationFailed("required", field=name)
        return None
    if len(value) > limit:
        raise ValidationFailed("too_long", field=name)
    return value


def _code(raw: Mapping[str, Any], name: str, table, *, required: bool = True) -> str | None:
    value = raw.get(name)
    if value in (None, ""):
        if required:
            raise ValidationFailed("required", field=name)
        return None
    value = str(value).strip()
    if value not in table:
        raise ValidationFailed("not_in_code_table", field=name)
    return value


def _codes(raw: Mapping[str, Any], name: str, allowed: list[str]) -> tuple[str, ...]:
    value = raw.get(name) or []
    if not isinstance(value, (list, tuple)):
        raise ValidationFailed("must_be_list", field=name)
    result: list[str] = []
    for item in value:
        item = str(item).strip()
        if item not in allowed:
            raise ValidationFailed("not_in_code_table", field=name)
        if item not in result:
            result.append(item)
    return tuple(result)


def _industry(raw: Mapping[str, Any]) -> str:
    value = str(raw.get("industry_code") or "").strip().upper()
    if not value:
        raise ValidationFailed("required", field="industry_code")
    if value not in standard.INDUSTRIES:
        raise ValidationFailed("not_in_code_table", field="industry_code")
    return value


def _theme(raw: Mapping[str, Any]) -> str | None:
    value = str(raw.get("theme_code") or "").strip().upper()
    if not value:
        return None
    if standard.theme_name(value) is None:
        raise ValidationFailed("not_in_code_table", field="theme_code")
    return value


def _frequency(raw: Mapping[str, Any]) -> str:
    value = _text(raw, "update_frequency", 10)
    if value not in standard.UPDATE_FREQUENCY_FIXED and not _FREQUENCY.fullmatch(value):
        raise ValidationFailed("invalid_format", field="update_frequency")
    return value


def _time_range(raw: Mapping[str, Any]) -> str | None:
    value = _text(raw, "time_range", 32, required=False)
    if value is None:
        return None
    match = _TIME_RANGE.fullmatch(value)
    try:
        start, end = (date.fromisoformat(part) for part in match.groups())
    except (AttributeError, ValueError):
        raise ValidationFailed("invalid_format", field="time_range") from None
    if start > end:
        raise ValidationFailed("invalid_range", field="time_range")
    return value


def _annotation(raw: Mapping[str, Any]) -> dict | None:
    value = raw.get("annotation_info")
    if value in (None, {}):
        return None
    if not isinstance(value, Mapping):
        raise ValidationFailed("must_be_object", field="annotation_info")
    unknown = set(value) - {"status", "types", "scale", "quality"}
    if unknown:
        raise ValidationFailed("unknown_property", field="annotation_info")
    result = {
        "status": _code(value, "status", standard.ANNOTATION_STATUSES),
        "types": list(_codes(value, "types", standard.ANNOTATION_TYPES)),
        "scale": _text(value, "scale", 64, required=False),
        "quality": _text(value, "quality", 128, required=False),
    }
    if result["status"] == "none" and result["types"]:
        raise ValidationFailed("types_require_annotation", field="annotation_info")
    return result


@dataclass(frozen=True)
class ResourceMetadata:
    """Validated, normalized catalog fields.  Field names follow the center contract."""

    resource_name: str
    resource_abstract: str
    industry_code: str
    resource_owner_name: str
    resource_owner_id: str
    contact_name: str
    contact_information: str
    data_type: str
    data_source_type: str
    update_frequency: str
    security_level: str
    personal_information_level: str
    theme_code: str | None = None
    update_method: str | None = None
    data_size: str | None = None
    time_range: str | None = None
    resource_quality: str | None = None
    high_quality_flag: str | None = None
    data_modalities: tuple[str, ...] = field(default_factory=tuple)
    contains_synthetic_data: str | None = None
    ai_readiness: str | None = None
    ai_task_types: tuple[str, ...] = field(default_factory=tuple)
    annotation_info: dict | None = None
    ai_training_authorization: str | None = None

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> "ResourceMetadata":
        if not isinstance(raw, Mapping):
            raise ValidationFailed("must_be_object", field="metadata")
        contact = _text(raw, "contact_information", 11)
        if not _PHONE.fullmatch(contact):
            raise ValidationFailed("invalid_format", field="contact_information")
        return cls(
            resource_name=_text(raw, "resource_name", 128),
            resource_abstract=_text(raw, "resource_abstract", 1024),
            industry_code=_industry(raw),
            resource_owner_name=_text(raw, "resource_owner_name", 128),
            resource_owner_id=_text(raw, "resource_owner_id", 64),
            contact_name=_text(raw, "contact_name", 10),
            contact_information=contact,
            data_type=_code(raw, "data_type", standard.DATA_TYPES),
            data_source_type=_code(raw, "data_source_type", standard.DATA_SOURCE_TYPES),
            update_frequency=_frequency(raw),
            security_level=_code(raw, "security_level", standard.SECURITY_LEVELS),
            personal_information_level=_code(raw, "personal_information_level",
                                             standard.PERSONAL_INFORMATION_LEVELS),
            theme_code=_theme(raw),
            update_method=_code(raw, "update_method", standard.UPDATE_METHODS, required=False),
            data_size=_text(raw, "data_size", 128, required=False),
            time_range=_time_range(raw),
            resource_quality=_code(raw, "resource_quality", standard.RESOURCE_QUALITY, required=False),
            high_quality_flag=_code(raw, "high_quality_flag", standard.HIGH_QUALITY_FLAGS, required=False),
            data_modalities=_codes(raw, "data_modalities", standard.DATA_MODALITIES),
            contains_synthetic_data=_code(raw, "contains_synthetic_data", standard.SYNTHETIC_DATA,
                                          required=False),
            ai_readiness=_code(raw, "ai_readiness", standard.AI_READINESS, required=False),
            ai_task_types=_codes(raw, "ai_task_types", standard.AI_TASK_TYPES),
            annotation_info=_annotation(raw),
            ai_training_authorization=_code(raw, "ai_training_authorization",
                                            standard.AI_TRAINING_AUTHORIZATION, required=False),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["data_modalities"] = list(self.data_modalities)
        value["ai_task_types"] = list(self.ai_task_types)
        return value
