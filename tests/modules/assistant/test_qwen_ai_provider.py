import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiMessage,
    AiRequest,
    AiToolCall,
    AiToolDefinition,
    ModelRole,
)
from app.modules.assistant.domain.exceptions import (
    AiProviderError,
    AiProviderErrorReason,
    AiProviderUnavailableException,
    AiProviderUnavailableReason,
)
from app.modules.assistant.infrastructure.external.qwen_ai_provider import (
    QwenAiProvider,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _provider(handler, **settings_values):
    transport = httpx.MockTransport(handler)
    settings = Settings(
        _env_file=None,
        QWEN_API_KEY="test-secret-key",
        QWEN_BASE_URL="https://qwen.test/compatible-mode/v1",
        **settings_values,
    )
    return QwenAiProvider(settings=settings, transport=transport)


def _request(role: ModelRole = ModelRole.MAIN) -> AiRequest:
    return AiRequest(
        model_role=role,
        messages=(AiMessage(role="user", content="Resume este diagrama"),),
    )


@pytest.mark.parametrize(
    ("role", "model"),
    [
        (ModelRole.MAIN, "qwen3.7-plus"),
        (ModelRole.VISION, "qwen3-vl-plus"),
        (ModelRole.COMPACTION, "qwen3.8-flash"),
        (ModelRole.PLANNING, "qwen3.7-plus"),
        (ModelRole.EXECUTION, "qwen3.8-flash"),
    ],
)
async def test_selects_model_for_requested_role(role, model):
    async def handler(request):
        assert request.headers["authorization"] == "Bearer test-secret-key"
        assert str(request.url) == "https://qwen.test/compatible-mode/v1/chat/completions"
        body = __import__("json").loads(request.content)
        assert body["model"] == model
        assert body["stream"] is False
        assert "tools" not in body
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "respuesta"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    result = await _provider(handler).complete(_request(role))
    assert result.text == "respuesta"
    assert result.model_role is role
    assert result.input_tokens == 4
    assert result.output_tokens == 2


async def test_serializes_structured_non_reasoning_request():
    async def handler(request):
        body = __import__("json").loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert body["enable_thinking"] is False
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"goal":"G","tasks":[]}'},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    request = AiRequest(
        model_role=ModelRole.PLANNING,
        messages=(AiMessage(role="user", content="Devuelve JSON"),),
        response_format="json_object",
        enable_reasoning=False,
    )

    result = await _provider(handler).complete(request)

    assert result.text == '{"goal":"G","tasks":[]}'


async def test_rejects_request_that_exceeds_local_context_budget_before_http_call():
    called = False

    async def handler(_request):
        nonlocal called
        called = True
        return httpx.Response(500)

    request = AiRequest(
        model_role=ModelRole.PLANNING,
        messages=(AiMessage(role="user", content="x" * 900),),
        max_output_tokens=7_900,
        enable_reasoning=True,
    )

    with pytest.raises(AiProviderError) as error:
        await _provider(handler, AGENT_CONTEXT_MAX_TOKENS=8_000).complete(request)

    assert error.value.reason is AiProviderErrorReason.CONTEXT_BUDGET_EXCEEDED
    assert called is False


async def test_timeout_is_returned_as_safe_provider_error():
    async def handler(_request):
        raise httpx.ReadTimeout("private transport detail")

    with pytest.raises(AiProviderUnavailableException) as error:
        await _provider(handler).complete(_request())

    assert "private transport detail" not in str(error.value)
    assert "test-secret-key" not in str(error.value)
    assert error.value.reason is AiProviderUnavailableReason.TIMEOUT


@pytest.mark.parametrize("status_code", [429, 500, 503])
async def test_rejects_rate_limit_and_server_errors_without_leaking_body(status_code):
    async def handler(_request):
        return httpx.Response(status_code, text="private vendor response")

    with pytest.raises(AiProviderUnavailableException) as error:
        await _provider(handler).complete(_request())

    assert "private vendor response" not in str(error.value)
    assert "test-secret-key" not in str(error.value)
    assert error.value.reason is AiProviderUnavailableReason.HTTP_ERROR
    assert error.value.status_code == status_code


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            {"choices": [{"message": {"content": "  "}, "finish_reason": "stop"}]},
            AiProviderErrorReason.EMPTY_RESPONSE,
        ),
        (
            {
                "choices": [
                    {
                        "message": {"content": "respuesta incompleta"},
                        "finish_reason": "length",
                    }
                ]
            },
            AiProviderErrorReason.OUTPUT_TRUNCATED,
        ),
        ({"choices": []}, AiProviderErrorReason.MISSING_CHOICES),
    ],
)
async def test_rejects_empty_or_truncated_content(payload, reason):
    async def handler(_request):
        return httpx.Response(200, json=payload)

    with pytest.raises(AiProviderError) as error:
        await _provider(handler).complete(_request())
    assert error.value.reason is reason


async def test_dev_content_logging_shows_payload_and_response_without_api_key(caplog):
    async def handler(_request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "diagnostic-response"}, "finish_reason": "stop"}
                ]
            },
        )

    caplog.set_level(
        "INFO",
        logger="app.modules.assistant.infrastructure.external.qwen_ai_provider",
    )
    await _provider(
        handler,
        ENVIRONMENT="DEV",
        QWEN_DEBUG_LOG_CONTENT=True,
    ).complete(
        AiRequest(
            model_role=ModelRole.PLANNING,
            messages=(AiMessage(role="user", content="diagnostic-prompt"),),
            purpose="diagnostic-test",
        )
    )

    assert "purpose=diagnostic-test" in caplog.text
    assert "diagnostic-prompt" in caplog.text
    assert "diagnostic-response" in caplog.text
    assert "test-secret-key" not in caplog.text


async def test_missing_key_does_not_make_app_settings_unavailable_but_blocks_inference():
    settings = Settings(_env_file=None, QWEN_API_KEY="")
    provider = QwenAiProvider(settings=settings)

    with pytest.raises(AiProviderUnavailableException):
        await provider.complete(_request())


async def test_serializes_tools_and_parses_tool_call_without_text_content():
    async def handler(request):
        import json

        payload = json.loads(request.content)
        assert payload["parallel_tool_calls"] is False
        assert payload["enable_thinking"] is False
        assert payload["tools"][0]["function"]["name"] == "search_diagram_elements"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_diagram_elements",
                                        "arguments": '{"query":"Producto"}',
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
        )

    request = AiRequest(
        model_role=ModelRole.MAIN,
        messages=(AiMessage(role="user", content="Busca Producto"),),
        tools=(
            AiToolDefinition(
                name="search_diagram_elements",
                description="Busca elementos del proyecto.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
        ),
    )
    result = await _provider(handler).complete(request)
    assert result.text == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].arguments == {"query": "Producto"}


async def test_serializes_assistant_tool_calls_and_tool_result_messages():
    async def handler(request):
        import json

        payload = json.loads(request.content)
        assert payload["messages"][0]["tool_calls"][0]["id"] == "call_1"
        assert payload["messages"][1] == {
            "role": "tool",
            "content": '{"items": []}',
            "tool_call_id": "call_1",
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "No hay clases."}, "finish_reason": "stop"}]},
        )

    request = AiRequest(
        model_role=ModelRole.MAIN,
        messages=(
            AiMessage(
                role="assistant",
                content="",
                tool_calls=(
                    AiToolCall(
                        id="call_1",
                        name="search_diagram_elements",
                        arguments={"query": "X"},
                    ),
                ),
            ),
            AiMessage(role="tool", content='{"items": []}', tool_call_id="call_1"),
        ),
    )
    result = await _provider(handler).complete(request)
    assert result.text == "No hay clases."


@pytest.mark.parametrize(
    "override",
    [
        {"QWEN_BASE_URL": "http://qwen.test/v1"},
        {"QWEN_BASE_URL": "https://qwen.test:invalid/v1"},
        {"QWEN_TIMEOUT_SECONDS": 181},
        {"AGENT_MEMORY_MAX_TOKENS": 0},
        {"AGENT_CONTEXT_MAX_TOKENS": 8_000, "AGENT_MEMORY_MAX_TOKENS": 8_000},
        {
            "AGENT_CONTEXT_MAX_TOKENS": 8_000,
            "AGENT_PLANNING_MAX_OUTPUT_TOKENS": 8_000,
        },
        {"AGENT_MAX_PLAN_TASKS": 0},
        {"AGENT_MAX_TOOL_RESULT_CHARS": 511},
        {"AGENT_MAX_ELEMENT_DETAIL_ITEMS": 0},
    ],
)
def test_invalid_qwen_settings_are_rejected(override):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **override)
