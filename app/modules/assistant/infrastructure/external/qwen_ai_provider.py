from collections.abc import Mapping
import json
import logging
from math import ceil
from time import perf_counter
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.core.config import Settings, settings as default_settings
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiContentPart,
    AiRequest,
    AiResult,
    AiToolCall,
    AiToolDefinition,
    ModelRole,
)
from app.modules.assistant.application.services.agent_trace import current_agent_message_id
from app.modules.assistant.domain.exceptions import (
    AiProviderError,
    AiProviderErrorReason,
    AiProviderUnavailableException,
    AiProviderUnavailableReason,
)

logger = logging.getLogger(__name__)


class QwenAiProvider:
    """Adaptador HTTP de Chat Completions compatible con Qwen Model Studio."""

    _MODEL_BY_ROLE = {
        ModelRole.MAIN: "QWEN_MODEL_MAIN",
        ModelRole.VISION: "QWEN_MODEL_VISION",
        ModelRole.PLANNING: "QWEN_MODEL_PLANNING",
        ModelRole.EXECUTION: "QWEN_MODEL_EXECUTION",
        ModelRole.COMPACTION: "QWEN_MODEL_COMPACTION",
    }

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self._transport = transport

    async def complete(self, request: AiRequest) -> AiResult:
        inference_id = uuid4().hex[:12]
        message_id = current_agent_message_id() or "unbound"
        api_key = self.settings.QWEN_API_KEY.get_secret_value().strip()
        if not api_key:
            raise AiProviderUnavailableException(
                reason=AiProviderUnavailableReason.MISSING_API_KEY
            )
        if request.max_output_tokens <= 0:
            raise AiProviderError(reason=AiProviderErrorReason.INVALID_REQUEST)

        model = getattr(self.settings, self._MODEL_BY_ROLE[request.model_role])
        payload = {
            "model": model,
            "messages": [self._serialize_message(message) for message in request.messages],
            "max_tokens": request.max_output_tokens,
            "stream": False,
        }
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
            if request.enable_reasoning is None:
                payload["enable_thinking"] = False
        if (
            request.purpose in ("continuation_resolution", "dialog_turn_interpretation", "action_planning", "memory_update")
            and request.enable_reasoning is None
        ):
            payload["enable_thinking"] = False
        if request.enable_reasoning is not None:
            payload["enable_thinking"] = request.enable_reasoning
        if request.tools:
            payload["tools"] = [self._serialize_tool(tool) for tool in request.tools]
            payload["parallel_tool_calls"] = False
            payload["enable_thinking"] = False
        estimated_input_tokens = self._estimate_input_tokens(payload)
        estimated_total_tokens = estimated_input_tokens + request.max_output_tokens
        if estimated_total_tokens > self.settings.AGENT_CONTEXT_MAX_TOKENS:
            logger.warning(
                "Qwen request rejected before sending (message_id=%s, inference_id=%s, "
                "reason=context_budget_exceeded, estimated_input_tokens=%s, "
                "reserved_output_tokens=%s, context_budget=%s)",
                message_id,
                inference_id,
                estimated_input_tokens,
                request.max_output_tokens,
                self.settings.AGENT_CONTEXT_MAX_TOKENS,
            )
            raise AiProviderError(
                reason=AiProviderErrorReason.CONTEXT_BUDGET_EXCEEDED
            )
        url = f"{self.settings.QWEN_BASE_URL.rstrip('/')}/chat/completions"
        content_logging = (
            self.settings.ENVIRONMENT.upper() == "DEV"
            and self.settings.QWEN_DEBUG_LOG_CONTENT
        )
        tool_names = [tool.name for tool in request.tools] if request.tools else []
        logger.info(
            "Qwen request started (purpose=%s, model=%s, role=%s, messages=%d, tools=%s, max_tokens=%s, est_tokens=%s)",
            request.purpose,
            model,
            request.model_role.value,
            len(request.messages),
            tool_names,
            request.max_output_tokens,
            estimated_input_tokens,
        )
        if content_logging:
            previews = []
            for m in request.messages:
                if m.role == "system":
                    first_line = m.content.strip().split("\n")[0]
                    prev = first_line if len(first_line) <= 120 else first_line[:110] + "..."
                    previews.append(f"[system: {prev}]")
                elif isinstance(m.content, list):
                    parts = []
                    for p in m.content:
                        if getattr(p, "type", None) == "text":
                            parts.append(str(p.text)[:200])
                        elif getattr(p, "type", None) == "image_url":
                            parts.append(f"[imagen: {str(p.image_url)[:60]}...]")
                    previews.append(f"[{m.role}: {' '.join(parts)}]")
                else:
                    content_str = str(m.content).strip()
                    prev = content_str if len(content_str) <= 400 else content_str[:380] + "..."
                    previews.append(f"[{m.role}: {prev}]")
            logger.info(
                "Qwen request prompt preview (purpose=%s): %s",
                request.purpose,
                " | ".join(previews),
            )
            logger.debug(
                "Qwen request payload raw (message_id=%s, inference_id=%s): %s",
                message_id,
                inference_id,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            )

        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.QWEN_TIMEOUT_SECONDS),
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            logger.warning(
                "Qwen request failed (message_id=%s, inference_id=%s, "
                "reason=timeout, duration_ms=%.1f)",
                message_id,
                inference_id,
                (perf_counter() - started_at) * 1000,
            )
            raise AiProviderUnavailableException(
                reason=AiProviderUnavailableReason.TIMEOUT
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "Qwen request failed (message_id=%s, inference_id=%s, reason=network_error, "
                "exception_type=%s, duration_ms=%.1f)",
                message_id,
                inference_id,
                type(exc).__name__,
                (perf_counter() - started_at) * 1000,
            )
            raise AiProviderUnavailableException(
                reason=AiProviderUnavailableReason.NETWORK_ERROR
            ) from exc

        duration_ms = (perf_counter() - started_at) * 1000
        if content_logging:
            logger.debug(
                "Qwen response body raw (message_id=%s, inference_id=%s): %s",
                message_id,
                inference_id,
                response.text,
            )

        if response.status_code < 200 or response.status_code >= 300:
            raise AiProviderUnavailableException(
                reason=AiProviderUnavailableReason.HTTP_ERROR,
                status_code=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise AiProviderError(reason=AiProviderErrorReason.INVALID_JSON) from exc
        try:
            result = self._parse_result(body, model, request.model_role, duration_ms=duration_ms)
        except AiProviderError as exc:
            logger.warning(
                "Qwen response rejected (message_id=%s, inference_id=%s, provider_reason=%s)",
                message_id,
                inference_id,
                exc.reason.value,
            )
            raise
        logger.info(
            "Qwen response accepted (purpose=%s, status=%s, duration_ms=%.1f, in_tokens=%s, out_tokens=%s, cached=%s, tool_calls=%d)",
            request.purpose,
            response.status_code,
            duration_ms,
            result.input_tokens,
            result.output_tokens,
            result.cached_tokens,
            len(result.tool_calls),
        )
        if content_logging:
            tool_call_names = [tc.name for tc in result.tool_calls] if result.tool_calls else []
            resp_preview = result.text.strip() if result.text else ""
            if len(resp_preview) > 250:
                resp_preview = resp_preview[:240] + "..."
            logger.info(
                "Qwen response content (purpose=%s): text=%r, tool_calls=%s",
                request.purpose,
                resp_preview,
                tool_call_names,
            )
        return result

    @staticmethod
    def _estimate_input_tokens(payload: Mapping[str, object]) -> int:
        """Estima el texto serializado; el proveedor conserva la autoridad final."""

        input_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"max_tokens", "stream"}
        }
        serialized = json.dumps(
            input_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        return max(1, ceil(len(serialized) / 3))

    @classmethod
    def _serialize_message(cls, message) -> dict[str, object]:
        content = message.content
        if isinstance(content, str):
            serialized_content: object = content
        else:
            serialized_content = [cls._serialize_content_part(part) for part in content]
        serialized: dict[str, object] = {
            "role": message.role,
            "content": serialized_content,
        }
        if message.tool_calls:
            serialized["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        if message.tool_call_id is not None:
            serialized["tool_call_id"] = message.tool_call_id
        return serialized

    @staticmethod
    def _serialize_tool(tool: AiToolDefinition) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }

    @staticmethod
    def _serialize_content_part(part: AiContentPart) -> dict[str, object]:
        if part.type == "text" and isinstance(part.text, str) and part.text:
            return {"type": "text", "text": part.text}
        if part.type == "image_url" and isinstance(part.image_url, str):
            parsed = urlparse(part.image_url)
            if (
                parsed.scheme != "https"
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise AiProviderError(reason=AiProviderErrorReason.INVALID_IMAGE_URL)
            return {"type": "image_url", "image_url": {"url": part.image_url}}
        raise AiProviderError(reason=AiProviderErrorReason.INVALID_REQUEST)

    @staticmethod
    def _parse_result(
        body: object,
        model: str,
        model_role: ModelRole,
        duration_ms: float | None = None,
    ) -> AiResult:
        if not isinstance(body, Mapping):
            raise AiProviderError(reason=AiProviderErrorReason.RESPONSE_NOT_OBJECT)
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AiProviderError(reason=AiProviderErrorReason.MISSING_CHOICES)
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise AiProviderError(reason=AiProviderErrorReason.INVALID_CHOICE)
        if choice.get("finish_reason") in {"length", "max_tokens"}:
            raise AiProviderError(reason=AiProviderErrorReason.OUTPUT_TRUNCATED)
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise AiProviderError(reason=AiProviderErrorReason.MISSING_MESSAGE)
        content = message.get("content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise AiProviderError(reason=AiProviderErrorReason.INVALID_CONTENT)
        raw_tool_calls = message.get("tool_calls") or []
        if not isinstance(raw_tool_calls, list) or len(raw_tool_calls) > 8:
            raise AiProviderError(reason=AiProviderErrorReason.INVALID_TOOL_CALLS)
        tool_calls: list[AiToolCall] = []
        for raw_call in raw_tool_calls:
            if not isinstance(raw_call, Mapping):
                raise AiProviderError(reason=AiProviderErrorReason.INVALID_TOOL_CALL)
            call_id = raw_call.get("id")
            function = raw_call.get("function")
            if not isinstance(call_id, str) or not call_id or not isinstance(function, Mapping):
                raise AiProviderError(reason=AiProviderErrorReason.INVALID_TOOL_CALL)
            name = function.get("name")
            raw_arguments = function.get("arguments")
            if not isinstance(name, str) or not name or not isinstance(raw_arguments, str):
                raise AiProviderError()
            try:
                arguments = json.loads(raw_arguments)
            except (ValueError, TypeError) as exc:
                raise AiProviderError(reason=AiProviderErrorReason.INVALID_TOOL_ARGUMENTS) from exc
            if not isinstance(arguments, dict):
                raise AiProviderError(reason=AiProviderErrorReason.INVALID_TOOL_ARGUMENTS)
            tool_calls.append(AiToolCall(id=call_id, name=name, arguments=arguments))
        if not content.strip() and not tool_calls:
            raise AiProviderError(reason=AiProviderErrorReason.EMPTY_RESPONSE)

        usage = body.get("usage")
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, Mapping) else None
        completion_tokens = usage.get("completion_tokens") if isinstance(usage, Mapping) else None
        cached_tokens = None
        if isinstance(usage, Mapping):
            prompt_details = usage.get("prompt_tokens_details")
            if isinstance(prompt_details, Mapping) and isinstance(prompt_details.get("cached_tokens"), int):
                cached_tokens = prompt_details["cached_tokens"]
            elif isinstance(usage.get("cached_tokens"), int):
                cached_tokens = usage["cached_tokens"]

        return AiResult(
            text=content.strip(),
            model_role=model_role,
            model=model,
            input_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
            output_tokens=completion_tokens if isinstance(completion_tokens, int) else None,
            cached_tokens=cached_tokens,
            duration_ms=round(duration_ms, 2) if duration_ms is not None else None,
            tool_calls=tuple(tool_calls),
        )
