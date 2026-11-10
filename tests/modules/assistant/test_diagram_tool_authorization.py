import anyio
import pytest
from sqlmodel import select
from uuid import UUID

from app.modules.assistant.application.services.diagram.diagram_mutation_tools import DiagramMutationTools
from app.modules.assistant.application.services.execution.tool_registry import ToolRegistry
from app.modules.assistant.domain.exceptions import (
    AgentToolArgumentsException,
    UnsupportedAgentToolActionException,
)
from app.modules.diagram.domain.events.diagram_events import DiagramClassCreatedEvent
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import DiagramAttributeModel
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import DiagramClassModel
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import DiagramRelationModel
from app.shared.infrastructure.event_bus_impl import InMemoryEventBus
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork
from tests.modules.diagram.conftest import create_test_class


def _registry(session, project_id, user_id):
    registry = ToolRegistry()
    DiagramMutationTools(
        session,
        SqlModelUnitOfWork(session, InMemoryEventBus()),
        project_id=project_id,
        user_id=user_id,
    ).register(registry)
    return registry


def _execute(awaitable):
    result = []

    async def _resolve():
        result.append(await awaitable)

    anyio.run(_resolve)
    return result[0]


def test_mutation_tool_creates_class_and_rejects_injected_actor_fields(session, test_project, owner_user):
    bus = InMemoryEventBus()
    events = []
    bus.subscribe(DiagramClassCreatedEvent, events.append)
    registry = ToolRegistry()
    DiagramMutationTools(
        session,
        SqlModelUnitOfWork(session, bus),
        project_id=test_project.id,
        user_id=owner_user.user_id,
    ).register(registry)
    report_events = []

    async def report(event):
        report_events.append(event)

    result = _execute(
        registry.execute(
            "apply_diagram_changes",
            {"actions": [{"operation_id": "create-class-1", "kind": "CREATE_CLASS", "name": "Producto"}]},
            report,
        )
    )

    assert result["status"] == "applied"
    class_id = result["results"][0]["entity_refs"][0]["id"]
    class_uuid = UUID(class_id)
    created_class = session.get(DiagramClassModel, class_uuid)
    assert created_class.name == "Producto"
    attrs = session.exec(select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == class_uuid)).all()
    assert len(attrs) == 1
    assert attrs[0].is_primary_key is True
    assert [event["status"] for event in report_events] == ["validated", "applied"]
    assert len(events) == 1
    assert events[0].sender_id == "assistant"

    with pytest.raises(AgentToolArgumentsException):
        _execute(
            registry.execute(
                "apply_diagram_changes",
                {"actions": [{"operation_id": "bad-actor", "kind": "DELETE_CLASS", "class_id": class_id,
                              "project_id": str(test_project.id), "user_id": owner_user.user_id}]},
            )
        )


def test_create_actions_reuse_exact_existing_classes_attributes_and_relations(
    session, test_project, owner_user
):
    registry = _registry(session, test_project.id, owner_user.user_id)

    def apply(action):
        return _execute(
            registry.execute("apply_diagram_changes", {"actions": [action]})
        )["results"][0]

    first_class = apply(
        {"operation_id": "class-product-1", "kind": "CREATE_CLASS", "name": "Producto"}
    )
    second_class = apply(
        {"operation_id": "class-product-2", "kind": "CREATE_CLASS", "name": "producto"}
    )
    product_id = first_class["entity_refs"][0]["id"]
    assert second_class["entity_refs"][0]["id"] == product_id
    assert len(session.exec(
        select(DiagramClassModel).where(
            DiagramClassModel.project_id == test_project.id,
            DiagramClassModel.name == "Producto",
            DiagramClassModel.deleted_date.is_(None),
        )
    ).all()) == 1

    first_attribute = apply(
        {
            "operation_id": "attribute-name-1",
            "kind": "CREATE_ATTRIBUTE",
            "class_id": product_id,
            "name": "nombre",
            "data_type": "TEXT",
        }
    )
    second_attribute = apply(
        {
            "operation_id": "attribute-name-2",
            "kind": "CREATE_ATTRIBUTE",
            "class_id": product_id,
            "name": "Nombre",
            "data_type": "TEXT",
        }
    )
    assert second_attribute["entity_refs"][0]["id"] == first_attribute["entity_refs"][0]["id"]
    assert len(
        session.exec(
            select(DiagramAttributeModel).where(
                DiagramAttributeModel.class_id == UUID(product_id),
                DiagramAttributeModel.name == "nombre",
                DiagramAttributeModel.deleted_date.is_(None),
            )
        ).all()
    ) == 1

    category = apply(
        {"operation_id": "class-category", "kind": "CREATE_CLASS", "name": "Categoria"}
    )
    relation_action = {
        "operation_id": "relation-product-category-1",
        "kind": "CREATE_RELATION",
        "relation_type": "ASSOCIATION",
        "source_class_id": category["entity_refs"][0]["id"],
        "target_class_id": product_id,
        "source_cardinality": "1",
        "target_cardinality": "0..*",
    }
    first_relation = apply(relation_action)
    repeated_relation = apply(
        {
            **relation_action,
            "operation_id": "relation-product-category-2",
        }
    )
    assert repeated_relation["entity_refs"][0]["id"] == first_relation["entity_refs"][0]["id"]
    assert len(
        session.exec(
            select(DiagramRelationModel).where(
                DiagramRelationModel.project_id == test_project.id,
                DiagramRelationModel.deleted_date.is_(None),
            )
        ).all()
    ) == 1
    product_foreign_keys = session.exec(
        select(DiagramAttributeModel).where(
            DiagramAttributeModel.class_id == UUID(product_id),
            DiagramAttributeModel.is_foreign_key.is_(True),
            DiagramAttributeModel.deleted_date.is_(None),
        )
    ).all()
    assert len(product_foreign_keys) == 1


def test_create_class_refuses_multiple_existing_matches_without_creating_another(
    session, test_project, owner_user
):
    create_test_class(session, test_project.id, name="Producto")
    create_test_class(session, test_project.id, name="Producto")
    session.commit()
    registry = _registry(session, test_project.id, owner_user.user_id)

    result = _execute(
        registry.execute(
            "apply_diagram_changes",
            {"actions": [{"operation_id": "ambiguous-product", "kind": "CREATE_CLASS", "name": "Producto"}]},
        )
    )

    assert result["status"] == "rejected"
    assert result["results"][0]["error_code"] == "conflict"
    assert len(
        session.exec(
            select(DiagramClassModel).where(
                DiagramClassModel.project_id == test_project.id,
                DiagramClassModel.name == "Producto",
                DiagramClassModel.deleted_date.is_(None),
            )
        ).all()
    ) == 2


def test_visual_scope_guard_rejects_unrequested_class_before_mutating(
    session, test_project, owner_user
):
    registry = _registry(session, test_project.id, owner_user.user_id)

    with pytest.raises(AgentToolArgumentsException):
        _execute(
            registry.execute(
                "apply_diagram_changes",
                {
                    "actions": [
                        {"operation_id": "create-category", "kind": "CREATE_CLASS", "name": "Categoria"}
                    ]
                },
                visual_scope={
                    "classes": [{"name": "Producto", "attributes": []}],
                    "relations": [],
                },
            )
        )

    assert session.exec(
        select(DiagramClassModel).where(
            DiagramClassModel.project_id == test_project.id,
            DiagramClassModel.name == "Categoria",
            DiagramClassModel.deleted_date.is_(None),
        )
    ).first() is None


def test_visual_scope_guard_enforces_the_user_selected_duplicate_class(
    session, test_project, owner_user
):
    first = create_test_class(session, test_project.id, name="Producto")
    second = create_test_class(session, test_project.id, name="Producto")
    session.commit()
    registry = _registry(session, test_project.id, owner_user.user_id)
    scope = {
        "classes": [{"name": "Producto", "attributes": [{"name": "nombre"}]}],
        "relations": [],
        "selected_class_ids": {"producto": str(first.id)},
    }

    with pytest.raises(AgentToolArgumentsException):
        _execute(
            registry.execute(
                "apply_diagram_changes",
                {"actions": [{"operation_id": "wrong-class", "kind": "CREATE_ATTRIBUTE", "class_id": str(second.id), "name": "nombre"}]},
                visual_scope=scope,
            )
        )
    result = _execute(
        registry.execute(
            "apply_diagram_changes",
            {"actions": [{"operation_id": "reuse-class", "kind": "CREATE_CLASS", "name": "Producto"}]},
            visual_scope=scope,
        )
    )
    assert result["results"][0]["entity_refs"][0]["id"] == str(first.id)
    assert session.exec(
        select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == second.id)
    ).all() == []


def test_mutation_rejects_reader_without_effect(session, test_project, reader_user):
    class_model = create_test_class(session, test_project.id, name="Privada")
    session.commit()
    registry = _registry(session, test_project.id, reader_user.user_id)

    result = _execute(
        registry.execute(
            "apply_diagram_changes",
            {"actions": [{"operation_id": "reader-rename", "kind": "RENAME_CLASS",
                          "class_id": str(class_model.id), "name": "No permitido"}]},
        )
    )

    assert result["status"] == "rejected"
    assert result["results"][0]["error_code"] == "forbidden"
    assert session.get(DiagramClassModel, class_model.id).name == "Privada"


def test_mutation_reports_excluded_move_class_as_unsupported_action(
    session, test_project, owner_user
):
    registry = _registry(session, test_project.id, owner_user.user_id)

    with pytest.raises(UnsupportedAgentToolActionException):
        _execute(
            registry.execute(
                "apply_diagram_changes",
                {
                    "actions": [
                        {
                            "operation_id": "move-is-not-supported",
                            "kind": "MOVE_CLASS",
                        }
                    ]
                },
            )
        )


def test_mutation_batch_keeps_prior_commit_when_later_operation_is_rejected(
    session, test_project, owner_user
):
    registry = _registry(session, test_project.id, owner_user.user_id)

    result = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "create-committed",
                        "kind": "CREATE_CLASS",
                        "name": "Persistida",
                    },
                    {
                        "operation_id": "rename-missing",
                        "kind": "RENAME_CLASS",
                        "class_id": str(UUID(int=1)),
                        "name": "No existe",
                    },
                ]
            },
        )
    )

    assert result["status"] == "rejected"
    assert result["stopped_at"] == "rename-missing"
    assert result["mutation_applied"] is True
    assert result["results"][0]["status"] == "applied"
    assert result["results"][1]["error_code"] == "not_found"
    persisted_class_id = UUID(result["results"][0]["entity_refs"][0]["id"])
    assert session.get(DiagramClassModel, persisted_class_id).name == "Persistida"


def test_class_and_secondary_attribute_use_cases_cover_edit_order_delete_and_cascade(
    session, test_project, owner_user
):
    registry = _registry(session, test_project.id, owner_user.user_id)
    created = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {"operation_id": "class-create", "kind": "CREATE_CLASS", "name": "Cliente"},
                ]
            },
        )
    )
    class_id = created["results"][0]["entity_refs"][0]["id"]
    attributes = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {"operation_id": "attr-email", "kind": "CREATE_ATTRIBUTE", "class_id": class_id, "name": "email"},
                    {"operation_id": "attr-name", "kind": "CREATE_ATTRIBUTE", "class_id": class_id, "name": "nombre"},
                ]
            },
        )
    )
    email_id = attributes["results"][0]["entity_refs"][0]["id"]
    name_id = attributes["results"][1]["entity_refs"][0]["id"]

    updated = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {"operation_id": "attr-update", "kind": "UPDATE_ATTRIBUTE", "attribute_id": email_id,
                     "name": "correo", "data_type": "TEXT", "nullable": False},
                    {"operation_id": "attr-reposition", "kind": "REPOSITION_ATTRIBUTE", "attribute_id": name_id, "position": 1},
                    {"operation_id": "attr-delete", "kind": "DELETE_ATTRIBUTE", "attribute_id": email_id},
                    {"operation_id": "class-rename", "kind": "RENAME_CLASS", "class_id": class_id, "name": "Persona"},
                ]
            },
        )
    )

    assert updated["status"] == "applied"
    remaining = session.get(DiagramAttributeModel, UUID(name_id))
    assert remaining.name == "nombre"
    assert remaining.position == 1
    assert session.get(DiagramAttributeModel, UUID(email_id)) is None
    assert session.get(DiagramClassModel, UUID(class_id)).name == "Persona"

    deleted = _execute(
        registry.execute(
            "apply_diagram_changes",
            {"actions": [{"operation_id": "class-delete", "kind": "DELETE_CLASS", "class_id": class_id}]},
        )
    )
    assert deleted["status"] == "applied"
    assert session.get(DiagramClassModel, UUID(class_id)) is None
    assert session.get(DiagramAttributeModel, UUID(name_id)) is None


def test_move_and_manual_foreign_key_actions_are_not_in_the_schema(session, test_project, owner_user):
    registry = _registry(session, test_project.id, owner_user.user_id)
    for kind in ("MOVE_CLASS", "CREATE_FOREIGN_KEY", "CREATE_BRIDGE_CLASS"):
        with pytest.raises(UnsupportedAgentToolActionException):
            _execute(registry.execute(
                "apply_diagram_changes",
                {"actions": [{"operation_id": f"unsupported-{kind}", "kind": kind}]},
            ))


def test_mutation_contract_rejects_malformed_ids_arguments_and_duplicate_operations(
    session, test_project, owner_user
):
    registry = _registry(session, test_project.id, owner_user.user_id)
    invalid_action_lists = [
        [{"operation_id": "bad-id", "kind": "RENAME_CLASS", "class_id": "not-a-uuid", "name": "X"}],
        [
            {"operation_id": "same", "kind": "CREATE_CLASS", "name": "A"},
            {"operation_id": "same", "kind": "CREATE_CLASS", "name": "B"},
        ],
        [{"operation_id": "bad-position", "kind": "CREATE_CLASS", "position": {"x": True, "y": 1}}],
        [{"operation_id": "bad-nullable", "kind": "CREATE_ATTRIBUTE", "class_id": str(test_project.id), "name": "x", "nullable": "yes"}],
    ]

    for actions in invalid_action_lists:
        with pytest.raises(AgentToolArgumentsException):
            _execute(registry.execute("apply_diagram_changes", {"actions": actions}))
