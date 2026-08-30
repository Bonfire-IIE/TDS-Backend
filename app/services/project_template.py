from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppImage, ProjectTemplate
from app.schemas.project_template import ProjectTemplateCreate, ProjectTemplateUpdate


class ProjectTemplateError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def validate_template_workflow(db: Session, workflow: dict) -> None:
    nodes = workflow.get("nodes")
    edges = workflow.get("edges")
    if not isinstance(nodes, list) or not nodes:
        raise ProjectTemplateError("项目模板至少包含一个镜像节点")
    if not isinstance(edges, list):
        raise ProjectTemplateError("项目模板必须包含 edges 数组")
    app_names = {node.get("app_image") for node in nodes if isinstance(node, dict)}
    if None in app_names or len(app_names) == 0:
        raise ProjectTemplateError("每个模板节点都必须配置 app_image")
    registered = set(db.scalars(select(AppImage.name).where(AppImage.name.in_(app_names), AppImage.status == "registered")))
    missing = sorted(app_names - registered)
    if missing:
        raise ProjectTemplateError(f"模板引用了不存在或已下架的 AppImage：{', '.join(missing)}")


def list_templates(db: Session, username: str) -> list[ProjectTemplate]:
    return list(db.scalars(select(ProjectTemplate).where(ProjectTemplate.owner == username).order_by(ProjectTemplate.updated_at.desc())))


def get(db: Session, template_id: str, username: str) -> ProjectTemplate:
    row = db.get(ProjectTemplate, template_id)
    if not row or row.owner != username:
        raise ProjectTemplateError("项目模板不存在或无权访问", 404)
    return row


def create(db: Session, username: str, body: ProjectTemplateCreate) -> ProjectTemplate:
    validate_template_workflow(db, body.workflow)
    row = ProjectTemplate(name=body.name.strip(), description=body.description, workflow=body.workflow, owner=username)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update(db: Session, template_id: str, username: str, body: ProjectTemplateUpdate) -> ProjectTemplate:
    row = get(db, template_id, username)
    if body.workflow is not None:
        validate_template_workflow(db, body.workflow)
        row.workflow = body.workflow
    if body.name is not None:
        row.name = body.name.strip()
    if "description" in body.model_fields_set:
        row.description = body.description
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, template_id: str, username: str) -> None:
    row = get(db, template_id, username)
    db.delete(row)
    db.commit()
