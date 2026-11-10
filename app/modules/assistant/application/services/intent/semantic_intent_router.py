"""Enrutador Semántico de Intención y Desambiguación Contextual con LLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import logging
from typing import Any, Sequence

from app.modules.assistant.application.ports.providers.ai_provider import (
    AiMessage,
    AiProvider,
    AiRequest,
    ModelRole,
)

logger = logging.getLogger(__name__)


class SemanticCategory(StrEnum):
    """Categorías semánticas exhaustivas del turno conversacional."""

    DIRECT_ACTION = "DIRECT_ACTION"
    CONTINUATION_OR_ANAPHORA = "CONTINUATION_OR_ANAPHORA"
    COMPOUND_ACTION = "COMPOUND_ACTION"
    NEEDS_MORE_CONTEXT = "NEEDS_MORE_CONTEXT"
    CONCEPTUAL_CONSULTATION = "CONCEPTUAL_CONSULTATION"
    DECLINE_OR_CANCEL = "DECLINE_OR_CANCEL"


@dataclass(frozen=True, slots=True)
class SemanticTurnDecision:
    """Decisión semántica canónica estructurada generada para el turno."""

    category: SemanticCategory
    reasoning: str
    resolved_goal: str
    requires_mutation: bool
    missing_info: tuple[str, ...] = ()
    clarification_question: str | None = None
    raw_message: str = ""


_ROUTER_SYSTEM_PROMPT = """Eres el Enrutador Semántico de Intención y Desambiguación Contextual de un asistente especializado en modelado de diagramas UML.

Tu misión es analizar el mensaje del usuario considerando el contexto del proyecto y el historial reciente de conversación, y clasificarlo en una de 6 categorías con salida JSON estructurada estricta:

CATEGORÍAS:
1. "DIRECT_ACTION": El usuario da una instrucción de acción explícita y autosuficiente (crear, editar o eliminar clases, atributos o relaciones) que NO depende de resolver pronombres o anáforas de turnos previos.
   - requires_mutation: true (o false si es lectura/inspección de clases)
   - resolved_goal: La instrucción canónica clara para el planificador.

2. "CONTINUATION_OR_ANAPHORA": El usuario pide ejecutar, continuar o aplicar algo que hace referencia a temas, sugerencias o recomendaciones previas ("aplica esa generalización", "haz lo que dijiste", "conéctalas", "dale con eso", "implementa la relación sugerida", "implementa eso", "créalas", "sí, hazlo", "aplica lo propuesto").
   - Tu deber crucial es DESCONTEXTUALIZAR: reescribir la orden en una instrucción completa, explícita y auto-contenida con los nombres reales de clases, tipos de relación o atributos discutidos. Si la sugerencia previa del asistente proponía clases que aún no existen en el diagrama, resolved_goal DEBE ordenar la creación de esas clases y la creación de su relación correspondiente.
   - requires_mutation: true
   - resolved_goal: La instrucción completa canónica (ej: "Crear la clase Curso, crear la clase Estudiante y relacionarlas mediante asociación de muchos a muchos").

3. "COMPOUND_ACTION": El usuario combina una continuación/aceptación con una nueva orden en el mismo turno ("aplica esa relación y además crea la clase Proveedor con nombre y teléfono").
   - Tu deber es desglosar y formular el objetivo consolidado de múltiples pasos para el planificador.
   - requires_mutation: true
   - resolved_goal: La lista de objetivos consolidada en orden lógico.

4. "NEEDS_MORE_CONTEXT": La solicitud del usuario es genuinamente ambigua o le faltan parámetros esenciales que no se pueden inferir del historial ni del diagrama (ej: "relaciona las clases" habiendo 3 o más clases en el lienzo y sin indicar cuáles ni qué tipo; o "crea un atributo" sin nombre ni clase).
   - requires_mutation: false
   - clarification_question: Una pregunta cordial, específica y contextual en español orientando al usuario exactamente sobre lo que falta para proceder (SIN tablas).
   - missing_info: Lista breve de datos faltantes (ej: ["clases_involucradas", "tipo_relacion"]).

5. "CONCEPTUAL_CONSULTATION": El usuario hace preguntas teóricas, arquitectónicas o de asesoría de diseño UML ("¿qué relación conviene entre Pedido y Producto?", "¿qué es agregación?", "¿cómo modelar un carrito de compras?").
   - NO solicita modificar el diagrama en este turno.
   - requires_mutation: false
   - resolved_goal: La consulta a responder directamente en texto Markdown (SIN tablas).

6. "DECLINE_OR_CANCEL": El usuario indica explícitamente cancelar, declinar o descartar la sugerencia o solicitud pendiente ("cancela eso", "olvídalo", "no hagas nada", "déjalo así").
   - requires_mutation: false
   - resolved_goal: "Cancelar la solicitud pendiente."

REGLAS DE ORO:
- REGLA DE FORMATO ESTRICTA: NUNCA utilices tablas Markdown (filas y columnas con '|'). Toda respuesta, pregunta de clarificación y razonamiento debe ser exclusivamente texto plano, encabezados (###) y listas con viñetas (- ).
- REGLA DE RETOMA DE PENDIENTES: Solo debes clasificar como "CONTINUATION_OR_ANAPHORA" para reanudar una tarea pendiente (has_active_pending_continuation: true) si el usuario lo confirma explícitamente ("sí", "continúa", "reintenta", "dale", "procede", "hazlo") o si menciona explícitamente el elemento de esa tarea. Si el usuario da una orden diferente (ej. "relaciona las clases"), NO la asocies a tareas residuales previas.
- REGLA DE METAMODELO Y EXISTENCIA UML:
  * Las llaves foráneas (FK) NO son atributos manuales; se generan automáticamente al crear relaciones entre clases. Si el usuario pide crear una llave foránea aislada ("crea una fk...", "llave foránea..."), clasifica como "NEEDS_MORE_CONTEXT" con clarification_question orientando a crear la relación entre las clases involucradas.
  * Las llaves primarias (PK) ya se crean automáticamente (`id: UUID`) con cada clase; no deben crearse manualmente como atributos.
  * Órdenes ambiguas como "relaciona las clases" o "conéctalas" sin que haya exactamente 2 clases obvias en el proyecto son estrictamente "NEEDS_MORE_CONTEXT".
  * Clases inexistentes en peticiones de relaciones: Si el usuario solicita relacionar o conectar entidades (ej: "relaciona Cliente con Factura") y una o ambas clases NO existen en `existing_classes_in_diagram` (y no fueron acordadas en el historial reciente), clasifica como "NEEDS_MORE_CONTEXT" con requires_mutation: false. En clarification_question formula una pregunta cordial informando que la clase no existe y preguntando si desea crearla primero y qué tipo de relación establecer (ej: "La clase Cliente no existe actualmente en el diagrama. ¿Deseas que la cree primero para relacionarla con Factura?").
- No pidas más contexto si el contexto ya se mencionó en el historial reciente o si hay una inferencia obvia (ej. si solo hay 2 clases en el diagrama y pide "relaciónalas", son esas dos).
- Responde EXCLUSIVAMENTE con el objeto JSON con las claves: "category", "reasoning", "resolved_goal", "requires_mutation", "missing_info", "clarification_question"."""



class SemanticIntentRouter:
    """Analizador y enrutador semántico autónomo impulsado por LLM."""

    def __init__(self, ai_provider: AiProvider | None = None) -> None:
        self.ai_provider = ai_provider

    async def route_turn(
        self,
        *,
        prompt: str,
        recent_turns: Sequence[dict[str, Any]] = (),
        existing_classes: Sequence[str] | dict[str, Any] = (),
        active_continuation: Any | None = None,
    ) -> SemanticTurnDecision:
        return await self.route(
            user_message=prompt,
            recent_turns=recent_turns,
            existing_classes=existing_classes,
            active_continuation=active_continuation,
        )

    async def route(
        self,
        *,
        user_message: str,
        recent_turns: Sequence[dict[str, Any]] = (),
        existing_classes: Sequence[str] | dict[str, Any] = (),
        active_continuation: Any | None = None,
    ) -> SemanticTurnDecision:
        clean_msg = user_message.strip()
        if not clean_msg:
            return SemanticTurnDecision(
                category=SemanticCategory.NEEDS_MORE_CONTEXT,
                reasoning="El mensaje del usuario está vacío.",
                resolved_goal="",
                requires_mutation=False,
                clarification_question="¿En qué puedo ayudarte con tu diagrama UML?",
                raw_message=user_message,
            )

        classes_list = (
            list(existing_classes.keys())
            if isinstance(existing_classes, dict)
            else list(existing_classes)
        )

        # Si no hay proveedor AI o falla la conexión, fallback heurístico seguro
        if self.ai_provider is None:
            return self._fallback_route(clean_msg, recent_turns, classes_list)

        payload = {
            "current_user_message": clean_msg,
            "recent_conversation_turns": list(recent_turns)[-3:] if recent_turns else [],
            "existing_classes_in_diagram": classes_list,
            "has_active_pending_continuation": active_continuation is not None,
            "active_continuation_goal": (
                getattr(active_continuation, "effective_request", None)
                if active_continuation else None
            ),
        }

        req = AiRequest(
            model_role=ModelRole.MAIN,
            messages=(
                AiMessage(role="system", content=_ROUTER_SYSTEM_PROMPT),
                AiMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ),
            response_format="json_object",
            purpose="semantic_intent_routing",
            enable_reasoning=False,
            max_output_tokens=600,
        )

        try:
            res = await self.ai_provider.complete(req)
            data = json.loads(res.text.strip())
            return self._parse_decision(data, clean_msg)
        except Exception as exc:
            logger.warning(
                "Fallo en SemanticIntentRouter (%s: %s). Aplicando fallback seguro.",
                type(exc).__name__,
                exc,
            )
            return self._fallback_route(clean_msg, recent_turns, existing_classes)

    def _parse_decision(self, data: dict[str, Any], raw_message: str) -> SemanticTurnDecision:
        raw_cat = str(data.get("category", "")).upper()
        category = (
            SemanticCategory(raw_cat)
            if raw_cat in SemanticCategory.__members__
            else SemanticCategory.DIRECT_ACTION
        )
        reasoning = str(data.get("reasoning", "")).strip()
        resolved_goal = str(data.get("resolved_goal", "")).strip() or raw_message
        requires_mutation = bool(data.get("requires_mutation", category in (
            SemanticCategory.DIRECT_ACTION,
            SemanticCategory.CONTINUATION_OR_ANAPHORA,
            SemanticCategory.COMPOUND_ACTION,
        )))
        missing_info = tuple(str(x) for x in data.get("missing_info") or [])
        clarification_question = data.get("clarification_question")
        if isinstance(clarification_question, str):
            clarification_question = clarification_question.strip() or None

        return SemanticTurnDecision(
            category=category,
            reasoning=reasoning,
            resolved_goal=resolved_goal,
            requires_mutation=requires_mutation,
            missing_info=missing_info,
            clarification_question=clarification_question,
            raw_message=raw_message,
        )

    def _fallback_route(
        self,
        message: str,
        recent_turns: Sequence[dict[str, Any]],
        existing_classes: Sequence[str],
    ) -> SemanticTurnDecision:
        """Fallback defensivo sin AI: clasifica lo evidente sin bloquear."""
        lower = message.casefold()
        if any(w in lower for w in ("cancela", "cancelar", "olvídalo", "olvidalo", "no hagas nada", "déjalo así", "dejalo asi", "descartar")):
            return SemanticTurnDecision(
                category=SemanticCategory.DECLINE_OR_CANCEL,
                reasoning="Cancelación detectada por fallback.",
                resolved_goal="Cancelar la solicitud pendiente.",
                requires_mutation=False,
                raw_message=message,
            )

        is_question = "?" in message or "¿" in message
        if is_question and not any(w in lower for w in ("crea", "agrega", "elimina", "modifica", "aplica", "conecta")):
            return SemanticTurnDecision(
                category=SemanticCategory.CONCEPTUAL_CONSULTATION,
                reasoning="Pregunta conceptual detectada por fallback.",
                resolved_goal=message,
                requires_mutation=False,
                raw_message=message,
            )

        # Si hay turnos recientes y menciona anáforas
        has_anaphora = any(w in lower for w in ("esa", "ese", "esas", "esos", "eso", "conéctalas", "conectalas", "hazlo", "aplica", "sugerid"))
        if recent_turns and has_anaphora:
            return SemanticTurnDecision(
                category=SemanticCategory.CONTINUATION_OR_ANAPHORA,
                reasoning="Referencia anafórica a turno reciente detectada por fallback.",
                resolved_goal=message,
                requires_mutation=True,
                raw_message=message,
            )

        return SemanticTurnDecision(
            category=SemanticCategory.DIRECT_ACTION,
            reasoning="Acción directa procesada por fallback.",
            resolved_goal=message,
            requires_mutation=True,
            raw_message=message,
        )
