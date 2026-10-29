from types import SimpleNamespace

import pytest

from app.services.appimage import AppImageError, _party_role_names, _validate_role_contract


def app_contract(*, input_role: str):
    return SimpleNamespace(
        party_schema={"roles": [{"name":"sender","title":"发送方"},{"name":"recver","title":"接收方"}]},
        deploy_templates=[{"role": "sender"}, {"role": "recver"}],
        io_schema={"inputs": [{"name": "source", "title":"输入数据", "role": input_role}], "outputs": []},
    )


def test_string_party_roles_are_supported():
    assert _party_role_names({"roles": ["sender", "recver"]}) == {"sender", "recver"}
    _validate_role_contract(app_contract(input_role="sender"))


def test_io_port_cannot_reference_undeclared_party_role():
    with pytest.raises(AppImageError, match="未声明的参与方角色: provider"):
        _validate_role_contract(app_contract(input_role="provider"))


def test_new_definitions_require_readable_titles():
    body=app_contract(input_role='sender')
    body.io_schema['inputs'][0].pop('title')
    with pytest.raises(AppImageError,match='可读名称'):_validate_role_contract(body)
    body.io_schema['inputs'][0]['title']='输入'
    body.party_schema={'roles':['sender','recver']}
    with pytest.raises(AppImageError,match='可读名称'):_validate_role_contract(body)
