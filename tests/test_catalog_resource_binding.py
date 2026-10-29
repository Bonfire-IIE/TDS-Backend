from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.schemas.catalog import ResourcePublish
from app.services.catalog import CatalogError, publish_resource


class _FakeDb:
    def __init__(self, connector):
        self.connector = connector
        self.resources = {}
        self.added = []

    def get(self, model, key):
        if model.__name__ == "Connector" and key == self.connector.id:
            return self.connector
        if model.__name__ == "DataCatalog":
            return self.resources.get(key)
        return None

    def scalar(self, _statement):
        return None

    def add(self, value):
        self.added.append(value)

    def flush(self):
        for value in self.added:
            if value.__class__.__name__ == "DataCatalog" and value.id is None:
                value.id = "resource-1"
                self.resources[value.id] = value

    def commit(self):
        return None

    def refresh(self, _value):
        return None


def _body(columns) -> ResourcePublish:
    return ResourcePublish(
        resource_id="connector-resource-1",
        version_no="V1",
        resource_name="dataset",
        resource_abstract="test dataset",
        industry_code="J",
        theme_code="ZA",
        resource_owner_name="Test Org",
        resource_owner_id="ORG-1",
        contact_name="Alice",
        contact_information="13800138000",
        resource_format="CSV",
        data_type="table",
        data_source_type="01",
        update_frequency="不更新",
        personal_information_level="0",
        security_level="general_1",
        data_items=columns,
        datasource_id="datasource-1",
        datasource_name="OSS source",
        datasource_type="oss",
        datasource_uri="http://minio/bucket",
        relative_uri="dataset.csv",
        source_connector_id="connector-1",
    )


def _column(name="id", column_type="string", comment=""):
    return {"name": name, "type": column_type, "comment": comment}


def _database():
    return _FakeDb(SimpleNamespace(id="connector-1", created_by="alice", status="active"))


def test_center_rejects_table_projection_without_columns():
    database = _database()
    with pytest.raises(CatalogError, match="必须提供列定义") as exc_info:
        publish_resource(database, "alice", _body([]))
    assert exc_info.value.status_code == 400
    assert database.added == []


def test_center_publishes_connector_resource_and_creates_generic_binding():
    database = _database()
    with patch("app.services.catalog.gen_data_code", return_value="resource-code"):
        resource = publish_resource(database, "alice", _body([_column()]))

    binding = next(value for value in database.added if value.__class__.__name__ == "DataResourceBinding")
    assert resource.id == "connector-resource-1"
    assert resource.status == "pending_review"
    assert binding.platform_resource_id == resource.id
    assert binding.connector_resource_ref == "connector-resource-1"
    assert binding.sync_status == "synced"
    assert binding.metadata_snapshot["columns"] == [
        {"name": "id", "type": "string", "comment": ""},
    ]
    assert binding.metadata_snapshot["datasource_ref"] == "datasource-1"
    assert binding.metadata_snapshot["format"] == "CSV"


@pytest.mark.parametrize(
    ("column_type", "expected"),
    [("STRING", "string"), ("DECIMAL(12,2)", "decimal(12,2)")],
)
def test_center_normalizes_seatunnel_column_types(column_type, expected):
    database = _database()
    with patch("app.services.catalog.gen_data_code", return_value="resource-code"):
        resource = publish_resource(database, "alice", _body([_column(column_type=column_type)]))
    assert resource.columns == [{"name": "id", "type": expected, "comment": ""}]


def test_center_rejects_non_seatunnel_column_type():
    with pytest.raises(CatalogError, match="str 不受支持"):
        publish_resource(_database(), "alice", _body([_column(column_type="str")]))


@pytest.mark.parametrize(
    ("columns", "message"),
    [
        ([_column(name="  ")], "列名不能为空"),
        ([_column(column_type="  ")], "类型不能为空"),
        ([_column(), _column()], "列名重复"),
    ],
)
def test_center_rejects_invalid_table_columns(columns, message):
    with pytest.raises(CatalogError, match=message):
        publish_resource(_database(), "alice", _body(columns))

@pytest.mark.parametrize('version', [None, '', '0', 'latest'])
def test_publication_without_concrete_version_cannot_be_marked_synced(version):
    database = _database()
    body = _body([_column()]).model_copy(update={'version_no': version})
    with pytest.raises(CatalogError) as exc:
        publish_resource(database, 'alice', body)
    assert exc.value.status_code == 422
    assert not database.added
