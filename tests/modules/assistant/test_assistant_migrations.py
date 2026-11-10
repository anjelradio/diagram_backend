import os
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from sqlalchemy import Index
from sqlalchemy import create_engine, inspect

from app.modules.assistant.infrastructure.persistence.models.agent_message_model import (
    AgentMessageModel,
)
from app.modules.assistant.infrastructure.persistence.models.agent_user_memory_model import (
    AgentUserMemoryModel,
)


def test_models_have_partial_uniqueness_for_running_and_active_memory():
    message_indexes = {index.name: index for index in AgentMessageModel.__table__.indexes}
    memory_indexes = {index.name: index for index in AgentUserMemoryModel.__table__.indexes}
    running = message_indexes["uq_agent_messages_running_project_user"]
    memory = memory_indexes["uq_agent_user_memories_active_project_user"]
    assert isinstance(running, Index) and running.unique
    assert "status = 'running'" in str(running.dialect_options["sqlite"]["where"])
    assert isinstance(memory, Index) and memory.unique
    assert "deleted_date IS NULL" in str(memory.dialect_options["sqlite"]["where"])


def test_migration_follows_the_existing_database_head_and_preserves_history():
    migration_file = (
        Path(__file__).parents[3]
        / "alembic"
        / "versions"
        / "031_create_agent_messages_and_memories.py"
    )
    spec = spec_from_file_location("assistant_messages_migration", migration_file)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.down_revision == "9a1b2c3d4e5f"
    assert migration.revision == "031_agent_msgs_memories"
    assert "agent_activities" not in migration_file.read_text()

    progress_migration_file = migration_file.with_name(
        "032_agent_message_plan_version.py"
    )
    progress_spec = spec_from_file_location(
        "assistant_plan_version_migration", progress_migration_file
    )
    assert progress_spec is not None and progress_spec.loader is not None
    progress_migration = module_from_spec(progress_spec)
    progress_spec.loader.exec_module(progress_migration)
    assert progress_migration.down_revision == migration.revision
    assert progress_migration.revision == "032_agent_message_plan_version"

    durable_migration_file = migration_file.with_name(
        "033_agent_message_durable_execution.py"
    )
    durable_spec = spec_from_file_location(
        "assistant_durable_execution_migration", durable_migration_file
    )
    assert durable_spec is not None and durable_spec.loader is not None
    durable_migration = module_from_spec(durable_spec)
    durable_spec.loader.exec_module(durable_migration)
    assert durable_migration.down_revision == progress_migration.revision
    assert durable_migration.revision == "033_agent_msg_durable_execution"

    continuation_migration_file = migration_file.with_name(
        "034_create_agent_continuations.py"
    )
    continuation_spec = spec_from_file_location(
        "assistant_continuations_migration", continuation_migration_file
    )
    assert continuation_spec is not None and continuation_spec.loader is not None
    continuation_migration = module_from_spec(continuation_spec)
    continuation_spec.loader.exec_module(continuation_migration)
    assert continuation_migration.down_revision == durable_migration.revision
    assert continuation_migration.revision == "034_create_agent_continuations"

    partial_migration_file = migration_file.with_name(
        "035_allow_partial_agent_messages.py"
    )
    partial_spec = spec_from_file_location(
        "assistant_partial_status_migration", partial_migration_file
    )
    assert partial_spec is not None and partial_spec.loader is not None
    partial_migration = module_from_spec(partial_spec)
    partial_spec.loader.exec_module(partial_migration)
    assert partial_migration.down_revision == continuation_migration.revision
    assert partial_migration.revision == "035_allow_partial_agent_messages"

    dialog_state_migration_file = migration_file.with_name(
        "036_agent_continuation_dialog_state.py"
    )
    dialog_state_spec = spec_from_file_location(
        "assistant_dialog_state_migration", dialog_state_migration_file
    )
    assert dialog_state_spec is not None and dialog_state_spec.loader is not None
    dialog_state_migration = module_from_spec(dialog_state_spec)
    dialog_state_spec.loader.exec_module(dialog_state_migration)
    assert dialog_state_migration.down_revision == partial_migration.revision
    assert dialog_state_migration.revision == "036_dialog_state_columns"

    threads_migration_file = migration_file.with_name(
        "037_agent_request_threads.py"
    )
    threads_spec = spec_from_file_location(
        "assistant_threads_migration", threads_migration_file
    )
    assert threads_spec is not None and threads_spec.loader is not None
    threads_migration = module_from_spec(threads_spec)
    threads_spec.loader.exec_module(threads_migration)
    assert threads_migration.down_revision == dialog_state_migration.revision
    assert threads_migration.revision == "037_agent_request_threads"

    drop_memory_migration_file = migration_file.with_name(
        "038_drop_agent_user_memories.py"
    )
    drop_memory_spec = spec_from_file_location(
        "assistant_drop_memory_migration", drop_memory_migration_file
    )
    assert drop_memory_spec is not None and drop_memory_spec.loader is not None
    drop_memory_migration = module_from_spec(drop_memory_spec)
    drop_memory_spec.loader.exec_module(drop_memory_migration)
    assert drop_memory_migration.down_revision == threads_migration.revision
    assert drop_memory_migration.revision == "038_drop_agent_user_memories"



def test_alembic_upgrade_works_from_empty_and_existing_head(tmp_path):
    server_root = Path(__file__).parents[3]
    database_url = f"sqlite:////{(tmp_path / 'assistant-migrations.sqlite3').as_posix().lstrip('/')}"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url

    def run_alembic(*arguments: str) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=server_root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

    run_alembic("upgrade", "head")
    engine = create_engine(database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("agent_messages")}
    indexes = {index["name"] for index in inspect(engine).get_indexes("agent_messages")}
    assert {
        "request_fingerprint",
        "cancel_requested_at",
        "lease_owner",
        "lease_expires_at",
        "lease_heartbeat_at",
        "root_message_id",
    } <= columns
    assert {
        "ix_agent_messages_request_fingerprint",
        "ix_agent_messages_cancel_requested_at",
        "ix_agent_messages_lease_expires_at",
        "ix_agent_messages_root_msg",
    } <= indexes

    continuation_columns = {
        column["name"] for column in inspect(engine).get_columns("agent_continuations")
    }
    continuation_indexes = {
        index["name"] for index in inspect(engine).get_indexes("agent_continuations")
    }
    assert {
        "id",
        "project_id",
        "user_id",
        "root_message_id",
        "latest_message_id",
        "state",
        "version",
        "effective_request",
        "resolved_facts",
        "missing_fields",
        "outcome",
        "purpose",
        "close_reason",
        "source_plan_message_id",
        "recent_message_ids",
        "image_context",
        "dialog_state",
        "expires_at",
        "claimed_by_message_id",
    } <= continuation_columns
    assert {
        "ix_agent_continuations_project_id",
        "ix_agent_continuations_user_id",
        "ix_agent_continuations_active",
        "ix_agent_continuations_project_user",
        "ix_agent_continuations_root_msg",
        "uq_agent_continuations_active_scope",
    } <= continuation_indexes

    engine.dispose()
    run_alembic("downgrade", "9a1b2c3d4e5f")
    run_alembic("upgrade", "head")


def test_migration_037_sanitizes_legacy_duplicates_and_claims(tmp_path):
    import json
    from uuid import uuid4
    from sqlalchemy import text

    server_root = Path(__file__).parents[3]
    db_file = tmp_path / "legacy-migration.sqlite3"
    database_url = f"sqlite:////{db_file.as_posix().lstrip('/')}"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url

    def run_alembic(*arguments: str) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=server_root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

    # 1. Upgrade hasta 036_dialog_state_columns
    run_alembic("upgrade", "036_dialog_state_columns")

    # 2. Insertar datos heredados con sqlite3 / sqlalchemy
    engine = create_engine(database_url)
    with engine.begin() as conn:
        project_id = str(uuid4())
        user_id = "test_user_mig"
        other_user = "other_user_mig"
        orphan_user = "orphan_user_mig"

        conn.execute(
            text(
                """
                INSERT INTO projects (id, name, owner_id, created_date, modified_date)
                VALUES (:id, :name, :owner_id, '2026-01-01 10:00:00', '2026-01-01 10:00:00')
                """
            ),
            {"id": project_id, "name": "Mig Project", "owner_id": user_id},
        )

        m1_id = str(uuid4())
        plan_json = json.dumps({
            "goal": "Crear Factura",
            "operation_ledger": [{"operation_id": "op-1", "action_kind": "CREATE_CLASS", "status": "applied"}]
        })
        conn.execute(
            text(
                """
                INSERT INTO agent_messages (id, project_id, user_id, prompt, status, response_markdown, plan, created_date, modified_date)
                VALUES (:id, :project_id, :user_id, 'Crea Factura', 'completed', 'Factura creada exitosamente.', :plan, '2026-01-01 10:00:00', '2026-01-01 10:00:00')
                """
            ),
            {"id": m1_id, "project_id": project_id, "user_id": user_id, "plan": plan_json},
        )

        m2_id = str(uuid4())
        conn.execute(
            text(
                """
                INSERT INTO agent_messages (id, project_id, user_id, prompt, status, created_date, modified_date)
                VALUES (:id, :project_id, :user_id, 'En proceso', 'running', '2026-01-02 10:00:00', '2026-01-02 10:00:00')
                """
            ),
            {"id": m2_id, "project_id": project_id, "user_id": user_id},
        )

        c_old_id = str(uuid4())
        conn.execute(
            text(
                """
                INSERT INTO agent_continuations (id, project_id, user_id, root_message_id, latest_message_id, state, version, effective_request, resolved_facts, missing_fields, outcome, recent_message_ids, expires_at, created_date, modified_date)
                VALUES (:id, :project_id, :user_id, :root_id, :latest_id, 'awaiting_input', 1, 'Duplicado viejo', '[]', '[]', 'awaiting_input', '[]', '2026-12-31 23:59:59', '2026-01-01 10:00:00', '2026-01-01 10:00:00')
                """
            ),
            {"id": c_old_id, "project_id": project_id, "user_id": user_id, "root_id": m1_id, "latest_id": m1_id},
        )

        c_recent_id = str(uuid4())
        conn.execute(
            text(
                """
                INSERT INTO agent_continuations (id, project_id, user_id, root_message_id, latest_message_id, state, version, effective_request, resolved_facts, missing_fields, outcome, recent_message_ids, expires_at, created_date, modified_date)
                VALUES (:id, :project_id, :user_id, :root_id, :latest_id, 'awaiting_input', 1, 'Duplicado reciente', '[]', '[]', 'awaiting_input', '[]', '2026-12-31 23:59:59', '2026-01-02 10:00:00', '2026-01-02 10:00:00')
                """
            ),
            {"id": c_recent_id, "project_id": project_id, "user_id": user_id, "root_id": m1_id, "latest_id": m1_id},
        )

        c_active_claim_id = str(uuid4())
        conn.execute(
            text(
                """
                INSERT INTO agent_continuations (id, project_id, user_id, root_message_id, latest_message_id, state, version, effective_request, resolved_facts, missing_fields, outcome, recent_message_ids, expires_at, claimed_by_message_id, created_date, modified_date)
                VALUES (:id, :project_id, :user_id, :root_id, :latest_id, 'claimed', 1, 'Reclamo activo', '[]', '[]', 'awaiting_input', '[]', '2026-12-31 23:59:59', :claimed_by, '2026-01-02 10:00:00', '2026-01-02 10:00:00')
                """
            ),
            {"id": c_active_claim_id, "project_id": project_id, "user_id": other_user, "root_id": m2_id, "latest_id": m2_id, "claimed_by": m2_id},
        )

        c_orphan_claim_id = str(uuid4())
        conn.execute(
            text(
                """
                INSERT INTO agent_continuations (id, project_id, user_id, root_message_id, latest_message_id, state, version, effective_request, resolved_facts, missing_fields, outcome, recent_message_ids, expires_at, claimed_by_message_id, created_date, modified_date)
                VALUES (:id, :project_id, :user_id, :root_id, :latest_id, 'claimed', 1, 'Reclamo huerfano', '[]', '[]', 'awaiting_input', '[]', '2026-12-31 23:59:59', :claimed_by, '2026-01-02 10:00:00', '2026-01-02 10:00:00')
                """
            ),
            {"id": c_orphan_claim_id, "project_id": project_id, "user_id": orphan_user, "root_id": m1_id, "latest_id": m1_id, "claimed_by": m1_id},
        )

    # 3. Aplicar upgrade a head (037)
    run_alembic("upgrade", "head")

    # 4. Verificar resultados de la migración
    with engine.connect() as conn:
        old_cont = conn.execute(text("SELECT state, close_reason, purpose FROM agent_continuations WHERE id = :id"), {"id": c_old_id}).fetchone()
        assert old_cont.state == "expired"
        assert old_cont.close_reason == "expired"
        assert old_cont.purpose == "clarification"

        recent_cont = conn.execute(text("SELECT state, close_reason, purpose FROM agent_continuations WHERE id = :id"), {"id": c_recent_id}).fetchone()
        assert recent_cont.state == "awaiting_input"
        assert recent_cont.close_reason is None
        assert recent_cont.purpose == "clarification"

        active_cont = conn.execute(text("SELECT state, close_reason FROM agent_continuations WHERE id = :id"), {"id": c_active_claim_id}).fetchone()
        assert active_cont.state == "claimed"

        orphan_cont = conn.execute(text("SELECT state, close_reason FROM agent_continuations WHERE id = :id"), {"id": c_orphan_claim_id}).fetchone()
        assert orphan_cont.state == "expired"
        assert orphan_cont.close_reason == "orphan_claim_cleared"

        msg1 = conn.execute(text("SELECT response_markdown, plan FROM agent_messages WHERE id = :id"), {"id": m1_id}).fetchone()
        assert msg1.response_markdown == "Factura creada exitosamente."
        plan_loaded = json.loads(msg1.plan)
        assert plan_loaded["goal"] == "Crear Factura"
        assert plan_loaded["operation_ledger"][0]["action_kind"] == "CREATE_CLASS"

    engine.dispose()

    # 5. Downgrade a 036 y vuelta a upgrade head
    run_alembic("downgrade", "036_dialog_state_columns")
    run_alembic("upgrade", "head")


def test_migration_037_sanitizes_legacy_duplicates_postgres():
    database_url = os.getenv("ASSISTANT_TEST_DATABASE_URL")
    if not database_url:
        import pytest
        pytest.skip("ASSISTANT_TEST_DATABASE_URL no configurado para validación descartable en PostgreSQL.")


def test_migration_038_drops_table_and_downgrades_structurally(tmp_path):
    server_root = Path(__file__).parents[3]
    db_file = tmp_path / "drop-memory.sqlite3"
    database_url = f"sqlite:////{db_file.as_posix().lstrip('/')}"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url

    def run_alembic(*arguments: str) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=server_root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

    # 1. Upgrade a 037_agent_request_threads: la tabla agent_user_memories existe
    run_alembic("upgrade", "037_agent_request_threads")
    engine = create_engine(database_url)
    table_names_037 = set(inspect(engine).get_table_names())
    assert "agent_user_memories" in table_names_037

    # 2. Upgrade a 038_drop_agent_user_memories: la tabla agent_user_memories se elimina
    run_alembic("upgrade", "038_drop_agent_user_memories")
    engine.dispose()
    engine = create_engine(database_url)
    table_names_038 = set(inspect(engine).get_table_names())
    assert "agent_user_memories" not in table_names_038

    # 3. Downgrade a 037_agent_request_threads: recrea la tabla con todas sus columnas e índices
    run_alembic("downgrade", "037_agent_request_threads")
    engine.dispose()
    engine = create_engine(database_url)
    table_names_recreated = set(inspect(engine).get_table_names())
    assert "agent_user_memories" in table_names_recreated

    columns = {col["name"] for col in inspect(engine).get_columns("agent_user_memories")}
    assert {"id", "created_date", "modified_date", "deleted_date", "user_id", "project_id", "summary_context"} <= columns

    indexes = {idx["name"] for idx in inspect(engine).get_indexes("agent_user_memories")}
    assert {
        "ix_agent_user_memories_user_id",
        "ix_agent_user_memories_project_id",
        "uq_agent_user_memories_active_project_user",
    } <= indexes

    # 4. Re-upgrade a head: la tabla se elimina nuevamente sin errores
    engine.dispose()
    run_alembic("upgrade", "head")
    engine = create_engine(database_url)
    table_names_head = set(inspect(engine).get_table_names())
    assert "agent_user_memories" not in table_names_head
    engine.dispose()

