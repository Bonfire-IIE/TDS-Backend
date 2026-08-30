from types import SimpleNamespace

import pytest

from app.services import project_template as service


class ScalarResult:
    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values)


def test_template_workflow_requires_nodes_and_edges():
    db = SimpleNamespace(scalars=lambda _query: ScalarResult(["registered-app"]))
    with pytest.raises(service.ProjectTemplateError, match="至少包含一个"):
        service.validate_template_workflow(db, {"nodes": [], "edges": []})
    with pytest.raises(service.ProjectTemplateError, match="edges 数组"):
        service.validate_template_workflow(db, {"nodes": [{"app_image": "registered-app"}]})


def test_template_workflow_rejects_unregistered_appimage():
    db = SimpleNamespace(scalars=lambda _query: ScalarResult([]))
    with pytest.raises(service.ProjectTemplateError, match="不存在或已下架"):
        service.validate_template_workflow(db, {"nodes": [{"app_image": "missing-app"}], "edges": []})
