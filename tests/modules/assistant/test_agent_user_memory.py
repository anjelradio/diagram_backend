from uuid import uuid4

from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory


def test_memory_is_scoped_and_gets_server_generated_uuid():
    project_id = uuid4()
    memory = AgentUserMemory.create(
        user_id="user-1", project_id=project_id, summary_context="Context"
    )

    assert memory.id is not None
    assert memory.project_id == project_id
    assert memory.user_id == "user-1"
    assert memory.summary_context == "Context"


def test_interaction_memory_keeps_only_confirmed_operation_facts():
    memory = AgentUserMemory.create(
        user_id="user-1", project_id=uuid4(), summary_context="## Proyecto\nERD"
    )

    memory.append_interaction(
        "Crea Producto y luego borra Secreto",
        "Producto quedó creado; Secreto falló.",
        confirmed_operations=[
            {
                "status": "applied",
                "action_kind": "CREATE_CLASS",
                "entity_refs": [{"type": "class", "id": "product-id"}],
            },
            {
                "status": "rejected",
                "action_kind": "DELETE_CLASS",
                "entity_refs": [{"type": "class", "id": "secret-id"}],
            },
        ],
    )

    assert "CREATE_CLASS" in memory.summary_context
    assert "product-id" in memory.summary_context
    assert "secret-id" not in memory.summary_context


def test_selective_memory_format_structure():
    """Valida la aceptación de la estructura lógica de memoria selectiva."""
    selective_summary = (
        "## Objetivos activos\n"
        "- Diseñar el módulo de facturación electrónica.\n\n"
        "## Preferencias del usuario\n"
        "- Lenguaje preferido: Python y nombres en singular.\n\n"
        "## Decisiones y restricciones vigentes\n"
        "- Usar UUIDv4 para identificadores primarios.\n\n"
        "## Resultados confirmados relevantes\n"
        "- Creación de clase Factura (confirmada en ledger).\n\n"
        "## Pendientes o dudas\n"
        "- Pendiente definir si Factura tiene detalle o ítem múltiple."
    )
    memory = AgentUserMemory.create(
        user_id="user-1", project_id=uuid4(), summary_context=selective_summary
    )

    assert "## Objetivos activos" in memory.summary_context
    assert "## Preferencias del usuario" in memory.summary_context
    assert "## Decisiones y restricciones vigentes" in memory.summary_context
    assert "## Resultados confirmados relevantes" in memory.summary_context
    assert "## Pendientes o dudas" in memory.summary_context


def test_memory_update_substitutes_outdated_corrections():
    """Una actualización sustituye información anterior contradictoria."""
    memory = AgentUserMemory.create(
        user_id="user-1",
        project_id=uuid4(),
        summary_context="## Preferencias del usuario\n- Idioma: Inglés",
    )

    # El usuario corrige su preferencia a Español
    corrected_summary = "## Preferencias del usuario\n- Idioma: Español (corregido por el usuario)"
    memory.update_summary_context(corrected_summary)

    assert "Español" in memory.summary_context
    assert "Inglés" not in memory.summary_context


def test_memory_does_not_slice_middle_of_text_at_char_limit():
    """No se utiliza recorte destructivo en medio que elimine decisiones vigentes."""
    initial = "INICIO\n" + "DATO_MEDIO_VIGENTE\n" + "Z" * 1000
    memory = AgentUserMemory.create(
        user_id="user-1", project_id=uuid4(), summary_context=initial
    )

    # Añadir interacción que supere el límite
    overflow_prompt = "P" * 1000
    overflow_resp = "R" * 23000
    memory.append_interaction(overflow_prompt, overflow_resp)

    # No debe existir el marcador antiguo de corte central
    assert "[…contexto anterior abreviado…]" not in memory.summary_context
    assert len(memory.summary_context) <= memory.MAX_SUMMARY_CONTEXT_CHARS


def test_memory_accepts_legacy_freeform_markdown():
    """Memorias antiguas en formato libre se cargan y preservan sin error."""
    legacy = "Proyecto de ecommerce. Tablas: ordenes, clientes. Sin formato formal."
    memory = AgentUserMemory.create(
        user_id="user-1", project_id=uuid4(), summary_context=legacy
    )
    assert memory.summary_context == legacy


def test_agent_memory_corpus_evaluation_against_sc002():
    """T029 [SC-002]: Evalúa retención >= 90%, cero hechos no confirmados y presupuesto de tokens."""
    from tests.modules.assistant.fixtures.agent_memory_cases import evaluate_corpus_against_sc002

    results = evaluate_corpus_against_sc002()
    assert results["passes_sc002"] is True
    assert results["retention_rate"] >= 90.0
    assert results["forbidden_violations"] == 0
    assert results["avg_tokens_per_case"] < 7000

