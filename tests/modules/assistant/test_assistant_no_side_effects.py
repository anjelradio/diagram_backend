from pathlib import Path


def test_diagram_dependencies_are_confined_to_authorized_agent_adapters():
    module_root = Path(__file__).parents[3] / "app" / "modules" / "assistant"
    allowed = {
        # Parses provider output against Diagram's enum contracts; it does not
        # invoke Diagram use cases or repositories directly.
        "application/services/visual/visual_contracts.py",
        "application/services/diagram/diagram_read_tools.py",
        "application/services/diagram/diagram_mutation_tools.py",
        "application/services/diagram/diagram_tool_schemas.py",
        "application/services/diagram/diagram_class_tools.py",
        "application/services/diagram/diagram_attribute_tools.py",
        "application/services/diagram/diagram_relation_tools.py",
        "application/services/diagram/diagram_layout_optimizer.py",
        "application/services/diagram/agent_relation_policy.py",
            # Reads current Diagram state to ground user-facing recommendations.
            "application/services/diagram/grounded_recommendation.py",
        "infrastructure/api/routers/assistant_router.py",
        "infrastructure/realtime/agent_completion_publisher.py",
        "infrastructure/realtime/agent_acceptance_publisher.py",
        "infrastructure/realtime/agent_activity_publisher.py",
        "infrastructure/realtime/agent_component_reservation_publisher.py",
        # Maps diagram domain exceptions to terminal failures without invoking use cases.
        "application/services/execution/terminal_failure.py",
        # Composition root that binds the authorized adapters to the worker.
        "infrastructure/services/agent_runtime_factory.py",
    }
    for path in module_root.rglob("*.py"):
        relative = path.relative_to(module_root).as_posix()
        source = path.read_text()
        if "app.modules.diagram" in source:
            assert relative in allowed, f"Diagram dependency escaped its adapter: {relative}"
        if "connection_manager" in source:
            assert relative in {
                "infrastructure/realtime/agent_completion_publisher.py",
                "infrastructure/realtime/agent_acceptance_publisher.py",
                "infrastructure/realtime/agent_activity_publisher.py",
                "infrastructure/realtime/agent_component_reservation_publisher.py",
            }
        assert "Gemini" not in source
