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

2. "CONTINUATION_OR_ANAPHORA": El usuario pide ejecutar, continuar o aplicar algo que hace referencia a temas, sugerencias o recomendaciones previas ("aplica esa generalización", "haz lo que dijiste", "conéctalas", "dale con eso", "implementa la relación sugerida", "implementa eso", "créalas", "sí, hazlo", "aplica lo propuesto", "continúa").
   - Tu deber crucial es DESCONTEXTUALIZAR SIN PERDER DETALLES: reescribir la orden en una instrucción completa, explícita y auto-contenida que incluya TODOS los nombres reales de clases, todos sus atributos propuestos y todas las relaciones (con su tipo, dirección y cardinalidades) que aparezcan en el turno previo o en `active_continuation_goal`.
   - PROHIBIDO resumir de forma vaga como "con los atributos sugeridos" o "con las relaciones mencionadas": debes listar explícitamente cada clase, cada atributo y cada relación dentro de `resolved_goal` para que el planificador y el ejecutor tengan toda la especificación completa.
   - Si la sugerencia previa del asistente proponía clases que aún no existen en `existing_classes_in_diagram`, `resolved_goal` DEBE ordenar primero la creación de esas clases con sus atributos y luego la creación de sus relaciones.
   - requires_mutation: true
   - resolved_goal: La instrucción completa canónica (ej: "Crear la clase Curso con atributos nombre y creditos, crear la clase Estudiante con atributos nombre y matricula, y relacionarlas mediante asociación de muchos a muchos").

3. "COMPOUND_ACTION": El usuario combina una continuación/aceptación o múltiples etapas dependientes con una nueva orden en el mismo turno ("aplica esa relación y además crea la clase Proveedor con nombre y teléfono").
   - Tu deber es desglosar y formular el objetivo consolidado de múltiples pasos para el planificador, incluyendo explícitamente todos los nombres de clases, atributos y relaciones tanto de la parte continuada como de la parte nueva.
   - requires_mutation: true
   - resolved_goal: La lista de objetivos consolidada en orden lógico.

4. "NEEDS_MORE_CONTEXT": La solicitud del usuario le faltan exclusivamente las ENTIDADES MÍNIMAS IMPRESCINDIBLES que no se pueden inferir del historial ni del diagrama:
   - Para relaciones: ÚNICAMENTE clasifica como "NEEDS_MORE_CONTEXT" si falta una o ambas clases a relacionar (ej: "relaciona la clase Producto" sin segunda clase, o "relaciona las clases" habiendo 3 o más clases en el lienzo sin indicar cuáles dos), o si alguna clase no existe en `existing_classes_in_diagram`. Formula en `clarification_question` una pregunta cordial preguntando solo por la clase faltante (ej: "¿Con qué otra clase del diagrama deseas relacionar la clase Producto?").
     * ¡PROHIBIDO usar NEEDS_MORE_CONTEXT si ambas clases ya se conocen pero faltan el tipo de relación, las cardinalidades, el verbo o la dirección! Para eso clasifica como DIRECT_ACTION o CONTINUATION_OR_ANAPHORA con requires_mutation: true y RAZONA AUTÓNOMAMENTE en `resolved_goal`.
   - Para atributos: ÚNICAMENTE clasifica como "NEEDS_MORE_CONTEXT" si falta la clase destino (ej: "crea el atributo nombre" sin indicar en qué clase) o si falta el nombre del atributo.
     * ¡PROHIBIDO usar NEEDS_MORE_CONTEXT porque falte el tipo de dato o si es opcional/obligatorio!
   - requires_mutation: false
   - clarification_question: Una pregunta cordial, específica y contextual en español orientando al usuario exactamente sobre la entidad faltante (SIN tablas).
   - missing_info: Lista breve de datos faltantes (ej: ["target_class"] o ["class_name"]).

5. "CONCEPTUAL_CONSULTATION": El usuario hace preguntas teóricas, arquitectónicas o de asesoría de diseño UML ("¿qué relación conviene entre Pedido y Producto?", "¿qué es agregación?", "¿cómo modelar un carrito de compras?").
   - NO solicita modificar el diagrama en este turno.
   - requires_mutation: false
   - resolved_goal: La consulta a responder directamente en texto Markdown (SIN tablas).

6. "DECLINE_OR_CANCEL": El usuario indica explícitamente cancelar, declinar o descartar la sugerencia o solicitud pendiente ("cancela eso", "olvídalo", "no hagas nada", "déjalo así").
   - requires_mutation: false
   - resolved_goal: "Cancelar la solicitud pendiente."

REGLAS DE ORO:
- REGLA DE FORMATO ESTRICTA: NUNCA utilices tablas Markdown (filas y columnas con '|'). Toda respuesta, pregunta de clarificación y razonamiento debe ser exclusivamente texto plano, encabezados (###) y listas con viñetas (- ).
- REGLA DE RETOMA DE PENDIENTES: Solo debes clasificar como "CONTINUATION_OR_ANAPHORA" para reanudar una tarea pendiente (has_active_pending_continuation: true) si el usuario lo confirma explícitamente ("sí", "continúa", "reintenta", "dale", "procede", "hazlo") o si aporta la entidad pendiente (ej. si se le preguntó con qué clase relacionar Producto y responde "con Categoría", o si se preguntó en qué clase agregar el atributo y responde "en Producto"). Al retomar, integra la entidad pendiente y formula el `resolved_goal` completo y razonado.
- PROTOCOLO DE RAZONAMIENTO AUTÓNOMO DE DOMINIO:
  * Al relacionar clases (en DIRECT_ACTION, CONTINUATION_OR_ANAPHORA o COMPOUND_ACTION):
    - Si el usuario indicó tipo, cardinalidades o roles de forma coherente, respétalos fielmente.
    - Si el usuario solo indicó las dos clases (ej. "Relaciona Producto con Categoría") o solo el tipo sin cardinalidades ni roles (ej. "Quiero composición entre Venta y DetalleVenta", "Herencia entre Usuario y Administrador"), RAZONA AUTÓNOMAMENTE el diseño ideal de dominio e inclúyelo en `resolved_goal`:
      1. COMPOSITION (Composición): si una clase es un contenedor/todo y la otra es una parte débil dependiente del ciclo de vida del contenedor (ej. Venta y DetalleVenta, Pedido y DetallePedido, Factura y DetalleFactura). Cabezal de diamante en el todo (`source_class: Venta`) y parte en `target_class: DetalleVenta`. Sin cardinalidades ni label.
      2. AGGREGATION (Agregación): si una clase es un contenedor/agrupador y la otra es una parte independiente (ej. Departamento y Profesor). Cabezal de diamante en el contenedor (`source_class`). Sin cardinalidades ni label.
      3. GENERALIZATION (Herencia): si una clase es superclase/generalización y la otra es un subtipo/especialización (ej. Usuario y Administrador, Persona y Cliente). Cabezal triangular en la superclase (`target_class: Usuario`) y subclase en `source_class: Administrador`. Sin cardinalidades ni label.
      4. ASSOCIATION (Asociación - por defecto para entidades independientes):
         - REGLA DE LECTURA CRUZADA ("ORDEN INVERTIDO") PARA CARDINALIDADES:
           Ejemplo: `source = Producto`, `target = Categoría`.
           "Un Producto pertenece a 1 Categoría" -> la cardinalidad "1" se sitúa en el extremo de Categoría (`target_cardinality: "1"`).
           "Una Categoría tiene 0 a muchos Productos" -> la cardinalidad "0..*" se sitúa en el extremo de Producto (`source_cardinality: "0..*"`).
           Regla universal: La clase hija/detalle que lleva la clave foránea (Producto, Venta, etc.) SIEMPRE lleva "0..*" o "1..*". La clase padre/maestra referenciada (Categoría, Cliente, etc.) SIEMPRE lleva "1" o "0..1".
         - Etiqueta/verbo (`name`): asigna un verbo descriptivo en español (ej. "pertenece", "realiza", "incluye", "asigna", "contiene").
  * Al crear atributos (en DIRECT_ACTION o CONTINUATION_OR_ANAPHORA):
    - Si el usuario no especificó el tipo de dato, infiere el tipo UML más adecuado (ej. precio -> decimal, nombre -> string/text, cantidad/stock -> integer, activo -> boolean, fecha -> date/datetime).
    - Si el usuario no especificó nulabilidad, infiere `nullable: false` (obligatorio) para campos nucleares de negocio (nombre, precio, codigo, total, cantidad, stock, email, fecha) y `nullable: true` (opcional) para campos complementarios/descriptivos (descripcion, observaciones, notas, telefono, foto, descuento).
    - En `resolved_goal`, explicita siempre los tipos y nulabilidad razonados.
- REGLA DE METAMODELO Y EXISTENCIA UML:
  * Las llaves foráneas (FK) NO son atributos manuales; se generan automáticamente al crear relaciones entre clases. Si el usuario pide crear una llave foránea aislada ("crea una fk...", "llave foránea..."), clasifica como "NEEDS_MORE_CONTEXT" con clarification_question orientando a crear la relación entre las clases involucradas.
  * Las llaves primarias (PK) ya se crean automáticamente (`id: UUID`) con cada clase; no deben crearse manualmente como atributos.
  * Al redactar `resolved_goal` (en `DIRECT_ACTION`, `CONTINUATION_OR_ANAPHORA` o `COMPOUND_ACTION`), NUNCA incluyas `id` (PK) ni llaves foráneas (`*_id`, `id_*`, `fk_*`) dentro de las listas de atributos a crear en una clase, incluso si figuraban en el mensaje previo: incluye únicamente los atributos de dominio ordinarios y deja que las relaciones generen las FK automáticamente. Asimismo, en relaciones estructurales (composición, agregación, generalización/herencia, realización, dependencia), NO incluyas cardinalidades en `resolved_goal` (indica solo quién es el todo/parte o superclase/subclase).
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
            max_output_tokens=1000,
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
        has_advisory_keyword = any(
            w in lower
            for w in (
                "sugiere", "sugerencia", "recomienda", "recomendación", "recomendacion",
                "aconseja", "debería tener", "deberia tener", "cuáles son", "cuales son",
                "qué clases", "que clases",
            )
        )
        if (is_question or has_advisory_keyword) and not any(
            w in lower for w in ("crea", "agrega", "elimina", "modifica", "aplica", "conecta")
        ):
            return SemanticTurnDecision(
                category=SemanticCategory.CONCEPTUAL_CONSULTATION,
                reasoning="Pregunta conceptual o solicitud de asesoría detectada por fallback.",
                resolved_goal=message,
                requires_mutation=False,
                raw_message=message,
            )

        # Detección de peticiones incompletas en fallback defensivo
        import re
        single_rel_match = re.match(
            r"^\s*(?:relaciona(?:r)?|conecta(?:r)?)\s+(?:la\s+clase\s+)?([A-Za-z0-9_]+)\s*$",
            message,
            re.IGNORECASE,
        )
        if single_rel_match:
            cand = single_rel_match.group(1).strip()
            if cand.lower() not in ("las", "clases", "todo", "todas"):
                return SemanticTurnDecision(
                    category=SemanticCategory.NEEDS_MORE_CONTEXT,
                    reasoning=f"Falta la segunda clase para relacionar con {cand}.",
                    resolved_goal="",
                    requires_mutation=False,
                    missing_info=("target_class",),
                    clarification_question=f"¿Con qué otra clase del diagrama deseas relacionar la clase {cand}?",
                    raw_message=message,
                )

        single_attr_match = re.match(
            r"^\s*(?:crea|agrega|añade)\s+(?:el\s+)?atributo\s+([A-Za-z0-9_]+)\s*$",
            message,
            re.IGNORECASE,
        )
        if single_attr_match:
            attr_name = single_attr_match.group(1).strip()
            return SemanticTurnDecision(
                category=SemanticCategory.NEEDS_MORE_CONTEXT,
                reasoning=f"Falta la clase destino donde crear el atributo {attr_name}.",
                resolved_goal="",
                requires_mutation=False,
                missing_info=("target_class",),
                clarification_question=f"¿En qué clase deseas agregar el atributo `{attr_name}`?",
                raw_message=message,
            )

        # Si hay turnos recientes y menciona anáforas, confirmaciones o complementos de entidad
        has_entity_continuation = bool(
            re.match(r"^\s*(?:con|a|en)\s+(?:la\s+clase\s+)?([A-Za-z0-9_]+)\s*$", message, re.IGNORECASE)
        )
        has_anaphora = any(
            w in lower
            for w in (
                "esa", "ese", "esas", "esos", "eso", "conéctalas", "conectalas",
                "hazlo", "aplica", "sugerid", "créalas", "crealas", "continúa", "continua",
            )
        )
        if recent_turns and (has_anaphora or has_entity_continuation):
            return SemanticTurnDecision(
                category=SemanticCategory.CONTINUATION_OR_ANAPHORA,
                reasoning="Referencia anafórica o complemento de entidad detectado por fallback.",
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
