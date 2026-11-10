import json
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.security.auth import AuthUser, get_current_user
from app.main import app
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiResult,
    AiToolCall,
    ModelRole,
)
from app.modules.assistant.application.ports.providers.image_storage_provider import StoredImage
from app.modules.assistant.infrastructure.api.routers import assistant_router
from app.modules.assistant.infrastructure.services import agent_runtime_factory
from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import (
    DiagramAttributeModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import (
    DiagramRelationModel,
)
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel
from tests.modules.diagram.conftest import create_test_attribute, create_test_class
from tests.modules.assistant.agent_test_helpers import process_and_fetch_message


class FakeCloudinaryProvider:
    async def upload(self, _image_data: bytes, *, public_id: str):
        return StoredImage(
            url="https://res.cloudinary.com/test/image/upload/import.png",
            public_id=public_id,
        )

    async def delete(self, _public_id: str) -> None:
        pass


class ImportProvider:
    def __init__(self):
        self.requests = []
        self.main_calls = 0

    async def complete(self, request):
        self.requests.append(request)
        if request.model_role is ModelRole.PLANNING:
            text = (
                '{"mode":"mutate","needs_image":true,"visual_request":"Importa el ERD completo",'
                '"scope":{"classes":"all","attributes":"all","relations":"all"},'
                '"independent_tasks":[],"clarification":null}'
            )
        elif request.model_role is ModelRole.VISION:
            text = (
                '{"supported":true,"diagram_kind":"ERD",'
                '"classes":['
                '{"name":"Categoria","attributes":[{"name":"id","data_type":"UUID","key_kind":"primary_key"},{"name":"nombre","data_type":"TEXT","key_kind":"ordinary"}]},'
                '{"name":"Producto","attributes":[{"name":"id","data_type":"UUID","key_kind":"primary_key"},{"name":"nombre","data_type":"TEXT","key_kind":"ordinary"},{"name":"id_categoria","data_type":"UUID","key_kind":"foreign_key"}]}],'
                '"relations":[{"source":"Categoria","target":"Producto","relation_type":"ASSOCIATION",'
                '"source_cardinality":"1","target_cardinality":"0..*"}],"uncertainties":[]}'
            )
        else:
            self.main_calls += 1
            if self.main_calls == 1:
                call = AiToolCall(
                    id="create-classes",
                    name="apply_diagram_changes",
                    arguments={
                        "actions": [
                            {"operation_id": "class-category", "kind": "CREATE_CLASS", "name": "Categoria"},
                            {"operation_id": "class-product", "kind": "CREATE_CLASS", "name": "Producto"},
                        ]
                    },
                )
                return AiResult(text="", model_role=request.model_role, model="fake", tool_calls=(call,))
            tool_results = [
                json.loads(message.content)
                for message in request.messages
                if message.role == "tool" and isinstance(message.content, str)
            ]
            confirmed_refs = [
                reference
                for result in tool_results
                for action_result in result.get("results", [])
                for reference in action_result.get("entity_refs", [])
            ]
            class_ids = [item["id"] for item in confirmed_refs if item.get("type") == "class"]
            attribute_ids = [item["id"] for item in confirmed_refs if item.get("type") == "attribute"]
            if self.main_calls == 2:
                call = AiToolCall(
                    id="create-attributes",
                    name="apply_diagram_changes",
                    arguments={
                        "actions": [
                            {"operation_id": "category-name", "kind": "CREATE_ATTRIBUTE", "class_id": class_ids[0], "name": "nombre", "data_type": "TEXT"},
                            {"operation_id": "product-name", "kind": "CREATE_ATTRIBUTE", "class_id": class_ids[1], "name": "nombre", "data_type": "TEXT"},
                        ]
                    },
                )
                assert attribute_ids  # PK IDs were confirmed with their classes.
                return AiResult(text="", model_role=request.model_role, model="fake", tool_calls=(call,))
            if self.main_calls == 3:
                call = AiToolCall(
                    id="create-relation",
                    name="apply_diagram_changes",
                    arguments={
                        "actions": [
                            {
                                "operation_id": "category-product",
                                "kind": "CREATE_RELATION",
                                "relation_type": "ASSOCIATION",
                                "source_class_id": class_ids[0],
                                "target_class_id": class_ids[1],
                                "source_cardinality": "1",
                                "target_cardinality": "0..*",
                            }
                        ]
                    },
                )
                return AiResult(text="", model_role=request.model_role, model="fake", tool_calls=(call,))
            return AiResult(
                text="Se recrearon Categoria y Producto, con su relación 1:N.",
                model_role=request.model_role,
                model="fake",
            )
        return AiResult(text=text, model_role=request.model_role, model="fake")


def test_visual_full_import_uses_confirmed_ids_and_derives_pk_fk_once(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    existing_product = create_test_class(session, test_project.id, name="Producto")
    create_test_attribute(
        session,
        existing_product.id,
        name="id",
        data_type="UUID",
        position=0,
        is_primary_key=True,
        is_nullable=False,
    )
    create_test_attribute(
        session,
        existing_product.id,
        name="descripcion",
        data_type="TEXT",
        position=1,
        is_primary_key=False,
        is_nullable=True,
    )
    unrelated = create_test_class(session, test_project.id, name="Auditoria")
    create_test_attribute(
        session,
        unrelated.id,
        name="id",
        data_type="UUID",
        position=0,
        is_primary_key=True,
        is_nullable=False,
    )
    session.commit()
    provider = ImportProvider()
    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", FakeCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Recrea el ERD completo de la imagen"),
            "image": ("erd.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        },
    )

    response = process_and_fetch_message(
        client=client,
        session=session,
        project_id=test_project.id,
        user_id=owner_user.user_id,
        accepted_response=accepted,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed", response.json()
    classes = session.exec(
        select(DiagramClassModel).where(DiagramClassModel.project_id == test_project.id)
    ).all()
    assert {model.name for model in classes} == {"Categoria", "Producto", "Auditoria"}
    assert next(model for model in classes if model.name == "Producto").id == existing_product.id
    relations = session.exec(
        select(DiagramRelationModel).where(DiagramRelationModel.project_id == test_project.id)
    ).all()
    assert len(relations) == 1
    attributes = session.exec(
        select(DiagramAttributeModel).where(
            DiagramAttributeModel.class_id.in_([model.id for model in classes])
        )
    ).all()
    assert sum(attribute.is_primary_key for attribute in attributes) == 3
    foreign_keys = [attribute for attribute in attributes if attribute.is_foreign_key]
    assert len(foreign_keys) == 1
    assert foreign_keys[0].class_id == next(model.id for model in classes if model.name == "Producto")
    assert foreign_keys[0].referenced_class_id == next(model.id for model in classes if model.name == "Categoria")
    assert {attribute.name for attribute in attributes if not attribute.is_primary_key and not attribute.is_foreign_key} == {"nombre", "descripcion"}
    record = session.get(AgentMessageModel, UUID(response.json()["message_id"]))
    assert record.plan["operation_ledger"]
    assert any(request.model_role is ModelRole.VISION for request in provider.requests)


class ManyToManyImportProvider:
    def __init__(self):
        self.requests = []
        self.main_calls = 0

    async def complete(self, request):
        self.requests.append(request)
        if request.model_role is ModelRole.PLANNING:
            text = (
                '{"mode":"mutate","needs_image":true,"visual_request":"Importa Estudiante y Curso con relación N:M",'
                '"scope":{"classes":"all","attributes":"all","relations":"all"},'
                '"independent_tasks":[],"clarification":null}'
            )
        elif request.model_role is ModelRole.VISION:
            text = (
                '{"supported":true,"diagram_kind":"ERD",'
                '"classes":['
                '{"name":"Estudiante","attributes":[{"name":"id","data_type":"UUID","key_kind":"primary_key"},{"name":"matricula","data_type":"TEXT","key_kind":"ordinary"}]},'
                '{"name":"Curso","attributes":[{"name":"id","data_type":"UUID","key_kind":"primary_key"},{"name":"codigo","data_type":"TEXT","key_kind":"ordinary"}]}],'
                '"relations":[{"source":"Estudiante","target":"Curso","relation_type":"ASSOCIATION",'
                '"source_cardinality":"0..*","target_cardinality":"0..*"}],"uncertainties":[]}'
            )
        else:
            self.main_calls += 1
            if self.main_calls == 1:
                call = AiToolCall(
                    id="create-classes",
                    name="apply_diagram_changes",
                    arguments={
                        "actions": [
                            {"operation_id": "c-est", "kind": "CREATE_CLASS", "name": "Estudiante"},
                            {"operation_id": "c-cur", "kind": "CREATE_CLASS", "name": "Curso"},
                        ]
                    },
                )
                return AiResult(text="", model_role=request.model_role, model="fake", tool_calls=(call,))
            tool_results = [
                json.loads(message.content)
                for message in request.messages
                if message.role == "tool" and isinstance(message.content, str)
            ]
            confirmed_refs = [
                reference
                for result in tool_results
                for action_result in result.get("results", [])
                for reference in action_result.get("entity_refs", [])
            ]
            class_ids = [item["id"] for item in confirmed_refs if item.get("type") == "class"]
            if self.main_calls == 2:
                call = AiToolCall(
                    id="create-relation",
                    name="apply_diagram_changes",
                    arguments={
                        "actions": [
                            {
                                "operation_id": "rel-est-cur",
                                "kind": "CREATE_RELATION",
                                "relation_type": "ASSOCIATION",
                                "source_class_id": class_ids[0],
                                "target_class_id": class_ids[1],
                                "source_cardinality": "0..*",
                                "target_cardinality": "0..*",
                            }
                        ]
                    },
                )
                return AiResult(text="", model_role=request.model_role, model="fake", tool_calls=(call,))
            return AiResult(
                text="Se recrearon Estudiante y Curso con su relación muchos a muchos y clase puente.",
                model_role=request.model_role,
                model="fake",
            )
        return AiResult(text=text, model_role=request.model_role, model="fake")


def test_visual_import_many_to_many_creates_single_bridge_class_and_materialized_keys(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    """US3: Importación visual con relación N:M materializa una sola clase puente y claves derivadas."""
    provider = ManyToManyImportProvider()
    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", FakeCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Importa Estudiante y Curso con relación N:M"),
            "image": ("erd.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        },
    )

    response = process_and_fetch_message(
        client=client,
        session=session,
        project_id=test_project.id,
        user_id=owner_user.user_id,
        accepted_response=accepted,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed", response.json()

    classes = session.exec(
        select(DiagramClassModel).where(
            DiagramClassModel.project_id == test_project.id,
            DiagramClassModel.deleted_date.is_(None),
        )
    ).all()
    class_names = {model.name for model in classes}
    assert "Estudiante" in class_names
    assert "Curso" in class_names
    assert "EstudianteCurso" in class_names  # Clase puente automática

    relations = session.exec(
        select(DiagramRelationModel).where(
            DiagramRelationModel.project_id == test_project.id,
            DiagramRelationModel.deleted_date.is_(None),
        )
    ).all()
    assert len(relations) == 1
    relation = relations[0]
    bridge_class = next(model for model in classes if model.name == "EstudianteCurso")
    assert relation.bridge_class_id == bridge_class.id

    # Comprobar atributos de la clase puente: 1 PK + 2 FKs automáticas
    bridge_attributes = session.exec(
        select(DiagramAttributeModel).where(
            DiagramAttributeModel.class_id == bridge_class.id,
            DiagramAttributeModel.deleted_date.is_(None),
        )
    ).all()
    assert len(bridge_attributes) == 3
    assert sum(1 for a in bridge_attributes if a.is_primary_key) == 1
    assert sum(1 for a in bridge_attributes if a.is_foreign_key) == 2


class StructuralImportProvider:
    def __init__(self):
        self.requests = []
        self.main_calls = 0

    async def complete(self, request):
        self.requests.append(request)
        if request.model_role is ModelRole.PLANNING:
            text = (
                '{"mode":"mutate","needs_image":true,"visual_request":"Importa composición de Casa y Habitación",'
                '"scope":{"classes":"all","attributes":"none","relations":"all"},'
                '"independent_tasks":[],"clarification":null}'
            )
        elif request.model_role is ModelRole.VISION:
            text = (
                '{"supported":true,"diagram_kind":"UML_CLASS",'
                '"classes":['
                '{"name":"Casa","attributes":[]},'
                '{"name":"Habitacion","attributes":[]}],'
                '"relations":[{"source":"Habitacion","target":"Casa","relation_type":"COMPOSITION",'
                '"source_cardinality":null,"target_cardinality":null,"head_class":"Casa"}],'
                '"uncertainties":[]}'
            )
        else:
            self.main_calls += 1
            if self.main_calls == 1:
                call = AiToolCall(
                    id="create-classes",
                    name="apply_diagram_changes",
                    arguments={
                        "actions": [
                            {"operation_id": "c-casa", "kind": "CREATE_CLASS", "name": "Casa"},
                            {"operation_id": "c-hab", "kind": "CREATE_CLASS", "name": "Habitacion"},
                        ]
                    },
                )
                return AiResult(text="", model_role=request.model_role, model="fake", tool_calls=(call,))
            tool_results = [
                json.loads(message.content)
                for message in request.messages
                if message.role == "tool" and isinstance(message.content, str)
            ]
            confirmed_refs = [
                reference
                for result in tool_results
                for action_result in result.get("results", [])
                for reference in action_result.get("entity_refs", [])
            ]
            class_ids = [item["id"] for item in confirmed_refs if item.get("type") == "class"]
            if self.main_calls == 2:
                call = AiToolCall(
                    id="create-relation",
                    name="apply_diagram_changes",
                    arguments={
                        "actions": [
                            {
                                "operation_id": "rel-comp",
                                "kind": "CREATE_RELATION",
                                "relation_type": "COMPOSITION",
                                "source_class_id": class_ids[0],
                                "target_class_id": class_ids[1],
                            }
                        ]
                    },
                )
                return AiResult(text="", model_role=request.model_role, model="fake", tool_calls=(call,))
            return AiResult(
                text="Se recrearon Casa y Habitacion con su composición.",
                model_role=request.model_role,
                model="fake",
            )
        return AiResult(text=text, model_role=request.model_role, model="fake")


def test_visual_import_structural_relation_with_head_class(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    """T017: Importación visual de relación estructural con head_class crea la relación y claves derivadas."""
    provider = StructuralImportProvider()
    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", FakeCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Importa composición de Casa y Habitación"),
            "image": ("uml.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        },
    )

    response = process_and_fetch_message(
        client=client,
        session=session,
        project_id=test_project.id,
        user_id=owner_user.user_id,
        accepted_response=accepted,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed", response.json()

    classes = session.exec(
        select(DiagramClassModel).where(
            DiagramClassModel.project_id == test_project.id,
            DiagramClassModel.deleted_date.is_(None),
        )
    ).all()
    assert {c.name for c in classes} == {"Casa", "Habitacion"}

    relations = session.exec(
        select(DiagramRelationModel).where(
            DiagramRelationModel.project_id == test_project.id,
            DiagramRelationModel.deleted_date.is_(None),
        )
    ).all()
    assert len(relations) == 1
    assert relations[0].relation_type == "COMPOSITION"


class ExcludedRelationsImportProvider:
    def __init__(self):
        self.requests = []
        self.main_calls = 0

    async def complete(self, request):
        self.requests.append(request)
        if request.model_role is ModelRole.PLANNING:
            text = (
                '{"mode":"mutate","needs_image":true,"visual_request":"Importa clases sin relaciones",'
                '"scope":{"classes":"all","attributes":"none","relations":"none"},'
                '"independent_tasks":[],"clarification":null}'
            )
        elif request.model_role is ModelRole.VISION:
            text = (
                '{"supported":true,"diagram_kind":"UML_CLASS",'
                '"classes":['
                '{"name":"Factura","attributes":[]},'
                '{"name":"Item","attributes":[]}],'
                '"relations":[{"source":"Factura","target":"Item","relation_type":"ASSOCIATION",'
                '"source_cardinality":"1","target_cardinality":"0..*"}],'
                '"uncertainties":[]}'
            )
        else:
            self.main_calls += 1
            if self.main_calls == 1:
                call = AiToolCall(
                    id="create-classes",
                    name="apply_diagram_changes",
                    arguments={
                        "actions": [
                            {"operation_id": "c-factura", "kind": "CREATE_CLASS", "name": "Factura"},
                            {"operation_id": "c-item", "kind": "CREATE_CLASS", "name": "Item"},
                        ]
                    },
                )
                return AiResult(text="", model_role=request.model_role, model="fake", tool_calls=(call,))
            return AiResult(
                text="Se crearon Factura e Item sin relaciones.",
                model_role=request.model_role,
                model="fake",
            )
        return AiResult(text=text, model_role=request.model_role, model="fake")


def test_visual_import_with_relations_none_creates_zero_relations(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    """T017: Alcance visual con relations=none crea clases pero 0 relaciones."""
    provider = ExcludedRelationsImportProvider()
    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", FakeCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Importa clases sin relaciones"),
            "image": ("uml.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        },
    )

    response = process_and_fetch_message(
        client=client,
        session=session,
        project_id=test_project.id,
        user_id=owner_user.user_id,
        accepted_response=accepted,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed", response.json()

    relations = session.exec(
        select(DiagramRelationModel).where(
            DiagramRelationModel.project_id == test_project.id,
            DiagramRelationModel.deleted_date.is_(None),
        )
    ).all()
    assert len(relations) == 0


class UnreadableDirectionProvider:
    def __init__(self):
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if request.model_role is ModelRole.PLANNING:
            text = (
                '{"mode":"mutate","needs_image":true,"visual_request":"Importa herencia",'
                '"scope":{"classes":"all","attributes":"none","relations":"all"},'
                '"independent_tasks":[],"clarification":null}'
            )
        elif request.model_role is ModelRole.VISION:
            text = (
                '{"supported":true,"diagram_kind":"UML_CLASS",'
                '"classes":[{"name":"A","attributes":[]},{"name":"B","attributes":[]}],'
                '"relations":[{"source":"A","target":"B","relation_type":"GENERALIZATION",'
                '"source_cardinality":null,"target_cardinality":null,"head_class":null}],'
                '"uncertainties":["No se pudo leer con certeza la dirección de la cabeza de herencia."]}'
            )
        else:
            return AiResult(
                text="No se pudo determinar la dirección de la relación. Por favor aclara cuál es la superclase.",
                model_role=request.model_role,
                model="fake",
            )
        return AiResult(text=text, model_role=request.model_role, model="fake")


def test_visual_import_unreadable_structural_direction_creates_zero_relations(
    monkeypatch,
    client: TestClient,
    session: Session,
    test_project: ProjectModel,
    owner_user: AuthUser,
):
    """T017: Dirección estructural ilegible no genera mutaciones de relación."""
    provider = UnreadableDirectionProvider()
    app.dependency_overrides[get_current_user] = lambda: owner_user
    monkeypatch.setattr(assistant_router, "CloudinaryImageProvider", FakeCloudinaryProvider)
    monkeypatch.setattr(agent_runtime_factory, "QwenAiProvider", lambda: provider)

    accepted = client.post(
        f"/api/projects/{test_project.id}/assistant/messages",
        files={
            "message_id": (None, str(uuid4())),
            "prompt": (None, "Importa herencia"),
            "image": ("uml.png", b"\x89PNG\r\n\x1a\ncontent", "image/png"),
        },
    )

    response = process_and_fetch_message(
        client=client,
        session=session,
        project_id=test_project.id,
        user_id=owner_user.user_id,
        accepted_response=accepted,
    )
    assert response.status_code == 200

    relations = session.exec(
        select(DiagramRelationModel).where(
            DiagramRelationModel.project_id == test_project.id,
            DiagramRelationModel.deleted_date.is_(None),
        )
    ).all()
    assert len(relations) == 0


