from types import SimpleNamespace

import pytest

from app.services.contract import ContractError, request


class NoDatabaseAccess:
    def get(self, *_args, **_kwargs):
        raise AssertionError("管理员拒绝必须发生在读取业务对象之前")


@pytest.mark.parametrize("admin", [True])
def test_admin_cannot_request_data_product(admin):
    body = SimpleNamespace(consumer_connector_id="connector-1")
    with pytest.raises(ContractError, match="管理员不可申请使用数据产品") as exc:
        request(NoDatabaseAccess(), "product-1", "operator", admin, body)
    assert exc.value.status_code == 403
