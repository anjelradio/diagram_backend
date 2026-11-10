import pytest

from app.modules.assistant.application.ports.providers.ai_provider import AiResult, ModelRole
from app.modules.assistant.application.services.visual.visual_contracts import parse_visual_intent
from app.modules.assistant.application.services.visual.visual_intent import VisualIntentAnalyzer
from app.modules.assistant.domain.exceptions import AiProviderError


class FakeProvider:
    def __init__(self, text):
        self.text = text
        self.calls = []

    async def complete(self, request):
        self.calls.append(request)
        return AiResult(text=self.text, model_role=request.model_role, model="test")


@pytest.mark.anyio
async def test_intent_analysis_receives_only_text_and_extracts_explicit_scope():
    provider = FakeProvider(
        '{"mode":"mutate","needs_image":true,'
        '"visual_request":"Producto y sus atributos",'
        '"scope":{"classes":["Producto"],"attributes":"all","relations":"none"},'
        '"independent_tasks":[],"clarification":null}'
    )

    intent = await VisualIntentAnalyzer(provider).analyze(
        "Crea solo Producto con sus atributos, sin relaciones"
    )

    assert intent.mode == "mutate"
    assert intent.scope["relations"] == "none"
    request = provider.calls[0]
    assert request.model_role is ModelRole.PLANNING
    assert all(isinstance(message.content, str) for message in request.messages)
    assert "Crea solo Producto" in request.messages[-1].content


def test_visual_intent_rejects_invalid_or_ambiguous_unstructured_output():
    with pytest.raises(AiProviderError):
        parse_visual_intent('{"mode":"mutate","needs_image":true}')


def test_visual_intent_accepts_clarification_without_requesting_image():
    intent = parse_visual_intent(
        '{"mode":"clarify","needs_image":false,"visual_request":"",'
        '"scope":{},"independent_tasks":[],"clarification":"¿Qué parte quieres importar?"}'
    )
    assert intent.mode == "clarify"


def test_visual_intent_normalizes_class_exclusion_from_provider():
    intent = parse_visual_intent(
        '{"mode":"mutate","needs_image":true,'
        '"visual_request":"Todas las clases excepto Lion",'
        '"scope":{"include":"all","exclude":["Lion"]},'
        '"independent_tasks":[],"clarification":null,"requested_mode":null}'
    )
    assert intent.scope == {"classes": {"include": "all", "exclude": ["Lion"]}}
