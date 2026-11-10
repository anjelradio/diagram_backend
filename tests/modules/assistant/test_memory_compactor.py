import pytest

from app.modules.assistant.application.ports.providers.ai_provider import AiResult, ModelRole
from app.modules.assistant.application.services.memory_compactor import MemoryCompactor
from app.modules.assistant.application.services.token_estimator import TokenEstimator
from app.modules.assistant.domain.exceptions import AgentMemoryCompactionException


@pytest.fixture
def anyio_backend():
    return "asyncio"


class ProviderStub:
    def __init__(self, text):
        self.text = text
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return AiResult(
            text=self.text,
            model_role=request.model_role,
            model="compact-model",
        )


@pytest.mark.anyio
async def test_compacts_as_markdown_using_only_the_compaction_role():
    provider = ProviderStub("## Objetivo\nModelar una biblioteca.")
    compactor = MemoryCompactor(provider, TokenEstimator(), max_tokens=7000)

    result = await compactor.compact("## History\n" + ("a" * 20_000))

    assert result.startswith("## Objetivo")
    assert provider.requests[0].model_role is ModelRole.COMPACTION
    assert provider.requests[0].enable_reasoning is False
    assert provider.requests[0].max_output_tokens > 0
    assert "no confiables" in provider.requests[0].messages[0].content.lower()


@pytest.mark.parametrize("value", ["", "   ", "x" * 10_501])
@pytest.mark.anyio
async def test_rejects_empty_or_oversized_compacted_memory(value):
    compactor = MemoryCompactor(ProviderStub(value), TokenEstimator(), max_tokens=7000)

    with pytest.raises(AgentMemoryCompactionException):
        await compactor.compact("old memory")


@pytest.mark.anyio
async def test_compacted_result_must_fit_half_the_configured_token_budget():
    compactor = MemoryCompactor(
        ProviderStub("x" * 10_501), TokenEstimator(), max_tokens=7000
    )

    with pytest.raises(AgentMemoryCompactionException):
        await compactor.compact("old memory")


@pytest.mark.anyio
async def test_compactor_system_prompt_prioritizes_active_goals_and_decisions():
    provider = ProviderStub("## Objetivos activos\n- Crear Factura\n\n## Preferencias del usuario\n\n## Decisiones y restricciones vigentes\n\n## Resultados confirmados relevantes\n\n## Pendientes o dudas")
    compactor = MemoryCompactor(provider, TokenEstimator(), max_tokens=7000)

    await compactor.compact("## Memoria previa extensa...")

    system_prompt = provider.requests[0].messages[0].content
    assert "objetivos activos" in system_prompt.lower()
    assert "preferencias" in system_prompt.lower()
    assert "decisiones" in system_prompt.lower()
    assert "datos no confiables" in system_prompt.lower()


@pytest.mark.anyio
async def test_compactor_unwraps_code_blocks_and_sanitizes_urls():
    wrapped_output = "```markdown\n## Objetivos activos\n- Consulta en https://example.com/api/v1/data\n```"
    provider = ProviderStub(wrapped_output)
    compactor = MemoryCompactor(provider, TokenEstimator(), max_tokens=7000)

    result = await compactor.compact("## Memoria previa")

    assert not result.startswith("```")
    assert not result.endswith("```")
    assert "https://example.com" not in result
    assert "[URL omitida]" in result


@pytest.mark.anyio
async def test_compactor_rejects_exceeding_max_characters():
    from app.modules.assistant.domain.entities.agent_user_memory import AgentUserMemory

    oversized_text = "a" * (AgentUserMemory.MAX_SUMMARY_CONTEXT_CHARS + 1)
    provider = ProviderStub(oversized_text)
    # Give a huge token budget so token check doesn't trip first
    compactor = MemoryCompactor(provider, TokenEstimator(), max_tokens=100_000)

    with pytest.raises(AgentMemoryCompactionException):
        await compactor.compact("old memory")
