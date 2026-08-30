from types import SimpleNamespace
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

class FakeDB:
    def scalar(self, _stmt):
        return SimpleNamespace(task_input_template=None)

def test_compile_workflow_dependencies():
    job,_=compile_job(FakeDB(),Version(),"alice","project-1","run-1")
    assert job["initiator"]=="alice"
    assert len(job["tasks"])==2
    assert job["tasks"][1]["dependencies"]==[job["tasks"][0]["alias"]]
    assert job["tasks"][1]["app_image"]=="app-b"

def test_task_input_config_is_forwarded_unchanged():
    Version.workflow["nodes"][0]["task_input_config"]='{"opaque":"{{not-a-template}}"}'
    job,_=compile_job(FakeDB(),Version(),"alice","project-1","run-1")
    assert job["tasks"][0]["task_input_config"]=='{"opaque":"{{not-a-template}}"}'
