import json

import httpx
import pytest

from app.core.config import Settings
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiContentPart,
    AiMessage,
    AiRequest,
    ModelRole,
)
from app.modules.assistant.domain.exceptions import AiProviderError
from app.modules.assistant.infrastructure.external.qwen_ai_provider import QwenAiProvider


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _vision_request(url="https://res.cloudinary.com/demo/image/upload/diagram.png"):
    return AiRequest(
        model_role=ModelRole.VISION,
        messages=(
            AiMessage(
                role="user",
                content=(
                    AiContentPart(type="text", text="Identifica las entidades"),
                    AiContentPart(type="image_url", image_url=url),
                ),
            ),
        ),
        max_output_tokens=700,
    )


@pytest.mark.anyio
async def test_vision_payload_uses_saved_https_url_and_never_sends_binary():
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "qwen3-vl-plus"
        content = body["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": "Identifica las entidades"}
        assert content[1] == {
            "type": "image_url",
            "image_url": {"url": "https://res.cloudinary.com/demo/image/upload/diagram.png"},
        }
        assert b"binary" not in request.content
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Se ven dos entidades."}, "finish_reason": "stop"}]},
        )

    settings = Settings(
        _env_file=None,
        QWEN_API_KEY="secret",
        QWEN_BASE_URL="https://qwen.test/v1",
    )
    provider = QwenAiProvider(settings=settings, transport=httpx.MockTransport(handler))

    result = await provider.complete(_vision_request())

    assert result.text == "Se ven dos entidades."


@pytest.mark.anyio
async def test_vision_provider_rejects_non_https_image_urls_before_request():
    settings = Settings(_env_file=None, QWEN_API_KEY="secret")
    provider = QwenAiProvider(
        settings=settings,
        transport=httpx.MockTransport(lambda _request: pytest.fail("request must not be sent")),
    )

    with pytest.raises(AiProviderError):
        await provider.complete(_vision_request("http://example.com/image.png"))
