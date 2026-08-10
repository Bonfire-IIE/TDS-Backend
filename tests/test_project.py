import pytest
from app.services.project import ProjectError, compile_job

class Version:
    workflow={
        "max_parallelism":2,
        "nodes":[
            {"id":"prepare","app_image":"app-a","parties":[{"domain_id":"alice","role":"owner"}]},
            {"id":"compute","app_image":"app-b","task_input_config":"{}","parties":[{"domain_id":"alice"},{"domain_id":"bob"}]},
        ],
        "edges":[{"source":"prepare","target":"compute"}],
    }

def test_compile_workflow_dependencies():
    job=compile_job(Version(),"alice")
    assert job["initiator"]=="alice"
    assert len(job["tasks"])==2
    assert job["tasks"][1]["dependencies"]==[job["tasks"][0]["task_id"]]
    assert job["tasks"][1]["app_image"]=="app-b"

def test_task_input_config_is_forwarded_unchanged():
    Version.workflow["nodes"][0]["task_input_config"]='{"opaque":"{{not-a-template}}"}'
    job=compile_job(Version(),"alice")
    assert job["tasks"][0]["task_input_config"]=='{"opaque":"{{not-a-template}}"}'
