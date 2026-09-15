import json
import logging
from typing import Any

from google import genai
from google.genai import types

from app.core.config import settings
from app.modules.assistant.application.ports.providers.ai_provider import (
    AiAction,
    AiInterpretationResult,
    AiProvider,
)
from app.modules.assistant.domain.enums.agent_action_type import AgentActionType
from app.modules.assistant.domain.exceptions import (
    AgentInterpretationFailedException,
    AiServiceUnavailableException,
)
from app.modules.diagram.domain.enums.diagram_relation_handle import DiagramRelationHandle

logger = logging.getLogger(__name__)


class GeminiAiProvider(AiProvider):
    """Implementación del proveedor de IA usando Google Gemini con fallback de modelos."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or settings.GEMINI_API_KEY
        self.client = genai.Client(api_key=key) if key else None
        self.models_chain = settings.GEMINI_MODEL_CHAIN
        self.max_cycles = settings.GEMINI_MAX_RETRY_CYCLES

    async def interpret_voice_command(
        self,
        audio_data: bytes,
        audio_mime_type: str,
        diagram_snapshot: dict[str, Any],
        available_data_types: list[str],
        available_relation_types: list[str],
        available_cardinalities: list[str],
    ) -> AiInterpretationResult:
        if not self.client:
            logger.error("GEMINI_API_KEY no está configurada.")
            raise AiServiceUnavailableException("Clave API de Gemini no configurada.")

        system_prompt = self._build_system_prompt(
            diagram_snapshot=diagram_snapshot,
            available_data_types=available_data_types,
            available_relation_types=available_relation_types,
            available_cardinalities=available_cardinalities,
        )

        audio_part = types.Part.from_bytes(
            data=audio_data,
            mime_type=audio_mime_type,
        )
        text_prompt_part = types.Part.from_text(
            text="Escucha el audio adjunto, transcribe la orden del usuario y genera el plan de acciones para el diagrama en formato JSON."
        )

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            temperature=0.1,
        )

        last_error: Exception | None = None

        for cycle in range(self.max_cycles):
            for model_name in self.models_chain:
                try:
                    logger.info(
                        "Intentando interpretar comando con modelo %s (ciclo %d)",
                        model_name,
                        cycle + 1,
                    )
                    response = await self.client.aio.models.generate_content(
                        model=model_name,
                        contents=[audio_part, text_prompt_part],
                        config=config,
                    )
                    if response and response.text:
                        return self._parse_response(response.text)
                except Exception as exc:
                    logger.warning(
                        "Fallo con el modelo %s: %s. Pasando al siguiente...",
                        model_name,
                        exc,
                    )
                    last_error = exc

        logger.error(
            "Todos los modelos de Gemini fallaron tras %d ciclos. Último error: %s",
            self.max_cycles,
            last_error,
        )
        raise AiServiceUnavailableException(
            f"No fue posible procesar la orden con ningún modelo disponible: {last_error}"
        )

    def _build_system_prompt(
        self,
        diagram_snapshot: dict[str, Any],
        available_data_types: list[str],
        available_relation_types: list[str],
        available_cardinalities: list[str],
    ) -> str:
        classes_info = []
        for cls_item in diagram_snapshot.get("classes", []):
            attrs = [
                f"{a['name']}:{a.get('data_type') or 'null'}{' (PK)' if a.get('is_primary_key') else ''}{' (FK)' if a.get('is_foreign_key') else ''}"
                for a in cls_item.get("attributes", [])
            ]
            classes_info.append(
                f"- Clase '{cls_item['name']}' (id: {cls_item['id']}) con atributos: [{', '.join(attrs)}]"
            )

        relations_info = []
        for rel in diagram_snapshot.get("relations", []):
            relations_info.append(
                f"- Relación '{rel['name']}' ({rel['relation_type']}) entre clase source {rel['source']['class_id']} ({rel['source'].get('handle')}) y target {rel['target']['class_id']} ({rel['target'].get('handle')})"
            )

        diagram_text = (
            "Estado actual del diagrama:\n"
            + (
                "\n".join(classes_info)
                if classes_info
                else "El diagrama no tiene clases aún."
            )
            + "\nRelaciones actuales:\n"
            + (
                "\n".join(relations_info)
                if relations_info
                else "No hay relaciones creadas aún."
            )
        )

        return f"""Eres un asistente inteligente de modelado de diagramas UML de clases y bases de datos relacionales.
Tu objetivo es escuchar el audio del usuario, transcribir lo que dijo y convertir sus peticiones en acciones concretas sobre el diagrama.

{diagram_text}

Restricciones y reglas de modelado:
1. TIPOS DE DATOS DISPONIBLES para atributos: {available_data_types}. Si el usuario no especifica tipo, usa 'TEXT' o null.
2. TIPOS DE RELACIÓN DISPONIBLES: {available_relation_types}.
3. CARDINALIDADES DISPONIBLES para asociaciones: {available_cardinalities}.
4. NO uses ni inventes acciones de mover clases o reposicionar atributos visualmente (el agente NO mueve clases).
5. HANDLES DISPONIBLES: {[h.value for h in DiagramRelationHandle]}. Elige el par que mejor conecte los centros y evita sobrecargar un handle cuando exista una alternativa.
6. Ordena las acciones para que una clase exista antes de crear sus atributos o relaciones.
7. Las acciones disponibles son:
   - CREATE_CLASS: payload: {{"name": str, "position_x": float, "position_y": float}}. Elige una posición libre y coherente; cero es válido.
   - DELETE_CLASS: payload: {{"class_name": str}}
   - RENAME_CLASS: payload: {{"class_name": str, "new_name": str}}
   - CREATE_ATTRIBUTE: payload: {{"class_name": str, "name": str, "data_type": str | null}}
   - UPDATE_ATTRIBUTE: payload: {{"class_name": str, "attribute_name": str, "new_name": str | null, "new_data_type": str | null, "is_nullable": bool | null}}
   - DELETE_ATTRIBUTE: payload: {{"class_name": str, "attribute_name": str}}
   - CREATE_RELATION: payload: {{"source_class_name": str, "target_class_name": str, "relation_type": str, "name": str, "source_cardinality": str | null, "target_cardinality": str | null, "source_handle": str, "target_handle": str}}
   - DELETE_RELATION: payload: {{"source_class_name": str, "target_class_name": str}}
   - RENAME_RELATION: payload: {{"source_class_name": str, "target_class_name": str, "new_name": str}}

DEBES responder OBLIGATORIAMENTE con un objeto JSON válido con este esquema:
{{
  "transcription": "Texto transcrito de lo que dijo el usuario en el audio",
  "resume": "Resumen claro y conciso en español de lo que se ejecutará o por qué no se pudo ejecutar",
  "actions": [
    {{
      "type": "NOMBRE_DE_LA_ACCION",
      "payload": {{ ... }}
    }}
  ]
}}

Si la orden no tiene relación con diagramas o es ininteligible, retorna "actions": [] y explica en "resume" la razón de forma amable."""

    def _parse_response(self, text: str) -> AiInterpretationResult:
        cleaned_text = text.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]
        elif cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[3:]
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]
        cleaned_text = cleaned_text.strip()

        try:
            data = json.loads(cleaned_text)
        except Exception as exc:
            logger.error("Error parseando JSON de Gemini: %s. Texto: %s", exc, text)
            raise AgentInterpretationFailedException(
                "La respuesta del asistente no tuvo un formato JSON válido."
            )

        transcription = str(data.get("transcription", "")).strip()
        resume = str(data.get("resume", "")).strip()
        raw_actions = data.get("actions", [])

        actions: list[AiAction] = []
        for raw in raw_actions:
            action_type_str = str(raw.get("type", "")).upper()
            try:
                action_type = AgentActionType(action_type_str)
            except ValueError:
                logger.warning("Acción desconocida devuelta por IA: %s", action_type_str)
                continue
            payload = raw.get("payload", {})
            actions.append(AiAction(type=action_type, payload=payload))

        return AiInterpretationResult(
            transcription=transcription,
            resume=resume,
            actions=actions,
        )
