import asyncio
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
                    response = await asyncio.wait_for(
                        self.client.aio.models.generate_content(
                            model=model_name,
                            contents=[audio_part, text_prompt_part],
                            config=config,
                        ),
                        timeout=settings.GEMINI_REQUEST_TIMEOUT_SECONDS,
                    )
                    if response and response.text:
                        return self._parse_response(response.text)
                except TimeoutError:
                    logger.warning(
                        "Timeout de %.1fs alcanzado con modelo %s. Pasando al siguiente modelo...",
                        settings.GEMINI_REQUEST_TIMEOUT_SECONDS,
                        model_name,
                    )
                    last_error = TimeoutError(f"Timeout al invocar modelo {model_name}")
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

    async def interpret_image_command(
        self,
        image_data: bytes,
        image_mime_type: str,
        diagram_snapshot: dict[str, Any],
        available_data_types: list[str],
        available_relation_types: list[str],
        available_cardinalities: list[str],
        prompt: str | None = None,
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

        image_part = types.Part.from_bytes(
            data=image_data,
            mime_type=image_mime_type,
        )
        instruction_text = (
            prompt.strip()
            if prompt and prompt.strip()
            else (
                "Analiza la imagen adjunta que contiene un diagrama de clases UML o modelo entidad-relación. "
                "Extrae todas las clases con sus nombres, atributos con sus tipos de datos estándar (omitiendo IDs y claves foráneas), "
                "y todas las relaciones entre clases con sus cardinalidades y tipos de relación. "
                "Genera el plan de acciones en formato JSON para recrear el diagrama de forma fiel y completa."
            )
        )
        text_prompt_part = types.Part.from_text(text=instruction_text)

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
                        "Intentando interpretar imagen con modelo %s (ciclo %d)",
                        model_name,
                        cycle + 1,
                    )
                    response = await asyncio.wait_for(
                        self.client.aio.models.generate_content(
                            model=model_name,
                            contents=[image_part, text_prompt_part],
                            config=config,
                        ),
                        timeout=settings.GEMINI_REQUEST_TIMEOUT_SECONDS,
                    )
                    if response and response.text:
                        return self._parse_response(response.text)
                except TimeoutError:
                    logger.warning(
                        "Timeout de %.1fs alcanzado con modelo %s al procesar imagen. Pasando al siguiente modelo...",
                        settings.GEMINI_REQUEST_TIMEOUT_SECONDS,
                        model_name,
                    )
                    last_error = TimeoutError(f"Timeout al invocar modelo {model_name}")
                except Exception as exc:
                    logger.warning(
                        "Fallo con el modelo %s al procesar imagen: %s. Pasando al siguiente...",
                        model_name,
                        exc,
                    )
                    last_error = exc

        logger.error(
            "Todos los modelos de Gemini fallaron al procesar imagen tras %d ciclos. Último error: %s",
            self.max_cycles,
            last_error,
        )
        raise AiServiceUnavailableException(
            f"No fue posible procesar la imagen con ningún modelo disponible: {last_error}"
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
            pos_x = cls_item.get("position_x", 0.0)
            pos_y = cls_item.get("position_y", 0.0)
            classes_info.append(
                f"- Clase '{cls_item['name']}' (id: {cls_item['id']}, posición X: {pos_x}, Y: {pos_y}) con atributos: [{', '.join(attrs)}]"
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
Tu objetivo es analizar la orden del usuario (a través de audio o imagen de diagrama) y convertir sus peticiones en acciones concretas sobre el diagrama.

{diagram_text}

Restricciones y reglas de modelado:
1. TIPOS DE DATOS DISPONIBLES para atributos: {available_data_types}. Si el usuario o la imagen no especifica tipo, usa 'TEXT' o null.
2. TIPOS DE RELACIÓN DISPONIBLES: {available_relation_types}.
3. CARDINALIDADES DISPONIBLES para asociaciones: {available_cardinalities}.
4. Movimiento de clases: SÍ puedes mover clases con MOVE_CLASS cuando el usuario diga "mové", "mueve", "lleva", "acercá", "coloca debajo/arriba/al lado/ a la derecha/izquierda de", "cerca de", "hacia el centro/zona".
5. HANDLES DISPONIBLES: {[h.value for h in DiagramRelationHandle]}. Elige el par que mejor conecte los centros y evita sobrecargar un handle cuando exista una alternativa.
6. ORDEN CANÓNICO DE ACCIONES: Debes estructurar y emitir las acciones en este orden lógico:
   a) Primero todas las creaciones o modificaciones de clases (CREATE_CLASS, RENAME_CLASS, DELETE_CLASS).
   b) Luego los atributos propios de negocio de las clases base (CREATE_ATTRIBUTE).
   c) Luego las relaciones entre clases (CREATE_RELATION) y movimientos (MOVE_CLASS).
   d) Por último, si una relación muchos a muchos generó una clase puente y dicha tabla en el diagrama contenía atributos adicionales de negocio (ej. 'cantidad'), emite CREATE_ATTRIBUTE sobre el nombre de la clase puente generada.
7. Ejemplos coloquiales rioplatenses → intención:
   - "haceme una clase Pedido con total" → CREATE_CLASS name=Pedido
   - "mové Cliente a la derecha de Factura" → MOVE_CLASS class_name=Cliente, reference_class_name=Factura, direction=RIGHT
   - "acercá Producto hacia el centro" → MOVE_CLASS class_name=Producto, zone=center
   - "agregale a Usuario el atributo edad" → CREATE_ATTRIBUTE class_name=Usuario name=edad
   - "uní Usuario con Pedido" → CREATE_RELATION source=Usuario target=Pedido
   - "no, mejor Cliente" (autocorrección) → ignora la primera mención, usa Cliente
   - "crea clase Pedido y colócala debajo de Cliente" → CREATE_CLASS + MOVE_CLASS
8. Las acciones disponibles son:
   - CREATE_CLASS: payload: {{"name": str, "position_x": float, "position_y": float}}. Elige una posición libre y coherente; cero es válido.
   - DELETE_CLASS: payload: {{"class_name": str}}
   - RENAME_CLASS: payload: {{"class_name": str, "new_name": str}}
   - MOVE_CLASS: payload: {{"class_name": str, "reference_class_name": str | null, "direction": str | null, "zone": str | null, "position_x": float | null, "position_y": float | null}}. Usa direction=RIGHT/LEFT/TOP/BOTTOM, zone=center/top-left/top-right/bottom-left/bottom-right, o position_x/y absolutas como fallback. Si el usuario dice "cerca de X" usa reference_class_name=X.
   - CREATE_ATTRIBUTE: payload: {{"class_name": str, "name": str, "data_type": str | null}}
   - UPDATE_ATTRIBUTE: payload: {{"class_name": str, "attribute_name": str, "new_name": str | null, "new_data_type": str | null, "is_nullable": bool | null}}
   - DELETE_ATTRIBUTE: payload: {{"class_name": str, "attribute_name": str}}
   - CREATE_RELATION: payload: {{"source_class_name": str, "target_class_name": str, "relation_type": str, "name": str, "source_cardinality": str | null, "target_cardinality": str | null, "source_handle": str, "target_handle": str}}
   - DELETE_RELATION: payload: {{"source_class_name": str, "target_class_name": str}}
   - RENAME_RELATION: payload: {{"source_class_name": str, "target_class_name": str, "new_name": str}}
9. CLASES PUENTE (M:N): Cuando se cree una relación muchos-a-muchos (M:N), el sistema automáticamente genera una clase puente intermedia con nombre combinado "{{SourceClass}}{{TargetClass}}" (por ejemplo, entre "Producto" y "Categoria" se genera "ProductoCategoria"). Esta clase puente incluye automáticamente: id (PK, UUID), {{source}}_id (FK, UUID), {{target}}_id (FK, UUID). NUNCA crees una acción CREATE_CLASS para la tabla puente intermedia: únicamente emite CREATE_RELATION entre las dos clases base (con cardinalidades '*' y '*'), y si la tabla intermedia tiene atributos adicionales propios de la asociación (como 'cantidad'), emite CREATE_ATTRIBUTE para dicha clase puente con ese atributo.
10. RELACIONES RECURSIVAS (AUTO-REFERENCIADAS): Una clase puede relacionarse consigo misma ÚNICAMENTE mediante relaciones de tipo 'ASSOCIATION' (por ejemplo, para representar jerarquías como categoría padre-hijo, empleado-supervisor o producto componente-subcomponente). NUNCA uses 'GENERALIZATION', 'COMPOSITION' ni 'AGGREGATION' cuando source_class_name == target_class_name. Para auto-relaciones, asigna handles distintos en la misma clase (ej. source_handle='RIGHT_TOP', target_handle='RIGHT_BOTTOM').
11. NUNCA EMITAS ATRIBUTOS DE ID O CLAVES FORÁNEAS: NUNCA emitas acciones CREATE_ATTRIBUTE para atributos de clave primaria llamados 'id' ni para claves foráneas (atributos terminados en '_id' o que comiencen con 'id_', como 'producto_id', 'id_producto', 'venta_id', etc.). En este sistema, TODA clase creada nace automáticamente con su clave primaria 'id' (UUID), y TODA clave foránea se genera automáticamente cuando se crea la relación (CREATE_RELATION). Si ves o escuchas atributos con ID o foráneas, IGNÓRALOS por completo. Solo debes crear atributos de datos propios de negocio (ej. 'nombre', 'precio', 'fecha', 'cantidad').

DEBES responder OBLIGATORIAMENTE con un objeto JSON válido con este esquema:
{{
  "transcription": "Texto transcrito de lo que dijo el usuario en el audio o null si la entrada fue una imagen",
  "resume": "Resumen claro y conciso en español de lo que se ejecutará o por qué no se pudo ejecutar",
  "actions": [
    {{
      "type": "NOMBRE_DE_LA_ACCION",
      "payload": {{ ... }}
    }}
  ]
}}

Si la orden o imagen no tiene relación con diagramas o es ilegible/ininteligible, retorna "actions": [] y explica en "resume" la razón de forma amable."""

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
            logger.warning("JSON de Gemini no válido (422 esperado): %s. Texto: %s", exc, text[:500])
            raise AgentInterpretationFailedException(
                "La respuesta del asistente no tuvo un formato JSON válido."
            )

        transcription_raw = data.get("transcription")
        transcription = str(transcription_raw).strip() if transcription_raw is not None and str(transcription_raw).strip() != "" and str(transcription_raw).strip().lower() != "null" else None
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
