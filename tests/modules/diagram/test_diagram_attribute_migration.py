import uuid
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import (
    ProjectModel,
)


def test_diagram_class_deletion_cascades_to_attributes(
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    test_class_with_attributes: DiagramClassModel,
    owner_user: AuthUser,
):
    """Verifica que la eliminación de una clase elimina en cascada todos sus atributos."""
    app.dependency_overrides[get_current_user] = lambda: owner_user
    class_id = test_class_with_attributes.id

    # 1. Verificar que existen atributos asociados a la clase
    attrs_before = session.exec(
        select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == class_id)
    ).all()
    assert len(attrs_before) == 4  # PK + 3 secundarios

    # 2. Eliminar la clase mediante el endpoint de la API
    resp_delete = client.delete(f"/api/diagram/classes/{class_id}")
    assert resp_delete.status_code == 204

    # 3. Confirmar que la clase ya no existe
    cls_after = session.get(DiagramClassModel, class_id)
    assert cls_after is None

    # 4. Confirmar que todos los atributos asociados fueron eliminados en cascada
    attrs_after = session.exec(
        select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == class_id)
    ).all()
    assert len(attrs_after) == 0


def test_database_level_foreign_key_cascade(
    session: Session,
    test_project: ProjectModel,
):
    """Verifica la regla ON DELETE CASCADE a nivel de base de datos relacional."""
    # 1. Crear una clase y atributos directamente en base de datos
    new_class = DiagramClassModel(
        id=uuid.uuid4(),
        project_id=test_project.id,
        name="ClaseCascada",
        position_x=10.0,
        position_y=20.0,
    )
    session.add(new_class)
    session.flush()

    pk_attr = DiagramAttributeModel(
        id=uuid.uuid4(),
        class_id=new_class.id,
        name="id",
        data_type="UUID",
        position=0,
        is_primary_key=True,
        is_nullable=False,
    )
    sec_attr = DiagramAttributeModel(
        id=uuid.uuid4(),
        class_id=new_class.id,
        name="campo",
        data_type="TEXT",
        position=1,
        is_primary_key=False,
        is_nullable=True,
    )
    session.add(pk_attr)
    session.add(sec_attr)
    session.commit()

    # 2. Eliminar la clase directamente de la sesión
    cls_in_db = session.get(DiagramClassModel, new_class.id)
    assert cls_in_db is not None
    session.delete(cls_in_db)
    session.commit()

    # 3. Verificar que los atributos fueron eliminados por el CASCADE de SQLite/Postgres
    remaining = session.exec(
        select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == new_class.id)
    ).all()
    assert len(remaining) == 0
