package bonfire.usage

import rego.v1

default decision := {
  "allowed": false,
  "decision": "default_deny",
  "reason": "未命中允许策略",
  "matched_policy_ids": [],
  "obligations": [],
}

contract := data.bonfire.contracts[input.contract_id]

contract_valid if {
  contract.status == "filed"
  input.subject.connector_id == contract.consumer_connector_id
  input.resource.product_id == contract.product_id
}

constraint_ok(c) if {
  time_ok(c)
  count_ok(c)
  environment_ok(c)
}

time_ok(c) if { not c.time_window }
time_ok(c) if {
  after_start(c.time_window)
  before_end(c.time_window)
}
after_start(w) if { w.from == null }
after_start(w) if { input.context.now >= w.from }
before_end(w) if { w.to == null }
before_end(w) if { input.context.now <= w.to }

count_ok(c) if { not c.count }
count_ok(c) if { input.context.used_count < c.count.max }

environment_ok(c) if { not c.exec_env }
environment_ok(c) if { input.context.exec_env == c.exec_env }

matching_allow contains p if {
  contract_valid
  some p in contract.policies
  p.effect == "allow"
  p.actions[input.action]
  constraint_ok(p.constraints)
}

matching_prohibit contains p if {
  contract_valid
  some p in contract.policies
  p.effect == "prohibit"
  p.actions[input.action]
  constraint_ok(p.constraints)
}

decision := {
  "allowed": false,
  "decision": "denied",
  "reason": "命中禁止策略",
  "matched_policy_ids": [p.id | some p in matching_prohibit],
  "obligations": [],
} if { count(matching_prohibit) > 0 }

decision := {
  "allowed": true,
  "decision": "allowed",
  "reason": "数字合约允许本次使用",
  "matched_policy_ids": [p.id | some p in matching_allow],
  "obligations": [o | some p in matching_allow; some o in p.obligations],
} if {
  count(matching_allow) > 0
  count(matching_prohibit) == 0
}
