from types import SimpleNamespace

from app.services.contract import list_contracts


class FakeSession:
    def __init__(self, contracts, connectors):
        self.results = [iter(contracts), iter(connectors)]

    def scalars(self, _statement):
        return self.results.pop(0)


def _contract(contract_id, created_by, *entity_ids):
    return SimpleNamespace(
        contract_id=contract_id,
        created_by=created_by,
        document={"contractInfo": {"signatoryEntities": [
            {"signatoryEntityId": entity_id} for entity_id in entity_ids
        ]}},
    )


def test_provider_can_list_contract_created_by_consumer():
    provider = SimpleNamespace(id="provider-id", tds_code="provider-code")
    visible = _contract("visible", "consumer-user", "provider-code", "consumer-code")
    unrelated = _contract("unrelated", "other-user", "other-provider", "other-consumer")

    result = list_contracts(FakeSession([visible, unrelated], [provider]), "provider-user", False)

    assert [contract.contract_id for contract in result] == ["visible"]


def test_creator_can_list_contract_without_connector_identity():
    created = _contract("created", "consumer-user", "provider-code", "consumer-code")

    result = list_contracts(FakeSession([created], []), "consumer-user", False)

    assert [contract.contract_id for contract in result] == ["created"]
