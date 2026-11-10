from uuid import uuid4
import json

from sqlmodel import Session

from app.modules.assistant.application.services.diagram.diagram_mutation_tools import (
    DiagramMutationTools,
)
from app.modules.assistant.application.services.diagram.diagram_read_tools import DiagramReadTools
from app.modules.assistant.application.services.execution.tool_registry import ToolRegistry
from app.shared.infrastructure.event_bus_impl import InMemoryEventBus
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork
from app.modules.collaboration.application.services.project_access_policy import (
    ProjectAccessPolicy,
)
from app.modules.collaboration.infrastructure.persistence.repositories.sqlmodel_project_member_repository import (
    SQLModelProjectMemberRepository,
)
from app.modules.diagram.application.queries.diagram.agent_diagram_queries import (
    AgentDiagramQueryHandler,
    GetAgentDiagramElementQuery,
    SearchAgentDiagramQuery,
)
from app.modules.diagram.application.services.diagram_access_policy import (
    DiagramAccessPolicy,
)
from app.modules.diagram.domain.exceptions import DiagramWriteForbiddenException
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.readers.sqlmodel_agent_diagram_reader import (
    SQLModelAgentDiagramReader,
)
from app.modules.projects.infrastructure.persistence.repositories.sqlmodel_project_repository import (
    SQLModelProjectRepository,
)
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel
from tests.modules.diagram.conftest import (
    create_test_attribute,
    create_test_class,
    create_test_relation,
)


def _handler(session: Session) -> AgentDiagramQueryHandler:
    project_repo = SQLModelProjectRepository(session)
    member_repo = SQLModelProjectMemberRepository(session)
    access = ProjectAccessPolicy(
        project_repository=project_repo,
        project_member_repository=member_repo,
    )
    return AgentDiagramQueryHandler(
        DiagramAccessPolicy(
            project_repository=project_repo,
            project_member_repository=member_repo,
            project_access_policy=access,
        ),
        SQLModelAgentDiagramReader(session),
    )


def test_search_is_project_scoped_stable_and_paginated(session, test_project, owner_user):
    alpha = create_test_class(session, test_project.id, name="Producto")
    beta = create_test_class(session, test_project.id, name="Producto")
    other_project_id = uuid4()
    session.add(
        ProjectModel(
            id=other_project_id,
            owner_id=owner_user.user_id,
            name="Otro proyecto",
            description="Proyecto aislado de prueba",
        )
    )
    session.flush()
    other_project_class = create_test_class(session, other_project_id, name="Producto")
    session.commit()

    handler = _handler(session)
    first = handler.search(
        SearchAgentDiagramQuery(
            project_id=test_project.id,
            user_id=owner_user.user_id,
            query="producto",
            types=("class",),
            limit=1,
            offset=0,
        )
    )
    second = handler.search(
        SearchAgentDiagramQuery(
            project_id=test_project.id,
            user_id=owner_user.user_id,
            query="producto",
            types=("class",),
            limit=1,
            offset=1,
        )
    )

    assert len(first.items) == 1
    assert first.has_more is True
    assert first.next_offset == 1
    assert len(second.items) == 1
    assert second.items[0].id != first.items[0].id
    assert {first.items[0].id, second.items[0].id} == {alpha.id, beta.id}
    assert other_project_class.id not in {first.items[0].id, second.items[0].id}


def test_class_detail_is_aggregated_and_excludes_soft_deleted_elements(
    session, test_project, owner_user
):
    from datetime import datetime, timezone

    model = create_test_class(session, test_project.id, name="Orden")
    visible = create_test_attribute(session, model.id, name="codigo", position=1, is_primary_key=False)
    deleted = create_test_attribute(session, model.id, name="secreto", position=2, is_primary_key=False)
    deleted.deleted_date = datetime.now(timezone.utc)
    session.add(deleted)
    session.commit()

    result = _handler(session).get(
        GetAgentDiagramElementQuery(
            project_id=test_project.id,
            user_id=owner_user.user_id,
            element_type="class",
            element_id=model.id,
        )
    )

    assert result is not None
    assert [item["id"] for item in result.details["attributes"]] == [str(visible.id)]
    assert not session.new
    assert not session.dirty
    assert not session.deleted


def test_read_tool_binds_actor_server_side_and_never_accepts_actor_arguments(
    session, test_project, owner_user
):
    item = create_test_class(session, test_project.id, name="Factura")
    session.commit()
    registry = ToolRegistry()
    DiagramReadTools(
        _handler(session), project_id=test_project.id, user_id=owner_user.user_id
    ).register(registry)

    result = _run(registry.execute("get_diagram_element", {"type": "class", "id": str(item.id)}))
    assert result["id"] == str(item.id)

    import pytest
    from app.modules.assistant.domain.exceptions import AgentToolArgumentsException

    with pytest.raises(AgentToolArgumentsException):
        _run(
            registry.execute(
                "get_diagram_element",
                {
                    "type": "class",
                    "id": str(item.id),
                    "project_id": str(uuid4()),
                    "user_id": "attacker",
                },
            )
        )


def test_search_tool_uses_opaque_cursor_and_reports_duplicate_names(
    session, test_project, owner_user
):
    create_test_class(session, test_project.id, name="Inventario")
    create_test_class(session, test_project.id, name="Inventario")
    session.commit()
    registry = ToolRegistry()
    DiagramReadTools(
        _handler(session), project_id=test_project.id, user_id=owner_user.user_id
    ).register(registry)

    first = _run(
        registry.execute(
            "search_diagram_elements",
            {"query": "Inventario", "types": ["class"], "limit": 1},
        )
    )
    second = _run(
        registry.execute(
            "search_diagram_elements",
            {
                "query": "Inventario",
                "types": ["class"],
                "limit": 1,
                "cursor": first["next_cursor"],
            },
        )
    )
    all_matches = _run(
        registry.execute(
            "search_diagram_elements",
            {"query": "Inventario", "types": ["class"], "limit": 50},
        )
    )

    assert first["has_more"] is True
    assert first["status"] == "ambiguous"
    assert first["ambiguous"] is True
    assert second["items"][0]["id"] != first["items"][0]["id"]
    assert all_matches["status"] == "ambiguous"
    assert all_matches["ambiguous"] is True


def test_large_class_and_relation_details_are_bounded_and_mark_truncation(
    session, test_project, owner_user
):
    class_model = create_test_class(session, test_project.id, name="Clase extensa")
    target = create_test_class(session, test_project.id, name="Destino")
    for position in range(1, 31):
        create_test_attribute(
            session,
            class_model.id,
            name=f"atributo_{position}_" + "x" * 180,
            data_type="TEXT",
            position=position,
            is_primary_key=False,
            is_nullable=True,
        )
    relations = [
        create_test_relation(
            session,
            test_project.id,
            class_model.id,
            target.id,
            name=f"relación_{index}",
        )
        for index in range(30)
    ]
    relation = relations[0]
    for position in range(1, 31):
        create_test_attribute(
            session,
            class_model.id,
            name=f"foreign_{position}_" + "y" * 160,
            data_type="UUID",
            position=30 + position,
            is_primary_key=False,
            is_nullable=False,
            is_foreign_key=True,
            referenced_class_id=target.id,
            relation_id=relation.id,
        )
    session.commit()

    reader = SQLModelAgentDiagramReader(session, max_detail_items=5)
    handler = AgentDiagramQueryHandler(
        _handler(session).access_policy,
        reader,
    )
    registry = ToolRegistry()
    DiagramReadTools(
        handler,
        project_id=test_project.id,
        user_id=owner_user.user_id,
        max_result_chars=1_200,
    ).register(registry)

    class_result = _run(
        registry.execute(
            "get_diagram_element", {"type": "class", "id": str(class_model.id)}
        )
    )
    relation_result = _run(
        registry.execute(
            "get_diagram_element", {"type": "relation", "id": str(relation.id)}
        )
    )

    assert len(json.dumps(class_result, ensure_ascii=False, separators=(",", ":"))) <= 1_200
    assert len(class_result["detail"]["attributes"]) < 5
    assert class_result["detail"]["attributes_truncated"] is True
    assert class_result["detail"]["relations_truncated"] is True
    assert len(json.dumps(relation_result, ensure_ascii=False, separators=(",", ":"))) <= 1_200
    assert relation_result["detail"]["materialization"]["derived_attributes_truncated"] is True


def test_search_reports_revoked_project_access_as_forbidden(session, test_project):
    registry = ToolRegistry()
    DiagramReadTools(
        _handler(session), project_id=test_project.id, user_id="removed-member"
    ).register(registry)

    result = _run(
        registry.execute("search_diagram_elements", {"query": "Anything"})
    )

    assert result == {"status": "forbidden", "error_code": "forbidden"}


def test_relation_detail_and_bridge_class_recovery(session, test_project, owner_user):
    """US2: Consultar detalle de relación N:M y recuperar la clase puente sin ambigüedad."""
    registry = ToolRegistry()
    DiagramMutationTools(
        session,
        SqlModelUnitOfWork(session, InMemoryEventBus()),
        project_id=test_project.id,
        user_id=owner_user.user_id,
    ).register(registry)
    DiagramReadTools(
        _handler(session), project_id=test_project.id, user_id=owner_user.user_id
    ).register(registry)

    # 1. Crear clases Autor y Libro
    created = _run(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {"operation_id": "c-aut", "kind": "CREATE_CLASS", "name": "Autor"},
                    {"operation_id": "c-lib", "kind": "CREATE_CLASS", "name": "Libro"},
                ]
            },
        )
    )
    autor_id = created["results"][0]["entity_refs"][0]["id"]
    libro_id = created["results"][1]["entity_refs"][0]["id"]

    # 2. Crear relación N:M entre Autor y Libro
    rel_nm = _run(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "rel-nm",
                        "kind": "CREATE_RELATION",
                        "relation_type": "ASSOCIATION",
                        "source_class_id": autor_id,
                        "target_class_id": libro_id,
                        "source_cardinality": "0..*",
                        "target_cardinality": "0..*",
                    }
                ]
            },
        )
    )
    rel_id = rel_nm["results"][0]["entity_refs"][0]["id"]

    # 3. Consultar detalle de la relación con get_diagram_element
    rel_detail = _run(
        registry.execute(
            "get_diagram_element",
            {"type": "relation", "id": rel_id},
        )
    )
    assert rel_detail["type"] == "relation"
    assert rel_detail["id"] == rel_id
    detail = rel_detail["detail"]
    assert detail["relation_type"] == "ASSOCIATION"
    bridge_class_id = detail["bridge_class_id"]
    assert bridge_class_id is not None
    assert detail["materialization"]["bridge_class_id"] == bridge_class_id

    # 4. Recuperar la clase puente consultando con su ID confirmado
    bridge_class_detail = _run(
        registry.execute(
            "get_diagram_element",
            {"type": "class", "id": bridge_class_id},
        )
    )
    assert bridge_class_detail["type"] == "class"
    assert bridge_class_detail["id"] == bridge_class_id
    assert bridge_class_detail["name"] == "AutorLibro"
    attrs = bridge_class_detail["detail"]["attributes"]
    assert len(attrs) == 3
    assert sum(1 for a in attrs if a["is_primary_key"]) == 1
    assert sum(1 for a in attrs if a["is_foreign_key"]) == 2

    # 5. Consultar relación inexistente devuelve not_found
    missing = _run(
        registry.execute(
            "get_diagram_element",
            {"type": "relation", "id": str(uuid4())},
        )
    )
    assert missing == {"status": "not_found", "error_code": "not_found"}


def test_entity_resolution_unique_match_ambiguity_and_absence(
    session, test_project, owner_user
):
    """T028 [US5]: Resolución de entidades exige coincidencia única, detecta ambigüedad y confirma ausencia."""
    from datetime import datetime, timezone

    # 1. Coincidencia única: Una sola clase "Producto"
    producto = create_test_class(session, test_project.id, name="Producto")
    session.commit()

    registry = ToolRegistry()
    DiagramReadTools(
        _handler(session), project_id=test_project.id, user_id=owner_user.user_id
    ).register(registry)

    res_unique = _run(
        registry.execute(
            "search_diagram_elements",
            {"query": "Producto", "types": ["class"]},
        )
    )
    assert res_unique["status"] == "ok"
    assert res_unique["ambiguous"] is False
    assert len(res_unique["items"]) == 1
    assert res_unique["items"][0]["id"] == str(producto.id)
    assert res_unique["items"][0]["name"] == "Producto"

    # Detalle con el ID confirmado
    detail = _run(
        registry.execute(
            "get_diagram_element",
            {"type": "class", "id": str(producto.id)},
        )
    )
    assert detail["name"] == "Producto"
    assert detail["id"] == str(producto.id)

    # 2. Ambigüedad: Dos clases con el mismo nombre "Factura"
    factura1 = create_test_class(session, test_project.id, name="Factura")
    factura2 = create_test_class(session, test_project.id, name="Factura")
    session.commit()

    res_ambiguous = _run(
        registry.execute(
            "search_diagram_elements",
            {"query": "Factura", "types": ["class"]},
        )
    )
    assert res_ambiguous["status"] == "ambiguous"
    assert res_ambiguous["ambiguous"] is True
    candidate_ids = {item["id"] for item in res_ambiguous["items"]}
    assert str(factura1.id) in candidate_ids
    assert str(factura2.id) in candidate_ids

    # 3. Ausencia: Entidad inexistente
    res_missing = _run(
        registry.execute(
            "search_diagram_elements",
            {"query": "Inexistente", "types": ["class"]},
        )
    )
    assert res_missing["status"] == "ok"
    assert res_missing["ambiguous"] is False
    assert len(res_missing["items"]) == 0

    res_missing_get = _run(
        registry.execute(
            "get_diagram_element",
            {"type": "class", "id": str(uuid4())},
        )
    )
    assert res_missing_get == {"status": "not_found", "error_code": "not_found"}

    # 4. Soft-delete: Clase eliminada lógicamente no aparece
    eliminada = create_test_class(session, test_project.id, name="Eliminada")
    eliminada.deleted_date = datetime.now(timezone.utc)
    session.add(eliminada)
    session.commit()

    res_deleted_search = _run(
        registry.execute(
            "search_diagram_elements",
            {"query": "Eliminada", "types": ["class"]},
        )
    )
    assert len(res_deleted_search["items"]) == 0
    res_deleted_get = _run(
        registry.execute(
            "get_diagram_element",
            {"type": "class", "id": str(eliminada.id)},
        )
    )
    assert res_deleted_get == {"status": "not_found", "error_code": "not_found"}


def test_list_diagram_classes_and_empty_search(session, test_project, owner_user):
    """Verifica list_diagram_classes y que search_diagram_elements permita query vacía."""
    from datetime import datetime, timezone

    c1 = create_test_class(session, test_project.id, name="Usuario")
    c2 = create_test_class(session, test_project.id, name="Pedido")
    c_del = create_test_class(session, test_project.id, name="Borrada")
    c_del.deleted_date = datetime.now(timezone.utc)
    session.add(c_del)
    session.commit()

    registry = ToolRegistry()
    DiagramReadTools(
        _handler(session), project_id=test_project.id, user_id=owner_user.user_id
    ).register(registry)

    # 1. list_diagram_classes retorna solo clases activas
    res_list = _run(registry.execute("list_diagram_classes", {}))
    assert res_list["status"] == "ok"
    assert res_list["total"] == 2
    names = {item["name"] for item in res_list["classes"]}
    assert names == {"Usuario", "Pedido"}
    assert "Borrada" not in names

    # 2. search_diagram_elements con query vacía retorna elementos sin fallar por validación
    res_search = _run(registry.execute("search_diagram_elements", {"query": "", "types": ["class"]}))
    assert res_search["status"] == "ok"
    assert len(res_search["items"]) == 2



def _run(awaitable):
    import anyio

    result = []

    async def _resolve():
        result.append(await awaitable)

    anyio.run(_resolve)
    return result[0]
