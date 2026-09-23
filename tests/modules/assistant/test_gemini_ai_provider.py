import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.modules.assistant.domain.enums.agent_action_type import AgentActionType
from app.modules.assistant.domain.exceptions import (
    AiServiceUnavailableException,
)
from app.modules.assistant.infrastructure.external.gemini_ai_provider import (
    GeminiAiProvider,
)


def test_parse_response_json() -> None:
    provider = GeminiAiProvider(api_key="test-key")

    raw_json = json.dumps({
        "transcription": "Crear clase Usuario",
        "resume": "Se creará la clase Usuario.",
        "actions": [
            {
                "type": "CREATE_CLASS",
                "payload": {"name": "Usuario"},
            }
        ],
    })
    markdown_wrapped = f"```json\n{raw_json}\n```"

    result = provider._parse_response(markdown_wrapped)

    assert result.transcription == "Crear clase Usuario"
    assert result.resume == "Se creará la clase Usuario."
    assert len(result.actions) == 1
    assert result.actions[0].type == AgentActionType.CREATE_CLASS
    assert result.actions[0].payload["name"] == "Usuario"


def test_fallback_chain_when_first_model_fails() -> None:
    import asyncio

    async def _run():
        provider = GeminiAiProvider(api_key="test-key")
        provider.models_chain = ["model-1", "model-2"]

        mock_client = MagicMock()
        mock_aio = MagicMock()
        mock_models = MagicMock()

        # Primer modelo falla, segundo responde exitosamente
        success_response = MagicMock()
        success_response.text = json.dumps({
            "transcription": "Crear clase Factura",
            "resume": "Se creará la clase Factura.",
            "actions": [{"type": "CREATE_CLASS", "payload": {"name": "Factura"}}],
        })

        mock_models.generate_content = AsyncMock(
            side_effect=[Exception("Quota exceeded on model-1"), success_response]
        )
        mock_aio.models = mock_models
        mock_client.aio = mock_aio
        provider.client = mock_client

        result = await provider.interpret_voice_command(
            audio_data=b"fake-audio",
            audio_mime_type="audio/wav",
            diagram_snapshot={"classes": [], "relations": []},
            available_data_types=["TEXT"],
            available_relation_types=["ASSOCIATION"],
            available_cardinalities=["1"],
        )

        assert result.transcription == "Crear clase Factura"
        assert len(result.actions) == 1
        assert mock_models.generate_content.call_count == 2

    asyncio.run(_run())


def test_all_models_fail_raises_service_unavailable() -> None:
    import asyncio

    async def _run():
        provider = GeminiAiProvider(api_key="test-key")
        provider.models_chain = ["model-1", "model-2"]
        provider.max_cycles = 1

        mock_client = MagicMock()
        mock_aio = MagicMock()
        mock_models = MagicMock()
        mock_models.generate_content = AsyncMock(
            side_effect=Exception("API Error")
        )
        mock_aio.models = mock_models
        mock_client.aio = mock_aio
        provider.client = mock_client

        with pytest.raises(AiServiceUnavailableException):
            await provider.interpret_voice_command(
                audio_data=b"fake-audio",
                audio_mime_type="audio/wav",
                diagram_snapshot={"classes": [], "relations": []},
                available_data_types=["TEXT"],
                available_relation_types=["ASSOCIATION"],
                available_cardinalities=["1"],
            )

    asyncio.run(_run())


def test_timeout_fallback_to_next_model() -> None:
    import asyncio

    async def _run():
        provider = GeminiAiProvider(api_key="test-key")
        provider.models_chain = ["slow-model", "fast-model"]

        mock_client = MagicMock()
        mock_aio = MagicMock()
        mock_models = MagicMock()

        success_response = MagicMock()
        success_response.text = json.dumps({
            "transcription": None,
            "resume": "Clase Producto creada.",
            "actions": [{"type": "CREATE_CLASS", "payload": {"name": "Producto"}}],
        })

        mock_models.generate_content = AsyncMock(
            side_effect=[TimeoutError("Model timed out"), success_response]
        )
        mock_aio.models = mock_models
        mock_client.aio = mock_aio
        provider.client = mock_client

        result = await provider.interpret_image_command(
            image_data=b"fake-image",
            image_mime_type="image/png",
            diagram_snapshot={"classes": [], "relations": []},
            available_data_types=["TEXT"],
            available_relation_types=["ASSOCIATION"],
            available_cardinalities=["1"],
        )

        assert result.resume == "Clase Producto creada."
        assert len(result.actions) == 1
        assert mock_models.generate_content.call_count == 2

    asyncio.run(_run())


def test_gemini_model_chain_configuration_and_ordering() -> None:
    """Verifica que la cadena de modelos contenga los modelos activos ordenados por rapidez, balance y razonamiento."""
    from app.core.config import Settings

    custom_settings = Settings(
        GEMINI_MODEL_CHAIN="Gemini 3.1 Flash Light, gemini-3.5-flash-light, gemini-2.5-flash, gemini-3-flash, gemini-3.5-flash, gemini-3.6-flash, gemini-3.7-flash, gemini-3.8-flash"
    )

    expected_order = [
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-3-flash-preview",
        "gemini-3.5-flash",
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.8-flash",
    ]

    assert custom_settings.GEMINI_MODEL_CHAIN == expected_order
    assert len(custom_settings.GEMINI_MODEL_CHAIN) == 8

    # Verificar que el proveedor inicialice con la lista ordenada
    provider = GeminiAiProvider(api_key="test-key")
    assert provider.models_chain == expected_order
