import pytest

from app.modules.assistant.domain.entities.execution_plan import ExecutionPlan
from app.modules.assistant.domain.exceptions import (
    ExecutionPlanErrorReason,
    InvalidExecutionPlanException,
)


def test_execution_plan_round_trips_a_valid_dependency_graph():
    plan = ExecutionPlan.create(
        goal="Crear clases y luego la relación",
        tasks=[
            {"id": "create-classes", "objective": "Crear las clases"},
            {
                "id": "create-relation",
                "objective": "Relacionarlas",
                "depends_on": ["create-classes"],
            },
        ],
        limits={"tool_calls": 5},
    )

    restored = ExecutionPlan.from_dict(plan.to_dict())

    assert restored.goal == plan.goal
    assert restored.tasks[1]["depends_on"] == ["create-classes"]
    assert restored.limits == {"tool_calls": 5}


@pytest.mark.parametrize(
    ("tasks", "reason"),
    [
        ([
            {"id": "a", "objective": "A", "depends_on": ["b"]},
            {"id": "b", "objective": "B", "depends_on": ["a"]},
        ], ExecutionPlanErrorReason.PLAN_CYCLIC_DEPENDENCY),
        ([{"id": "a", "objective": "A", "depends_on": ["missing"]}],
         ExecutionPlanErrorReason.PLAN_INVALID_DEPENDENCY),
        ([{"id": "a", "objective": "A"}, {"id": "a", "objective": "A"}],
         ExecutionPlanErrorReason.PLAN_DUPLICATE_TASK_ID),
    ],
)
def test_execution_plan_rejects_cycles_unknown_dependencies_and_duplicate_ids(tasks, reason):
    with pytest.raises(InvalidExecutionPlanException) as failure:
        ExecutionPlan.create(goal="Plan inválido", tasks=tasks)
    assert failure.value.reason is reason


def test_execution_plan_rejects_unknown_version_or_invalid_status():
    plan = ExecutionPlan.create(
        goal="Plan válido", tasks=[{"id": "a", "objective": "Tarea A"}]
    ).to_dict()
    plan["version"] = 2

    with pytest.raises(InvalidExecutionPlanException):
        ExecutionPlan.from_dict(plan)

    plan["version"] = 1
    plan["tasks"][0]["status"] = "done"
    with pytest.raises(InvalidExecutionPlanException):
        ExecutionPlan.from_dict(plan)


def test_execution_plan_blocks_descendants_when_task_fails():
    plan = ExecutionPlan.create(
        goal="Plan con dependencias en cadena e independientes",
        tasks=[
            {"id": "t1", "objective": "Tarea 1", "depends_on": []},
            {"id": "t2", "objective": "Tarea 2 (depende de 1)", "depends_on": ["t1"]},
            {"id": "t3", "objective": "Tarea 3 (depende de 2)", "depends_on": ["t2"]},
            {"id": "t_indep", "objective": "Tarea Independiente", "depends_on": []},
        ],
    )

    ready = [t["id"] for t in plan.get_ready_tasks()]
    assert set(ready) == {"t1", "t_indep"}

    blocked = plan.mark_task_status("t1", "failed", error_code="timeout")
    assert set(blocked) == {"t2", "t3"}

    assert plan.get_task("t1")["status"] == "failed"
    assert plan.get_task("t2")["status"] == "blocked"
    assert plan.get_task("t3")["status"] == "blocked"
    # La tarea independiente sigue en estado pending y lista para ejecutarse
    assert plan.get_task("t_indep")["status"] == "pending"
    assert [t["id"] for t in plan.get_ready_tasks()] == ["t_indep"]


def test_execution_plan_extracts_only_confirmed_refs_scoped_to_prerequisites():
    plan = ExecutionPlan.create(
        goal="Plan con ledger",
        tasks=[
            {"id": "t1", "objective": "Crear A", "depends_on": []},
            {"id": "t2", "objective": "Crear B", "depends_on": []},
            {"id": "t3", "objective": "Relacionar A con B", "depends_on": ["t1", "t2"]},
        ],
    )
    plan.operation_ledger = [
        {
            "operation_id": "op1",
            "task_id": "t1",
            "status": "applied",
            "entity_refs": [{"type": "class", "id": "id-a", "name": "A"}],
        },
        {
            "operation_id": "op2",
            "task_id": "t2",
            "status": "applied",
            "entity_refs": [{"type": "class", "id": "id-b", "name": "B"}],
        },
        {
            "operation_id": "op_unconfirmed",
            "task_id": "t1",
            "status": "proposed",
            "entity_refs": [{"type": "class", "id": "id-leak", "name": "NoAplicado"}],
        },
    ]

    # t3 recibe refs confirmadas de sus prerequisitos (t1 y t2)
    refs_for_t3 = plan.get_confirmed_entity_refs("t3")
    assert len(refs_for_t3) == 2
    assert {r["id"] for r in refs_for_t3} == {"id-a", "id-b"}
    # La operación en estado "proposed" jamás se filtra como confirmada
    assert not any(r["id"] == "id-leak" for r in refs_for_t3)


def test_execution_plan_rejects_invalid_result_refs_and_ledger_refs():
    plan = ExecutionPlan.create(
        goal="Plan válido", tasks=[{"id": "a", "objective": "Tarea A"}]
    ).to_dict()
    plan["tasks"][0]["result_refs"] = [{"invalid": "no type or id"}]
    with pytest.raises(InvalidExecutionPlanException):
        ExecutionPlan.from_dict(plan)

    plan["tasks"][0]["result_refs"] = []
    plan["operation_ledger"] = [{"operation_id": "op1", "status": "applied", "entity_refs": "not-a-list"}]
    with pytest.raises(InvalidExecutionPlanException):
        ExecutionPlan.from_dict(plan)


def test_execution_plan_round_trips_partial_status():
    plan_dict = ExecutionPlan.create(
        goal="Plan con estado parcial",
        tasks=[
            {"id": "t1", "objective": "Tarea 1", "status": "completed"},
            {
                "id": "t2",
                "objective": "Tarea 2",
                "status": "failed",
                "error_code": "class_not_found",
                "failure_reason": "class_not_available",
            },
        ],
    ).to_dict()
    plan_dict["status"] = "partial"

    restored = ExecutionPlan.from_dict(plan_dict)
    assert restored.status == "partial"
    assert restored.get_task("t2")["failure_reason"] == "class_not_available"


@pytest.mark.parametrize(
    ("t1_status", "t2_status", "ledger_uncertain", "expected_status"),
    [
        ("completed", "completed", False, "completed"),
        ("failed", "blocked", False, "failed"),
        ("completed", "failed", False, "partial"),
        ("completed", "blocked", False, "partial"),
        ("completed", "completed", True, "uncertain"),
    ],
)
def test_execution_plan_recomputes_overall_status_accurately(
    t1_status, t2_status, ledger_uncertain, expected_status
):
    plan = ExecutionPlan.create(
        goal="Calcular estado global",
        tasks=[
            {"id": "t1", "objective": "Tarea 1"},
            {"id": "t2", "objective": "Tarea 2", "depends_on": ["t1"]},
        ],
    )
    plan.get_task("t1")["status"] = t1_status
    plan.get_task("t2")["status"] = t2_status
    if ledger_uncertain:
        plan.operation_ledger = [
            {"operation_id": "op-u", "task_id": "t1", "status": "uncertain", "entity_refs": []}
        ]

    calculated = plan.recompute_overall_status()
    assert calculated == expected_status
    assert plan.status == expected_status


def test_execution_plan_validates_safe_failure_reason():
    plan_dict = ExecutionPlan.create(
        goal="Plan válido", tasks=[{"id": "a", "objective": "Tarea A"}]
    ).to_dict()
    plan_dict["tasks"][0]["failure_reason"] = ""
    with pytest.raises(InvalidExecutionPlanException):
        ExecutionPlan.from_dict(plan_dict)

    plan_dict["tasks"][0]["failure_reason"] = 123
    with pytest.raises(InvalidExecutionPlanException):
        ExecutionPlan.from_dict(plan_dict)


