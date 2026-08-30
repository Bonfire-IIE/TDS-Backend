from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.schemas.project_template import ProjectTemplateCreate, ProjectTemplateOut, ProjectTemplateUpdate
from app.services import project_template as svc

router = APIRouter(prefix="/project-templates", tags=["project-templates"])


def wrap(data):
    return {"code": 0, "message": "ok", "data": data}


def guard(fn):
    try:
        return fn()
    except svc.ProjectTemplateError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.get("")
def listing(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return wrap([ProjectTemplateOut.model_validate(row) for row in svc.list_templates(db, user["username"])])


@router.post("", status_code=201)
def create(body: ProjectTemplateCreate, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return wrap(ProjectTemplateOut.model_validate(guard(lambda: svc.create(db, user["username"], body))))


@router.get("/{template_id}")
def detail(template_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return wrap(ProjectTemplateOut.model_validate(guard(lambda: svc.get(db, template_id, user["username"]))))


@router.put("/{template_id}")
def update(template_id: str, body: ProjectTemplateUpdate, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return wrap(ProjectTemplateOut.model_validate(guard(lambda: svc.update(db, template_id, user["username"], body))))


@router.delete("/{template_id}")
def delete(template_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    guard(lambda: svc.delete(db, template_id, user["username"]))
    return wrap({"id": template_id})
