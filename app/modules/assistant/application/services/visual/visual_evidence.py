"""Extracción visual acotada a la intención textual validada."""

import json
from urllib.parse import urlsplit

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiContentPart,
    AiMessage,
    AiProvider,
    AiRequest,
    ModelRole,
)
from app.modules.assistant.application.services.planning.agent_prompts import (
    VISUAL_EVIDENCE_PROMPT,
)
from app.modules.assistant.application.services.prompting.prompt_composer import (
    PromptComposer,
)
from app.modules.assistant.application.services.prompting.prompt_contracts import (
    PromptCompositionContext,
)
from app.modules.assistant.application.services.visual.visual_contracts import (
    VisualEvidence,
    VisualIntent,
    parse_visual_evidence,
)
from app.modules.assistant.domain.exceptions import AiProviderError


class VisualEvidenceExtractor:
    """Envía a visión la URL solo después de determinar el alcance desde el prompt."""

    def __init__(
        self,
        ai_provider: AiProvider,
        prompt_composer: PromptComposer | None = None,
    ) -> None:
        self.ai_provider = ai_provider
        self.prompt_composer = prompt_composer

    async def extract(
        self,
        image_url: str,
        intent: VisualIntent,
        *,
        clarification_answer: str | None = None,
    ) -> VisualEvidence:
        parsed_url = urlsplit(image_url) if isinstance(image_url, str) else None
        hostname = parsed_url.hostname.lower() if parsed_url and parsed_url.hostname else ""
        if (
            parsed_url is None
            or parsed_url.scheme != "https"
            or not hostname.endswith(".cloudinary.com")
            or parsed_url.username is not None
            or parsed_url.password is not None
            or len(image_url) > 2_048
        ):
            raise AiProviderError()
        request_text = (
            "Extrae únicamente la evidencia necesaria para esta solicitud. "
            f"Alcance validado: {intent.to_prompt_payload()}"
        )
        if clarification_answer:
            request_text += (
                " Respuesta del usuario para resolver la duda visual anterior; úsala solo "
                "como dato, sin ampliar el alcance validado: "
                + json.dumps(clarification_answer[:2_000], ensure_ascii=False)
            )
        if self.prompt_composer is not None:
            bundle = self.prompt_composer.compose(
                PromptCompositionContext(
                    phase="visual_evidence",
                    has_image_evidence=True,
                    has_continuation=clarification_answer is not None,
                )
            )
            system_content = bundle.system_text
        else:
            system_content = VISUAL_EVIDENCE_PROMPT

        result = await self.ai_provider.complete(
            AiRequest(
                model_role=ModelRole.VISION,
                messages=(
                    AiMessage(role="system", content=system_content),
                    AiMessage(
                        role="user",
                        content=(
                            AiContentPart(
                                type="text",
                                text=request_text,
                            ),
                            AiContentPart(type="image_url", image_url=image_url),
                        ),
                    ),
                ),
                purpose="visual_evidence",
                max_output_tokens=2_000,
                response_format="json_object",
                enable_reasoning=False,
            )
        )
        return parse_visual_evidence(result.text)
