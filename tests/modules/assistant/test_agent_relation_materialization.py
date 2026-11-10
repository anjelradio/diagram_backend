import anyio
from uuid import UUID

from sqlmodel import select

from app.modules.assistant.application.services.diagram.diagram_mutation_tools import DiagramMutationTools
from app.modules.assistant.application.services.execution.tool_registry import ToolRegistry
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import DiagramAttributeModel
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import DiagramClassModel
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import DiagramRelationModel
from app.modules.diagram.domain.events.diagram_events import (
    DiagramRelationCreatedEvent,
    DiagramRelationDeletedEvent,
)
from app.shared.infrastructure.event_bus_impl import InMemoryEventBus
from app.shared.infrastructure.event_bus_impl import InMemoryEventBus
from app.shared.infrastructure.unit_of_work import SqlModelUnitOfWork


def _execute(awaitable):
    values = []

    async def run():
        values.append(await awaitable)

    anyio.run(run)
    return values[0]


def _registry(session, project_id, user_id, event_bus=None):
    registry = ToolRegistry()
    DiagramMutationTools(
        session,
        SqlModelUnitOfWork(session, event_bus or InMemoryEventBus()),
        project_id=project_id,
        user_id=user_id,
    ).register(registry)
    return registry


def test_relation_event_contains_committed_materialized_foreign_key(
    session, test_project, owner_user, monkeypatch
):
    event_bus = InMemoryEventBus()
    registry = _registry(session, test_project.id, owner_user.user_id, event_bus)
    created = _execute(
        registry.execute(
            "apply_diagram_changes",
            {"actions": [
                {"operation_id": "client", "kind": "CREATE_CLASS", "name": "Cliente"},
                {"operation_id": "order", "kind": "CREATE_CLASS", "name": "Pedido"},
            ]},
        )
    )
    client_id = UUID(created["results"][0]["entity_refs"][0]["id"])
    order_id = UUID(created["results"][1]["entity_refs"][0]["id"])
    emitted = []
    commit_count = {"value": 0}
    event_bus.subscribe(
        DiagramRelationCreatedEvent,
        lambda event: (emitted.append(event), assert_committed()),
    )
    session_commit = session.commit

    def tracked_commit():
        session_commit()
        commit_count["value"] += 1

    def assert_committed():
        assert commit_count["value"] == 1

    monkeypatch.setattr(session, "commit", tracked_commit)
    _execute(
        registry.execute(
            "apply_diagram_changes",
            {"actions": [{
                "operation_id": "client-orders",
                "kind": "CREATE_RELATION",
                "relation_type": "ASSOCIATION",
                "source_class_id": str(client_id),
                "target_class_id": str(order_id),
                "source_cardinality": "1",
                "target_cardinality": "0..*",
            }]},
        )
    )

    assert len(emitted) == 1
    projection = emitted[0].data["materialized_classes"]
    assert len(projection) == 1
    assert projection[0]["id"] == str(order_id)
    derived = [attribute for attribute in projection[0]["attributes"] if attribute["is_foreign_key"]]
    assert len(derived) == 1
    assert derived[0]["referenced_class_id"] == str(client_id)
    assert derived[0]["relation_id"] == emitted[0].data["id"]

    deleted = []
    event_bus.subscribe(DiagramRelationDeletedEvent, deleted.append)
    _execute(
        registry.execute(
            "apply_diagram_changes",
            {"actions": [{
                "operation_id": "delete-client-orders",
                "kind": "DELETE_RELATION",
                "relation_id": emitted[0].data["id"],
            }]},
        )
    )
    assert len(deleted) == 1
    assert deleted[0].data["removed_attribute_ids"] == [derived[0]["id"]]
    remaining_class = deleted[0].data["materialized_classes"][0]
    assert remaining_class["id"] == str(order_id)
    assert not any(item["is_foreign_key"] for item in remaining_class["attributes"])


def test_failed_relation_commit_emits_no_diagram_mutation(
    session, test_project, owner_user, monkeypatch
):
    event_bus = InMemoryEventBus()
    registry = _registry(session, test_project.id, owner_user.user_id, event_bus)
    created = _execute(
        registry.execute(
            "apply_diagram_changes",
            {"actions": [
                {"operation_id": "client", "kind": "CREATE_CLASS", "name": "Cliente"},
                {"operation_id": "order", "kind": "CREATE_CLASS", "name": "Pedido"},
            ]},
        )
    )
    source_id = UUID(created["results"][0]["entity_refs"][0]["id"])
    target_id = UUID(created["results"][1]["entity_refs"][0]["id"])
    emitted = []
    event_bus.subscribe(DiagramRelationCreatedEvent, emitted.append)

    def fail_commit():
        raise RuntimeError("commit rejected")

    monkeypatch.setattr(session, "commit", fail_commit)
    result = _execute(
        registry.execute(
            "apply_diagram_changes",
            {"actions": [{
                "operation_id": "failed-relation",
                "kind": "CREATE_RELATION",
                "relation_type": "ASSOCIATION",
                "source_class_id": str(source_id),
                "target_class_id": str(target_id),
                "source_cardinality": "1",
                "target_cardinality": "0..*",
            }]},
        )
    )

    assert result["status"] == "uncertain"
    assert emitted == []
    assert session.exec(
        select(DiagramRelationModel).where(DiagramRelationModel.project_id == test_project.id)
    ).all() == []


def test_many_to_many_relation_creates_one_bridge_and_all_derived_attributes(
    session, test_project, owner_user
):
    registry = _registry(session, test_project.id, owner_user.user_id)
    created = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {"operation_id": "class-a", "kind": "CREATE_CLASS", "name": "Autor"},
                    {"operation_id": "class-b", "kind": "CREATE_CLASS", "name": "Libro"},
                ]
            },
        )
    )
    source_id = UUID(created["results"][0]["entity_refs"][0]["id"])
    target_id = UUID(created["results"][1]["entity_refs"][0]["id"])

    relation_result = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "relation-ab",
                        "kind": "CREATE_RELATION",
                        "relation_type": "ASSOCIATION",
                        "source_class_id": str(source_id),
                        "target_class_id": str(target_id),
                        "source_cardinality": "0..*",
                        "target_cardinality": "0..*",
                    }
                ]
            },
        )
    )
    relation_id = UUID(relation_result["results"][0]["entity_refs"][0]["id"])
    derived = relation_result["results"][0]["derived_effects"]
    bridge_id = UUID(next(ref["id"] for ref in derived if ref["type"] == "class"))
    bridge = session.get(DiagramClassModel, bridge_id)
    assert bridge.name == "AutorLibro"
    assert session.get(DiagramRelationModel, relation_id).bridge_class_id == bridge_id

    bridge_attributes = session.exec(
        select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == bridge_id)
    ).all()
    assert len(bridge_attributes) == 3
    assert sum(attribute.is_primary_key for attribute in bridge_attributes) == 1
    assert sum(attribute.is_foreign_key for attribute in bridge_attributes) == 2
    existing_fk = next(attribute for attribute in bridge_attributes if attribute.is_foreign_key)

    redundant = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {"operation_id": "explicit-bridge", "kind": "CREATE_CLASS", "name": "AutorLibro"},
                    {
                        "operation_id": "explicit-fk",
                        "kind": "CREATE_ATTRIBUTE",
                        "class_id": str(bridge_id),
                        "name": existing_fk.name,
                    },
                    {
                        "operation_id": "explicit-pk",
                        "kind": "CREATE_ATTRIBUTE",
                        "class_id": str(bridge_id),
                        "name": "id",
                    },
                ]
            },
        )
    )
    assert redundant["status"] == "applied"
    assert len(
        session.exec(
            select(DiagramClassModel).where(
                DiagramClassModel.project_id == test_project.id,
                DiagramClassModel.name == "AutorLibro",
            )
        ).all()
    ) == 1
    assert len(
        session.exec(
            select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == bridge_id)
        ).all()
    ) == 3

    added = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "bridge-extra-attribute",
                        "kind": "CREATE_ATTRIBUTE",
                        "class_id": str(bridge_id),
                        "name": "fecha_publicacion",
                        "data_type": "DATE",
                        "nullable": False,
                    }
                ]
            },
        )
    )
    assert added["status"] == "applied"
    assert len(
        session.exec(
            select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == bridge_id)
        ).all()
    ) == 4

    renamed = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "rename-relation",
                        "kind": "RENAME_RELATION",
                        "relation_id": str(relation_id),
                        "name": "escribe",
                    }
                ]
            },
        )
    )
    assert renamed["status"] == "applied"
    assert session.get(DiagramRelationModel, relation_id).name == "escribe"

    deleted = _execute(
        registry.execute(
            "apply_diagram_changes",
            {"actions": [{"operation_id": "delete-relation", "kind": "DELETE_RELATION", "relation_id": str(relation_id)}]},
        )
    )
    assert deleted["status"] == "applied"
    assert session.get(DiagramRelationModel, relation_id) is None
    assert session.get(DiagramClassModel, bridge_id) is None
    assert session.exec(
        select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == bridge_id)
    ).all() == []


def test_one_to_many_one_to_one_and_structural_relations_follow_diagram_policy(
    session, test_project, owner_user
):
    registry = _registry(session, test_project.id, owner_user.user_id)
    classes = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {"operation_id": "c1", "kind": "CREATE_CLASS", "name": "Cliente"},
                    {"operation_id": "c2", "kind": "CREATE_CLASS", "name": "Pedido"},
                    {"operation_id": "c3", "kind": "CREATE_CLASS", "name": "Perfil"},
                    {"operation_id": "c4", "kind": "CREATE_CLASS", "name": "Usuario"},
                    {"operation_id": "c5", "kind": "CREATE_CLASS", "name": "Base"},
                    {"operation_id": "c6", "kind": "CREATE_CLASS", "name": "Derivada"},
                    {"operation_id": "c7", "kind": "CREATE_CLASS", "name": "EntidadBase"},
                    {"operation_id": "c8", "kind": "CREATE_CLASS", "name": "EntidadDerivada"},
                ]
            },
        )
    )
    ids = [UUID(item["entity_refs"][0]["id"]) for item in classes["results"]]
    relations = [
        {
            "operation_id": "one-to-many",
            "kind": "CREATE_RELATION",
            "relation_type": "ASSOCIATION",
            "source_class_id": str(ids[0]),
            "target_class_id": str(ids[1]),
            "source_cardinality": "1",
            "target_cardinality": "0..*",
        },
        {
            "operation_id": "one-to-one",
            "kind": "CREATE_RELATION",
            "relation_type": "ASSOCIATION",
            "source_class_id": str(ids[2]),
            "target_class_id": str(ids[3]),
            "source_cardinality": "0..1",
            "target_cardinality": "1",
        },
        {
            "operation_id": "composition",
            "kind": "CREATE_RELATION",
            "relation_type": "COMPOSITION",
            "source_class_id": str(ids[4]),
            "target_class_id": str(ids[5]),
        },
        {
            "operation_id": "generalization",
            "kind": "CREATE_RELATION",
            "relation_type": "GENERALIZATION",
            "source_class_id": str(ids[6]),
            "target_class_id": str(ids[7]),
        },
    ]
    results = _execute(
        registry.execute("apply_diagram_changes", {"actions": relations})
    )

    assert results["status"] == "applied"
    fk_for_many = session.exec(
        select(DiagramAttributeModel).where(
            DiagramAttributeModel.relation_id == UUID(results["results"][0]["entity_refs"][0]["id"])
        )
    ).one()
    assert fk_for_many.class_id == ids[1]
    assert fk_for_many.referenced_class_id == ids[0]

    fk_for_optional = session.exec(
        select(DiagramAttributeModel).where(
            DiagramAttributeModel.relation_id == UUID(results["results"][1]["entity_refs"][0]["id"])
        )
    ).one()
    assert fk_for_optional.class_id == ids[3]
    assert fk_for_optional.referenced_class_id == ids[2]
    assert fk_for_optional.is_nullable is True

    structural_fk = session.exec(
        select(DiagramAttributeModel).where(
            DiagramAttributeModel.relation_id == UUID(results["results"][2]["entity_refs"][0]["id"])
        )
    ).one()
    assert structural_fk.class_id == ids[5]
    assert structural_fk.referenced_class_id == ids[4]
    assert structural_fk.is_nullable is False

    generalization_fk = session.exec(
        select(DiagramAttributeModel).where(
            DiagramAttributeModel.relation_id
            == UUID(results["results"][3]["entity_refs"][0]["id"])
        )
    ).one()
    assert generalization_fk.class_id == ids[6]
    assert generalization_fk.referenced_class_id == ids[7]
    assert generalization_fk.is_nullable is False


def test_self_association_uses_one_nullable_self_referencing_foreign_key(
    session, test_project, owner_user
):
    registry = _registry(session, test_project.id, owner_user.user_id)
    created = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {"operation_id": "employee", "kind": "CREATE_CLASS", "name": "Empleado"}
                ]
            },
        )
    )
    employee_id = UUID(created["results"][0]["entity_refs"][0]["id"])

    result = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "reports-to",
                        "kind": "CREATE_RELATION",
                        "relation_type": "ASSOCIATION",
                        "source_class_id": str(employee_id),
                        "target_class_id": str(employee_id),
                        "source_cardinality": "0..1",
                        "target_cardinality": "0..*",
                    }
                ]
            },
        )
    )

    assert result["status"] == "applied"
    relation_id = UUID(result["results"][0]["entity_refs"][0]["id"])
    self_reference = session.exec(
        select(DiagramAttributeModel).where(
            DiagramAttributeModel.relation_id == relation_id
        )
    ).one()
    assert self_reference.class_id == employee_id
    assert self_reference.referenced_class_id == employee_id
    assert self_reference.is_foreign_key is True
    assert self_reference.is_nullable is True


def test_regression_class_creation_with_attributes_and_relation_lifecycle(
    session, test_project, owner_user
):
    """Regresión: creación de clases con atributos propios, relación N:M, extensión del puente y limpieza."""
    registry = _registry(session, test_project.id, owner_user.user_id)

    # 1. Crear clases con atributos propios
    creation_result = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {"operation_id": "c-estudiante", "kind": "CREATE_CLASS", "name": "Estudiante"},
                    {"operation_id": "c-curso", "kind": "CREATE_CLASS", "name": "Curso"},
                ]
            },
        )
    )
    assert creation_result["status"] == "applied"
    estudiante_id = UUID(creation_result["results"][0]["entity_refs"][0]["id"])
    curso_id = UUID(creation_result["results"][1]["entity_refs"][0]["id"])

    attr_result = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "a-matricula",
                        "kind": "CREATE_ATTRIBUTE",
                        "class_id": str(estudiante_id),
                        "name": "matricula",
                        "data_type": "TEXT",
                        "nullable": False,
                    },
                    {
                        "operation_id": "a-codigo",
                        "kind": "CREATE_ATTRIBUTE",
                        "class_id": str(curso_id),
                        "name": "codigo",
                        "data_type": "TEXT",
                        "nullable": False,
                    },
                ]
            },
        )
    )
    assert attr_result["status"] == "applied"

    # Verificar atributos propios (más el id PK automático de cada clase)
    estudiante_attrs = session.exec(
        select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == estudiante_id)
    ).all()
    curso_attrs = session.exec(
        select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == curso_id)
    ).all()
    assert len(estudiante_attrs) == 2  # id + matricula
    assert len(curso_attrs) == 2  # id + codigo

    # 2. Relación N:M que materializa clase puente
    rel_result = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "rel-estudiante-curso",
                        "kind": "CREATE_RELATION",
                        "relation_type": "ASSOCIATION",
                        "source_class_id": str(estudiante_id),
                        "target_class_id": str(curso_id),
                        "source_cardinality": "0..*",
                        "target_cardinality": "0..*",
                    }
                ]
            },
        )
    )
    assert rel_result["status"] == "applied"
    relation_id = UUID(rel_result["results"][0]["entity_refs"][0]["id"])
    bridge_ref = next(
        ref for ref in rel_result["results"][0]["derived_effects"] if ref["type"] == "class"
    )
    bridge_id = UUID(bridge_ref["id"])
    bridge_class = session.get(DiagramClassModel, bridge_id)
    assert bridge_class is not None
    assert bridge_class.name == "EstudianteCurso"

    # 3. Agregar atributo de negocio a la clase puente
    bridge_attr_result = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "a-calificacion",
                        "kind": "CREATE_ATTRIBUTE",
                        "class_id": str(bridge_id),
                        "name": "calificacion_final",
                        "data_type": "DECIMAL",
                        "nullable": True,
                    }
                ]
            },
        )
    )
    assert bridge_attr_result["status"] == "applied"
    bridge_attrs = session.exec(
        select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == bridge_id)
    ).all()
    assert len(bridge_attrs) == 4  # id PK + 2 FKs + calificacion_final

    # 4. Eliminar la relación y verificar limpieza de puente conservando entidades originales
    delete_result = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "del-rel",
                        "kind": "DELETE_RELATION",
                        "relation_id": str(relation_id),
                    }
                ]
            },
        )
    )
    assert delete_result["status"] == "applied"
    assert session.get(DiagramClassModel, bridge_id) is None
    assert session.get(DiagramRelationModel, relation_id) is None
    # Estudiante y Curso siguen existiendo con sus atributos
    assert session.get(DiagramClassModel, estudiante_id) is not None
    assert session.get(DiagramClassModel, curso_id) is not None
    assert len(
        session.exec(
            select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == estudiante_id)
        ).all()
    ) == 2
    assert len(
        session.exec(
            select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == curso_id)
        ).all()
    ) == 2


def test_relation_materialization_deduplication_and_derived_reference_handling(
    session, test_project, owner_user
):
    """US2: No duplicar PK, FK ni clase puente cuando el agente intenta crearlas manualmente."""
    registry = _registry(session, test_project.id, owner_user.user_id)

    # 1. Crear clases base Cliente y Pedido
    created = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {"operation_id": "c-cli", "kind": "CREATE_CLASS", "name": "Cliente"},
                    {"operation_id": "c-ped", "kind": "CREATE_CLASS", "name": "Pedido"},
                ]
            },
        )
    )
    cliente_id = UUID(created["results"][0]["entity_refs"][0]["id"])
    pedido_id = UUID(created["results"][1]["entity_refs"][0]["id"])

    # 2. Intento de crear manualmente la PK 'id' en Cliente
    pk_attempt = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "dup-pk",
                        "kind": "CREATE_ATTRIBUTE",
                        "class_id": str(cliente_id),
                        "name": "id",
                        "data_type": "UUID",
                    }
                ]
            },
        )
    )
    assert pk_attempt["status"] == "applied"
    assert any(
        eff.get("type") == "already_materialized"
        for eff in pk_attempt["results"][0]["derived_effects"]
    )
    cliente_attrs = session.exec(
        select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == cliente_id)
    ).all()
    assert len(cliente_attrs) == 1
    assert cliente_attrs[0].is_primary_key is True

    # 3. Crear relación 1:N (Cliente 1 -> 0..* Pedido)
    rel_1_n = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "rel-cli-ped",
                        "kind": "CREATE_RELATION",
                        "relation_type": "ASSOCIATION",
                        "source_class_id": str(cliente_id),
                        "target_class_id": str(pedido_id),
                        "source_cardinality": "1",
                        "target_cardinality": "0..*",
                    }
                ]
            },
        )
    )
    assert rel_1_n["status"] == "applied"
    derived_fk_ref = next(
        ref for ref in rel_1_n["results"][0]["derived_effects"] if ref["type"] == "attribute"
    )
    fk_id = UUID(derived_fk_ref["id"])
    fk_attr = session.get(DiagramAttributeModel, fk_id)
    assert fk_attr is not None
    assert fk_attr.class_id == pedido_id
    assert fk_attr.is_foreign_key is True
    assert fk_attr.name == "cliente_id"

    # 4. Intento de crear manualmente la FK 'cliente_id' en Pedido
    fk_attempt = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "dup-fk",
                        "kind": "CREATE_ATTRIBUTE",
                        "class_id": str(pedido_id),
                        "name": "cliente_id",
                        "data_type": "UUID",
                    }
                ]
            },
        )
    )
    assert fk_attempt["status"] == "applied"
    assert any(
        eff.get("type") == "already_materialized"
        for eff in fk_attempt["results"][0]["derived_effects"]
    )
    assert fk_attempt["results"][0]["entity_refs"][0]["id"] == str(fk_id)
    pedido_attrs = session.exec(
        select(DiagramAttributeModel).where(DiagramAttributeModel.class_id == pedido_id)
    ).all()
    assert len(pedido_attrs) == 2  # PK + FK única

    # 5. Crear relación N:M entre Pedido y Producto para probar clase puente y derived refs
    prod_created = _execute(
        registry.execute(
            "apply_diagram_changes",
            {"actions": [{"operation_id": "c-prod", "kind": "CREATE_CLASS", "name": "Producto"}]},
        )
    )
    producto_id = UUID(prod_created["results"][0]["entity_refs"][0]["id"])
    rel_n_m = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "rel-ped-prod",
                        "kind": "CREATE_RELATION",
                        "relation_type": "ASSOCIATION",
                        "source_class_id": str(pedido_id),
                        "target_class_id": str(producto_id),
                        "source_cardinality": "0..*",
                        "target_cardinality": "0..*",
                    }
                ]
            },
        )
    )
    assert rel_n_m["status"] == "applied"
    bridge_ref = next(
        ref for ref in rel_n_m["results"][0]["derived_effects"] if ref["type"] == "class"
    )
    bridge_id = UUID(bridge_ref["id"])

    # 6. Intento de crear manualmente la clase puente 'PedidoProducto'
    bridge_attempt = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "dup-bridge",
                        "kind": "CREATE_CLASS",
                        "name": "PedidoProducto",
                    }
                ]
            },
        )
    )
    assert bridge_attempt["status"] == "applied"
    assert any(
        eff.get("type") == "already_materialized"
        for eff in bridge_attempt["results"][0]["derived_effects"]
    )
    assert bridge_attempt["results"][0]["entity_refs"][0]["id"] == str(bridge_id)
    classes_named_bridge = session.exec(
        select(DiagramClassModel).where(
            DiagramClassModel.project_id == test_project.id,
            DiagramClassModel.name == "PedidoProducto",
            DiagramClassModel.deleted_date.is_(None),
        )
    ).all()
    assert len(classes_named_bridge) == 1


def test_reversed_association_and_directed_structural_duplicate_detection(
    session, test_project, owner_user
):
    """T007: Detección de duplicados para asociaciones invertidas y relaciones estructurales dirigidas."""
    registry = _registry(session, test_project.id, owner_user.user_id)

    # 1. Crear clases A y B
    classes = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {"operation_id": "c-a", "kind": "CREATE_CLASS", "name": "ClaseA"},
                    {"operation_id": "c-b", "kind": "CREATE_CLASS", "name": "ClaseB"},
                ]
            },
        )
    )
    id_a = UUID(classes["results"][0]["entity_refs"][0]["id"])
    id_b = UUID(classes["results"][1]["entity_refs"][0]["id"])

    # 2. Crear asociación directa A -> B (1 -> 0..*, 'relaciona')
    res1 = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "rel-direct",
                        "kind": "CREATE_RELATION",
                        "relation_type": "ASSOCIATION",
                        "source_class_id": str(id_a),
                        "target_class_id": str(id_b),
                        "source_cardinality": "1",
                        "target_cardinality": "0..*",
                        "name": "relaciona",
                    }
                ]
            },
        )
    )
    assert res1["status"] == "applied"
    rel_id = UUID(res1["results"][0]["entity_refs"][0]["id"])

    # 3. Intentar crear asociación invertida B -> A (0..* -> 1, 'relaciona')
    # Debe ser detectada como already_materialized y reutilizar el ID existente
    res2 = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "rel-reversed",
                        "kind": "CREATE_RELATION",
                        "relation_type": "ASSOCIATION",
                        "source_class_id": str(id_b),
                        "target_class_id": str(id_a),
                        "source_cardinality": "0..*",
                        "target_cardinality": "1",
                        "name": "relaciona",
                    }
                ]
            },
        )
    )
    assert res2["status"] == "applied"
    assert any(
        eff.get("type") == "already_materialized"
        for eff in res2["results"][0]["derived_effects"]
    )
    assert res2["results"][0]["entity_refs"][0]["id"] == str(rel_id)

    # 4. Probar que asociación invertida con diferente nombre NO es equivalente
    res3 = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "rel-diff-name",
                        "kind": "CREATE_RELATION",
                        "relation_type": "ASSOCIATION",
                        "source_class_id": str(id_b),
                        "target_class_id": str(id_a),
                        "source_cardinality": "0..*",
                        "target_cardinality": "1",
                        "name": "otra_cosa",
                    }
                ]
            },
        )
    )
    assert res3["status"] == "applied"
    assert res3["results"][0]["entity_refs"][0]["id"] != str(rel_id)

    # 5. Relaciones estructurales conservan dirección estricta
    res_comp1 = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "comp-direct",
                        "kind": "CREATE_RELATION",
                        "relation_type": "COMPOSITION",
                        "source_class_id": str(id_a),
                        "target_class_id": str(id_b),
                    }
                ]
            },
        )
    )
    assert res_comp1["status"] == "applied"
    comp_id = UUID(res_comp1["results"][0]["entity_refs"][0]["id"])

    # Duplicado exacto estructural -> already_materialized
    res_comp_dup = _execute(
        registry.execute(
            "apply_diagram_changes",
            {
                "actions": [
                    {
                        "operation_id": "comp-dup",
                        "kind": "CREATE_RELATION",
                        "relation_type": "COMPOSITION",
                        "source_class_id": str(id_a),
                        "target_class_id": str(id_b),
                    }
                ]
            },
        )
    )
    assert res_comp_dup["status"] == "applied"
    assert any(
        eff.get("type") == "already_materialized"
        for eff in res_comp_dup["results"][0]["derived_effects"]
    )
    assert res_comp_dup["results"][0]["entity_refs"][0]["id"] == str(comp_id)


def test_sixteen_association_cardinality_pairs_and_five_structural_directions(
    session, test_project, owner_user
):
    """T008: Verificar materialización para las 16 combinaciones de cardinalidad y los 5 tipos estructurales."""
    from tests.modules.assistant.fixtures.relation_cases import (
        ASSOCIATION_CARDINALITY_PAIRS,
    )

    registry = _registry(session, test_project.id, owner_user.user_id)

    # Probar un subconjunto representativo de los 16 pares de cardinalidades
    for i, (src_card, tgt_card) in enumerate(ASSOCIATION_CARDINALITY_PAIRS):
        cls_res = _execute(
            registry.execute(
                "apply_diagram_changes",
                {
                    "actions": [
                        {"operation_id": f"src-{i}", "kind": "CREATE_CLASS", "name": f"Src{i}"},
                        {"operation_id": f"tgt-{i}", "kind": "CREATE_CLASS", "name": f"Tgt{i}"},
                    ]
                },
            )
        )
        src_id = cls_res["results"][0]["entity_refs"][0]["id"]
        tgt_id = cls_res["results"][1]["entity_refs"][0]["id"]

        rel_res = _execute(
            registry.execute(
                "apply_diagram_changes",
                {
                    "actions": [
                        {
                            "operation_id": f"rel-{i}",
                            "kind": "CREATE_RELATION",
                            "relation_type": "ASSOCIATION",
                            "source_class_id": src_id,
                            "target_class_id": tgt_id,
                            "source_cardinality": src_card,
                            "target_cardinality": tgt_card,
                            "name": f"rel_{i}",
                        }
                    ]
                },
            )
        )
        assert rel_res["status"] == "applied"
        assert len(rel_res["results"][0]["entity_refs"]) >= 1

    # Probar las 5 relaciones estructurales
    structural_types = [
        "AGGREGATION",
        "COMPOSITION",
        "GENERALIZATION",
        "REALIZATION",
        "DEPENDENCY",
    ]
    for st in structural_types:
        cls_res = _execute(
            registry.execute(
                "apply_diagram_changes",
                {
                    "actions": [
                        {"operation_id": f"st-src-{st}", "kind": "CREATE_CLASS", "name": f"StructSrc{st}"},
                        {"operation_id": f"st-tgt-{st}", "kind": "CREATE_CLASS", "name": f"StructTgt{st}"},
                    ]
                },
            )
        )
        s_id = cls_res["results"][0]["entity_refs"][0]["id"]
        t_id = cls_res["results"][1]["entity_refs"][0]["id"]

        rel_res = _execute(
            registry.execute(
                "apply_diagram_changes",
                {
                    "actions": [
                        {
                            "operation_id": f"rel-struct-{st}",
                            "kind": "CREATE_RELATION",
                            "relation_type": st,
                            "source_class_id": s_id,
                            "target_class_id": t_id,
                        }
                    ]
                },
            )
        )
        assert rel_res["status"] == "applied"
        assert len(rel_res["results"][0]["entity_refs"]) >= 1



