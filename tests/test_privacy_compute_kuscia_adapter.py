import json

from app.integrations.privacy_compute.kuscia import KusciaPrivacyComputeAdapter


class _Client:
    def query_job(self, job_id):
        return {
            "job_id": job_id,
            "tasks": [{
                "parties": [{"domain_id": "provider"}, {"domain_id": "consumer"}],
                "task_input_config": json.dumps({
                    "sf_output_ids": ["output-1", "output-1"],
                    "sf_output_uris": ["output-1.orc", "output-1.orc"],
                }),
            }],
        }


def test_platform_column_types_are_translated_at_adapter_boundary():
    assert KusciaPrivacyComputeAdapter._columns_for_execution_system([
        {"name": "fingerprint_hash", "type": "string", "comment": ""},
        {"name": "score", "type": "double"},
    ]) == [
        {"name": "fingerprint_hash", "type": "str", "comment": ""},
        {"name": "score", "type": "float64"},
    ]


def test_result_exposes_generic_deduplicated_output_bindings():
    result = KusciaPrivacyComputeAdapter(client=_Client()).result({}, "run-1")

    assert result == {
        "external_run_ref": "run-1",
        "outputs": [{
            "resource_ref": "output-1",
            "uri": "output-1.orc",
            "format": "orc",
            "parties": ["provider", "consumer"],
        }],
    }
