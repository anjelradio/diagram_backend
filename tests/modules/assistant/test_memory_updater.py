from unittest.mock import AsyncMock
import pytest

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiProvider,
    AiResult,
    ModelRole,
)
from app.modules.assistant.application.services.memory_updater import MemoryUpdater
from app.modules.assistant.application.services.memory_evidence import ConfirmedOperation
from app.modules.assistant.application.services.token_estimator import TokenEstimator
from app.modules.assistant.domain.exceptions import (
    AgentMemoryUpdateException,
    AiProviderError,
    AiProviderErrorReason,
)


class DummyAiProvider(AiProvider):
    def __init__(self, response_text: str | Exception):
        self.response_text = response_text
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if isinstance(self.response_text, Exception):
            raise self.response_text
        return AiResult(
            text=self.response_text,
            model_role=ModelRole.COMPACTION,
            model="qwen-compaction",
            completed=True,
        )


@pytest.mark.anyio
async def test_memory_updater_generates_selective_sections_with_evidence():
    valid_selective_output = (
        "## Objetivos activos\n"
        "- Diseñar módulo de facturación\n\n"
        "## Preferencias del usuario\n"
        "- Nombres de clases en español singular\n\n"
        "## Decisiones y restricciones vigentes\n"
        "- Factura se relaciona con Cliente\n\n"
        "## Resultados confirmados relevantes\n"
        "- CREATE_CLASS: Factura\n\n"
        "## Pendientes o dudas\n"
        "- Atributos pendientes de Factura"
    )
    provider = DummyAiProvider(valid_selective_output)
    estimator = TokenEstimator()
    updater = MemoryUpdater(provider, estimator, max_tokens=7000)

    confirmed_ops = [
        ConfirmedOperation(
            operation_id="op-1",
            action_kind="CREATE_CLASS",
            entity_refs=({"type": "class", "id": "factura-id"},),
            summary="CREATE_CLASS: Factura",
        )
    ]

    result = await updater.update(
        current_summary="## Memoria inicial",
        prompt="Crea la clase Factura para el módulo de facturación",
        response_markdown="He creado la clase Factura.",
        confirmed_operations=confirmed_ops,
    )

    assert result == valid_selective_output
    assert len(provider.requests) == 1
    req = provider.requests[0]
    assert req.model_role == ModelRole.COMPACTION
    assert req.purpose == "memory_update"
    assert req.enable_reasoning is False
    # Ensure URL sanitization and payload content
    user_payload_content = req.messages[1].content
    assert "factura-id" not in user_payload_content  # Formatter strips internal UUIDs
    assert "Factura" in user_payload_content


@pytest.mark.anyio
async def test_memory_updater_fails_cleanly_on_missing_required_sections():
    # Salida que no contiene todas las 5 secciones obligatorias
    invalid_output = "## Objetivos activos\n- Solo un objetivo sin el resto de secciones"
    provider = DummyAiProvider(invalid_output)
    updater = MemoryUpdater(provider, TokenEstimator(), max_tokens=7000)

    with pytest.raises(AgentMemoryUpdateException):
        await updater.update(
            current_summary=None,
            prompt="Hola",
            response_markdown="Hola, ¿en qué te ayudo?",
        )


@pytest.mark.anyio
async def test_memory_updater_fails_cleanly_on_provider_error():
    provider = DummyAiProvider(AiProviderError(reason=AiProviderErrorReason.UNSPECIFIED))
    updater = MemoryUpdater(provider, TokenEstimator(), max_tokens=7000)

    with pytest.raises(AgentMemoryUpdateException):
        await updater.update(
            current_summary="## Memoria previa",
            prompt="Nuevo pedido",
            response_markdown="Entendido.",
        )


@pytest.mark.anyio
async def test_memory_updater_fails_on_empty_prompt_or_response():
    provider = DummyAiProvider("## Secciones")
    updater = MemoryUpdater(provider, TokenEstimator(), max_tokens=7000)

    with pytest.raises(AgentMemoryUpdateException):
        await updater.update(
            current_summary="## Memoria previa",
            prompt="   ",
            response_markdown="Respuesta",
        )


@pytest.mark.anyio
async def test_memory_updater_rejects_exceeding_max_characters():
    from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory

    oversized = (
        "## Objetivos activos\n"
        + ("x" * AgentUserMemory.MAX_SUMMARY_CONTEXT_CHARS)
        + "\n## Preferencias del usuario\n\n## Decisiones y restricciones vigentes\n\n## Resultados confirmados relevantes\n\n## Pendientes o dudas"
    )
    provider = DummyAiProvider(oversized)
    updater = MemoryUpdater(provider, TokenEstimator(), max_tokens=100_000)

    with pytest.raises(AgentMemoryUpdateException):
        await updater.update(
            current_summary="## Previa",
            prompt="Prompt",
            response_markdown="Resp",
        )


@pytest.mark.anyio
async def test_memory_updater_rejects_exceeding_token_budget():
    output = (
        "## Objetivos activos\n"
        + ("word " * 3000)
        + "\n## Preferencias del usuario\n\n## Decisiones y restricciones vigentes\n\n## Resultados confirmados relevantes\n\n## Pendientes o dudas"
    )
    provider = DummyAiProvider(output)
    # Small budget like 500 tokens
    updater = MemoryUpdater(provider, TokenEstimator(), max_tokens=500)

    with pytest.raises(AgentMemoryUpdateException):
        await updater.update(
            current_summary="## Previa",
            prompt="Prompt",
            response_markdown="Resp",
        )
