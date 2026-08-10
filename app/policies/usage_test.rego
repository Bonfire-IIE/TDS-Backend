package bonfire.usage_test

import rego.v1
import data.bonfire.usage

base_contract := {
  "status": "filed", "product_id": "product-1",
  "consumer_connector_id": "consumer-1",
  "policies": [{
    "id": "allow-1", "effect": "allow", "actions": {"process": true},
    "constraints": {"count": {"max": 2}, "exec_env": "mpc"}, "obligations": [],
  }],
}

base_input := {
  "contract_id": "contract-1", "action": "process",
  "subject": {"connector_id": "consumer-1"},
  "resource": {"product_id": "product-1"},
  "context": {"now": 1784160000, "used_count": 0, "exec_env": "mpc"},
}

test_allow if {
  result := usage.decision with input as base_input with data.bonfire.contracts as {"contract-1": base_contract}
  result.allowed
}

test_count_denied if {
  result := usage.decision with input as object.union(base_input, {"context": {"now": 1784160000, "used_count": 2, "exec_env": "mpc"}}) with data.bonfire.contracts as {"contract-1": base_contract}
  not result.allowed
}

test_prohibit_wins if {
  prohibited := object.union(base_contract, {"policies": array.concat(base_contract.policies, [{"id": "deny-1", "effect": "prohibit", "actions": {"process": true}, "constraints": {}, "obligations": []}])})
  result := usage.decision with input as base_input with data.bonfire.contracts as {"contract-1": prohibited}
  result.decision == "denied"
}
