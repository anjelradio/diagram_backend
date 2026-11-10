"""El lote conserva el destino de cada acción para verificar el plan."""

import pytest

from app.modules.assistant.application.services.diagram.diagram_mutation_tools import DiagramMutationTools


@pytest.mark.anyio
async def test_batched_actions_report_distinct_target_names(monkeypatch):
    async def apply_one(self, action, report, selected_class_ids):
        await report({
            "operation_id": action["operation_id"],
            "action_kind": action["kind"],
            "status": "applied",
            "entity_refs": [],
        })
        return {"status": "applied", "entity_refs": [], "derived_effects": []}

    monkeypatch.setattr(DiagramMutationTools, "_apply_one", apply_one)
    tool = DiagramMutationTools.__new__(DiagramMutationTools)
    events = []

    async def report(event):
        events.append(event)

    result = await tool._apply_actions({"actions": [
        {"operation_id": "first", "kind": "CREATE_CLASS", "name": "Producto"},
        {"operation_id": "second", "kind": "CREATE_CLASS", "name": "Categoria"},
    ]}, report, {})

    assert result["status"] == "applied"
    assert [event["target_name"] for event in events] == ["Producto", "Categoria"]
