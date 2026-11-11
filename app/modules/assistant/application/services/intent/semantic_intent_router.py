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
from app.modules.assistant.application.services.planning.agent_intent import (
    is_audit_query,
    is_neon_sync_prompt,
)

logger = logging.getLogger(__name__)


class SemanticCategory(StrEnum):
    """Categorías semánticas exhaustivas del turno conversacional."""

    DIRECT_ACTION = "DIRECT_ACTION"
    CONTINUATION_OR_ANAPHORA = "CONTINUATION_OR_ANAPHORA"
    COMPOUND_ACTION = "COMPOUND_ACTION"
    NEEDS_MORE_CONTEXT = "NEEDS_MORE_CONTEXT"
    CONCEPTUAL_CONSULTATION = "CONCEPTUAL_CONSULTATION"
    AUDIT_QUERY = "AUDIT_QUERY"
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

Tu misión es analizar el mensaje del usuario considerando el contexto del proyecto y el historial reciente de conversación, y clasificarlo en una de 7 categorías con salida JSON estructurada estricta:

CATEGORÍAS:
1. "DIRECT_ACTION": El usuario da una instrucción de acción explícita y autosuficiente (crear, editar o eliminar clases, atributos o relaciones) que NO depende de resolver pronombres o anáforas de turnos previos.
   - requires_mutation: true (o false si es lectura/inspección de clases)
   - resolved_goal: La instrucción canónica clara para el planificador.

2. "CONTINUATION_OR_ANAPHORA": El usuario pide ejecutar, continuar, guardar o aplicar algo que hace referencia a temas, sugerencias, respuestas o recomendaciones previas ("aplica esa generalización", "haz lo que dijiste", "conéctalas", "dale con eso", "implementa la relación sugerida", "implementa eso", "créalas", "sí, hazlo", "aplica lo propuesto", "continúa", "agrega esa sugerencia a una tarea de Notion", "guarda eso en Notion", "crea esos atributos", "implementa todo eso", "crea todo lo que hablamos", "aplica todo lo acordado").
   - PRINCIPIO UNIVERSAL DE CONTINUIDAD CONVERSACIONAL:
     * Una continuación o anáfora es válida TANTO cuando `has_active_pending_continuation` es `true` COMO cuando `has_active_pending_continuation` es `false` pero existe historial en `recent_conversation_turns` (por ejemplo, cuando en turnos previos el asistente dio recomendaciones, sugirió atributos/clases/relaciones, o concluyó preguntando "¿Deseas que implemente estos cambios en tu diagrama?").
     * REGLA DE RECENCIA VS. CONSOLIDACIÓN MULTI-TURNO:
       1. Confirmación Singular / Inmediata: Cuando el usuario usa pronombres singulares ("esa sugerencia", "esos atributos", "esa relación", "eso", "sí, hazlo") refiriéndose a la última propuesta, toma los datos del turno inmediatamente anterior (`most_recent_turn`).
       2. Confirmación Global / Acumulativa: Cuando el usuario usa expresiones globales ("implementa todo eso", "crea todo lo que hemos hablado", "aplica todas las sugerencias", "haz todo", "crea el modelo acordado"), O cuando la conversación previa ha ido construyendo el modelo incrementalmente a lo largo de varios turnos (ej. Turno 1 propuso clase Usuario, Turno 2 propuso clase Rol, Turno 3 propuso la relación entre ellos):
          DEBES CONSOLIDAR Y RECAPITULAR TODAS las clases propuestas (con sus atributos) y TODAS las relaciones propuestas a lo largo de `recent_conversation_turns` (de más antiguo a más reciente). NUNCA descartes clases o atributos sugeridos en turnos anteriores del mismo hilo cuando el usuario pide implementar "todo".
   - Tu deber crucial es DESCONTEXTUALIZAR SIN PERDER DETALLES: reescribir la orden en una instrucción completa, explícita y auto-contenida que incluya TODOS los nombres reales de clases, todos sus atributos propuestos y todas las relaciones (con su tipo, dirección y cardinalidades) o todo el contenido recomendado que aparezca en `most_recent_turn`, en `recent_conversation_turns` o en `active_continuation_goal`.
   - PROHIBIDO resumir de forma vaga como "con los atributos sugeridos" o "con las relaciones mencionadas": debes listar explícitamente cada clase, cada atributo y cada relación dentro de `resolved_goal` para que el planificador y el ejecutor tengan toda la especificación completa.
   - Si la sugerencia previa del asistente proponía clases que aún no existen en `existing_classes_in_diagram`, `resolved_goal` DEBE ordenar primero la creación de esas clases con sus atributos y luego la creación de sus relaciones.
   - requires_mutation: true
   - resolved_goal: La instrucción completa canónica (ej: "Crear la clase Curso con atributos nombre y creditos, crear la clase Estudiante con atributos nombre y matricula, y relacionarlas mediante asociación de muchos a muchos", o consolidado multi-turno: "Crear la clase Usuario con atributos nombre y email; crear la clase Rol con atributos nombre y descripcion; y relacionar Rol con Usuario mediante asociación de 1 a N").

3. "COMPOUND_ACTION": El usuario combina una continuación/aceptación o múltiples etapas dependientes con una nueva orden en el mismo turno ("aplica esa relación y además crea la clase Proveedor con nombre y teléfono").
   - Tu deber es desglosar y formular el objetivo consolidado de múltiples pasos para el planificador, incluyendo explícitamente todos los nombres de clases, atributos y relaciones tanto de la parte continuada como de la parte nueva.
   - requires_mutation: true
   - resolved_goal: La lista de objetivos consolidada en orden lógico.

4. "NEEDS_MORE_CONTEXT": La solicitud del usuario carece de ENTIDADES MÍNIMAS OBLIGATORIAS que no se pueden inferir del historial ni del diagrama:
   - Para clases: si pide crear una clase pero no indica el nombre (ej: "crea una clase", "agrega una clase"), falta ["class_name"]. Formula en clarification_question: "¿Qué nombre deseas asignarle a la nueva clase?".
   - Para atributos:
     * Si pide crear un atributo sin indicar clase ni nombre (ej: "crea un atributo", "agrega un atributo", "hace un atributo"), faltan ["target_class", "attribute_name"]. Formula una ÚNICA pregunta agrupada: "Para crear el atributo necesito que me indiques los siguientes datos:\n- ¿En qué clase deseas agregarlo?\n- ¿Qué nombre debe tener el atributo?".
     * Si indica el nombre del atributo pero falta la clase (ej: "crea el atributo nombre", "hace un atributo llamado nombre"), falta ["target_class"]. Formula: "¿En qué clase deseas agregar el atributo?".
     * Si indica la clase pero falta el nombre del atributo (ej: "agrega un atributo a la clase Producto"), falta ["attribute_name"]. Formula: "¿Qué nombre debe tener el nuevo atributo para la clase Producto?".
     * ¡PROHIBIDO usar NEEDS_MORE_CONTEXT porque falte el tipo de dato o si es opcional/obligatorio! Esos datos se deducen autónomamente.
   - Para relaciones: ÚNICAMENTE clasifica como "NEEDS_MORE_CONTEXT" si falta una o ambas clases a relacionar (ej: "relaciona la clase Producto" sin segunda clase, o "relaciona las clases" habiendo 3 o más clases en el lienzo sin indicar cuáles dos), o si alguna clase no existe en `existing_classes_in_diagram`. Formula en `clarification_question` una pregunta cordial preguntando solo por la clase faltante (ej: "¿Con qué otra clase del diagrama deseas relacionar la clase Producto?").
     * ¡PROHIBIDO usar NEEDS_MORE_CONTEXT si ambas clases ya se conocen pero faltan el tipo de relación, las cardinalidades, el verbo o la dirección! Para eso clasifica como DIRECT_ACTION o CONTINUATION_OR_ANAPHORA con requires_mutation: true y RAZONA AUTÓNOMAMENTE en `resolved_goal`.
   - Para consultas de sugerencias (atributos o relaciones):
     * Si pide sugerencias de atributos (ej: "¿qué atributos me sugieres?", "¿qué atributos recomiendas?") sin indicar la clase:
       - Si en `existing_classes_in_diagram` hay 0 clases: falta ["target_class"]. Formula: "¿Para qué clase o entidad de tu sistema deseas que te sugiera atributos?".
       - Si en `existing_classes_in_diagram` hay 2 o más clases y no se especifica cuál: falta ["target_class"]. Formula: "¿Para cuál de tus clases deseas sugerencias de atributos? Puedes elegir entre: " listando las clases existentes.
       - Si en `existing_classes_in_diagram` hay exactamente 1 clase: ¡NO es NEEDS_MORE_CONTEXT! Clasifica como "CONCEPTUAL_CONSULTATION" y sugiere los atributos para esa clase directamente.
     * Si pide sugerencias de relaciones (ej: "¿qué relación me sugieres?", "¿cómo deberían relacionarse?") sin indicar las clases a conectar:
       - Si en `existing_classes_in_diagram` no hay exactamente 2 clases: falta ["relation_classes"]. Formula: "¿Entre cuáles dos clases deseas que te sugiera una relación?".
       - Si en `existing_classes_in_diagram` hay exactamente 2 clases: ¡NO es NEEDS_MORE_CONTEXT! Clasifica como "CONCEPTUAL_CONSULTATION" y sugiere la mejor relación entre esas dos clases directamente.
   - REGLA DE PREGUNTA ÚNICA AGRUPADA: Si faltan múltiples datos obligatorios (ej. clase destino y nombre del atributo, o ambas clases a relacionar), NUNCA hagas preguntas de una en una. Formula SIEMPRE una sola pregunta cordial agrupando todos los datos faltantes en una lista con viñetas.
   - REGLA DE BUCLE MULTI-TURNO PARCIAL ACUMULATIVO:
     * Si `has_active_pending_continuation` es true y `active_continuation_missing_fields` contenía campos pendientes, y en el turno actual el usuario proporciona solo algunos de esos datos (por ejemplo, se le pidieron clase y nombre, y solo responde indicando la clase):
       1. Mantén category: "NEEDS_MORE_CONTEXT".
       2. En `resolved_goal`, acumula la intención original integrando los datos que el usuario ya proporcionó (ej: "Crear atributo en la clase Producto [pendiente: nombre del atributo]") para no perderlos en el siguiente turno.
       3. En `missing_info`, incluye ÚNICAMENTE los campos que aún faltan.
       4. En `clarification_question`, pregunta en un solo mensaje cordial SOLO por los datos que todavía faltan.
       5. Cuando el usuario finalmente aporte todos los datos pendientes, cambia la categoría a "CONTINUATION_OR_ANAPHORA" (o "COMPOUND_ACTION" si además agregó una orden nueva) con el `resolved_goal` completo y cerrado con todos los datos consolidados.
   - requires_mutation: false
   - clarification_question: Una pregunta cordial, específica y contextual en español orientando al usuario exactamente sobre la entidad faltante (SIN tablas).
   - missing_info: Lista breve de datos faltantes (ej: ["target_class", "attribute_name"] o ["class_name"]).

5. "CONCEPTUAL_CONSULTATION": El usuario hace preguntas teóricas, arquitectónicas o de asesoría de diseño UML ("¿qué relación conviene entre Pedido y Producto?", "¿qué es agregación?", "¿cuál es la diferencia entre generalización y herencia?", "¿cómo modelar un carrito de compras?").
   - Incluye preguntas abiertas y teóricas sobre el estándar UML 2.5 (no requieren entidades del proyecto; responde como consultor experto).
   - Incluye sugerencias de atributos o relaciones cuando las entidades ya se conocen o se infieren de la única clase del lienzo.
   - En toda respuesta de recomendación de entidades o cambios, concluye siempre preguntando de forma cordial: '¿Deseas que implemente estos cambios en tu lienzo?'.
   - NO solicita modificar el diagrama en este turno.
   - requires_mutation: false
   - resolved_goal: La consulta a responder directamente en texto Markdown (SIN tablas).

6. "AUDIT_QUERY": El usuario pregunta quién realizó una acción o qué cambios se hicieron históricamente ("¿Quién creó la clase Producto?", "¿Quién modificó el atributo stock?", "¿Qué cambios hizo Juan hoy?", "¿Quién borró la relación entre Cliente y Factura?", "¿Qué cambios ha tenido la clase Usuario?", "¿Qué modificaciones se hicieron hoy en el proyecto?").
   - DIRECTIVA DE AUTORÍA VS. MUTACIÓN: Si el mensaje del usuario pregunta quién realizó una acción o qué cambios se hicieron en el pasado, está ESTRICTAMENTE PROHIBIDO clasificarlo como DIRECT_ACTION ni asignar requires_mutation: true. No se está pidiendo crear ni modificar nada. Clasifica como AUDIT_QUERY con requires_mutation: false y resolved_goal indicando resolver la consulta mediante la herramienta query_diagram_audit_logs.
   - DIRECTIVA DE SUGERENCIAS VS. AUDITORÍA: Si el usuario pregunta por recomendaciones futuras o asesoría de modelado (ej: "¿qué atributos me sugieres?", "¿qué atributos puedo colocar?", "¿cómo recomiendas modelar?"), clasifica como CONCEPTUAL_CONSULTATION. Si el usuario pregunta qué atributos fueron agregados, modificados o creados por alguien en el pasado (ej: "¿qué atributos agregó Juan?", "¿qué cambios se hicieron ayer?"), clasifica como AUDIT_QUERY.
   - requires_mutation: false
   - resolved_goal: La consulta histórica a resolver usando query_diagram_audit_logs.

7. "DECLINE_OR_CANCEL": El usuario indica explícitamente cancelar, declinar o descartar la sugerencia o solicitud pendiente ("cancela eso", "olvídalo", "no hagas nada", "déjalo así").
   - requires_mutation: false
   - resolved_goal: "Cancelar la solicitud pendiente."

REGLAS DE ORO:
- REGLA DE FORMATO ESTRICTA: NUNCA utilices tablas Markdown (filas y columnas con '|'). Toda respuesta, pregunta de clarificación y razonamiento debe ser exclusivamente texto plano, encabezados (###) y listas con viñetas (- ).
- EQUIVALENCIA TERMINOLÓGICA DE MODELADO: Los términos 'tabla', 'entidad' o 'modelo' son sinónimos directos de 'clase' en UML. Los términos 'campo' o 'columna' son sinónimos directos de 'atributo'. Trátalos exactamente como clases y atributos del metamodelo UML sin pedir clarificación por el vocabulario.
- REGLA DE RETOMA DE PENDIENTES, ANÁFORAS Y SUGERENCIAS RECIENTES:
  * Si `has_active_pending_continuation` es `true`, clasifica como "CONTINUATION_OR_ANAPHORA" cuando el usuario confirme continuar ("sí", "continúa", "reintenta", "dale", "procede", "hazlo") o cuando aporte los datos faltantes solicitados en el turno anterior.
  * Si `has_active_pending_continuation` es `false`, igualmente clasifica como "CONTINUATION_OR_ANAPHORA" (o "COMPOUND_ACTION" si agrega otra acción) cuando el usuario pida aplicar, ejecutar o guardar en Notion la sugerencia, recomendación o propuesta que el asistente acaba de presentar en `most_recent_turn`. Toma siempre `most_recent_turn` como el referente inmediato sin dudar entre turnos antiguos.
  * En `recent_turns`, cada turno puede incluir `confirmed_operations` con las entidades y atributos recién creados o modificados. Si el usuario dice "agrega X a esa clase", "¿qué relación debería tener esa entidad con Y?" o "modifica esa tabla", resuelve la referencia anafórica ("esa clase", "esa tabla") vinculándola prioritariamente a la entidad creada o afectada en `confirmed_operations` del turno inmediatamente anterior.
  * Si el usuario dice "implementa todo eso", "crea todo lo acordado", "aplica todo lo que hablamos" a través de varios turnos de discusión: consolida TODAS las clases, atributos y relaciones discutidas en `recent_turns` en `resolved_goal` en orden canónico (primero creación de clases con sus atributos de dominio, y al final las relaciones entre ellas).
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
  * Órdenes relacionadas con NOTION (crear tarea, ver tareas, modificar tarea, eliminar tarea, consultar pendientes):
    - REGLA DE AISLAMIENTO ESTRICTO DE NOTION (PROHIBICIÓN DE PETICIONES MIXTAS):
      * De momento, el asistente permite que un turno se dedique a Notion O al Diagrama, nunca a ambos simultáneamente.
      * Si el usuario formula una solicitud que mezcla órdenes del diagrama UML (crear, modificar o relacionar clases, o confirmar cambios en el lienzo) Y AL MISMO TIEMPO solicita acciones en Notion (crear, listar o modificar tareas):
        - ESTÁ ESTRICTAMENTE PROHIBIDO formular un plan compuesto (COMPOUND_ACTION) o ejecutar ambas cosas a la vez.
        - Clasifica obligatoriamente como 'NEEDS_MORE_CONTEXT' con requires_mutation: false.
        - En clarification_question, responde sugiriendo resolver una cosa a la vez y preguntando:
          'He detectado que solicitas tanto modificaciones en el diagrama como acciones en Notion. Para mantener la coherencia y el orden en tu proyecto, estas acciones deben gestionarse por separado. ¿Deseas que primero aplique los cambios en el lienzo o que primero gestione la tarea en Notion?'
    - CONSULTAS Y GESTIÓN PURA DE NOTION:
      * Si el usuario pide ver sus tareas ('dime mis tareas en Notion', 'cuáles tareas tengo pendientes', 'ver tareas hechas'): clasifica como DIRECT_ACTION con requires_mutation: false y resolved_goal indicando consultar las tareas del usuario mediante list_notion_tasks.
      * Si el usuario pide crear una tarea puntual ('crea una tarea en Notion llamada X'): clasifica como DIRECT_ACTION con requires_mutation: true y resolved_goal indicando crear la tarea mediante create_notion_task con estado pendiente.
    - EXCEPCIÓN VÁLIDA (SUGERENCIA PREVIA -> TAREA EN NOTION):
      * Si el usuario retoma una recomendación o sugerencia del turno anterior ÚNICAMENTE para guardarla en Notion (ej: 'agrega esa sugerencia a una tarea nueva de Notion', 'crea una tarea en Notion con eso', 'guarda esos atributos en una tarea') SIN pedir implementar en el lienzo al mismo tiempo:
        - Esto NO es una mezcla prohibida; es una acción pura hacia Notion.
        - Clasifica como CONTINUATION_OR_ANAPHORA hacia Notion con requires_mutation: true.
        - resolved_goal: 'Crear una nueva tarea en Notion asignada al usuario con título y descripción detallada basados en las sugerencias del turno anterior usando create_notion_task.'
    - EJECUCIÓN DE TAREAS DE NOTION SOBRE EL DIAGRAMA:
      * Si el usuario pide ejecutar o implementar una tarea de Notion ('ejecuta la tarea 1 de Notion', 'implementa la tarea X'): solo se permite UNA tarea a la vez. Clasifica como DIRECT_ACTION con requires_mutation: true.
      * Si el usuario pide 'haz todas las tareas' o pide ejecutar múltiples tareas de Notion a la vez: clasifica como DIRECT_ACTION con requires_mutation: false e indica en clarification_question o respuesta que solo se permite ejecutar una única tarea a la vez para mantener la coherencia del diagrama.
  * Órdenes relacionadas con NEON (PostgreSQL Serverless vía MCP):
    - Si el usuario dice "despliega esto en Neon", "actualiza la base de datos de Neon", "migra a Neon", "sincroniza Neon", "sincroniza nuestro proyecto a Neon", o menciona "actualiza la clase X en Neon":
      - Clasifica como DIRECT_ACTION con requires_mutation: true (o CONTINUATION_OR_ANAPHORA con requires_mutation: true si continúa o confirma algo previo como "sí, sincroniza...").
      - `resolved_goal` debe indicar explícitamente: "Sincronizar la base de datos PostgreSQL en Neon con el estado actual del diagrama mediante la herramienta sync_neon_database".
      - Si el usuario formula una orden compuesta (ej: "elimina la clase Categoria del diagrama y actualiza Neon"), clasifica como COMPOUND_ACTION con requires_mutation: true y descontextualiza ambos pasos: 1º mutar el diagrama, 2º sincronizar Neon con sync_neon_database.
  * Las llaves foráneas (FK) NO son atributos manuales; se generan automáticamente al crear relaciones entre clases. Si el usuario pide crear una llave foránea aislada ("crea una fk...", "llave foránea..."), clasifica como "NEEDS_MORE_CONTEXT" con clarification_question orientando a crear la relación entre las clases involucradas.
  * Las llaves primarias (PK) ya se crean automáticamente (`id: UUID`) con cada clase; no deben crearse manualmente como atributos.
  * Al redactar `resolved_goal` (en `DIRECT_ACTION`, `CONTINUATION_OR_ANAPHORA` o `COMPOUND_ACTION`), NUNCA incluyas `id` (PK) ni llaves foráneas en snake_case o camelCase (`*_id`, `id_*`, `fk_*`, `categoriaId`, `idCategoria`, `usuarioId`) dentro de las listas de atributos a crear en una clase, incluso si figuraban en el mensaje previo: incluye únicamente los atributos de dominio ordinarios y deja que las relaciones generen las FK automáticamente. Asimismo, en relaciones estructurales (composición, agregación, generalización/herencia, realización, dependencia), NO incluyas cardinalidades en `resolved_goal` (indica solo quién es el todo/parte o superclase/subclase).
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
        existing_class_attributes: dict[str, list[str]] | None = None,
    ) -> SemanticTurnDecision:
        return await self.route(
            user_message=prompt,
            recent_turns=recent_turns,
            existing_classes=existing_classes,
            active_continuation=active_continuation,
            existing_class_attributes=existing_class_attributes,
        )

    async def route(
        self,
        *,
        user_message: str,
        recent_turns: Sequence[dict[str, Any]] = (),
        existing_classes: Sequence[str] | dict[str, Any] = (),
        active_continuation: Any | None = None,
        existing_class_attributes: dict[str, list[str]] | None = None,
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
            return self._fallback_route(
                clean_msg,
                recent_turns,
                classes_list,
                active_continuation=active_continuation,
            )

        turns_slice = list(recent_turns)[-8:] if recent_turns else []
        payload = {
            "current_user_message": clean_msg,
            "most_recent_turn": turns_slice[-1] if turns_slice else None,
            "older_conversation_turns": turns_slice[:-1] if len(turns_slice) > 1 else [],
            "recent_conversation_turns": turns_slice,
            "existing_classes_in_diagram": classes_list,
            "existing_classes_attributes": existing_class_attributes or {},
            "has_active_pending_continuation": active_continuation is not None,
            "active_continuation_goal": (
                getattr(active_continuation, "effective_request", None)
                if active_continuation else None
            ),
            "active_continuation_missing_fields": (
                list(getattr(active_continuation, "missing_fields", []))
                if active_continuation else []
            ),
            "active_continuation_resolved_facts": (
                list(getattr(active_continuation, "resolved_facts", []))
                if active_continuation else []
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

        if is_neon_sync_prompt(raw_message) or is_neon_sync_prompt(resolved_goal):
            requires_mutation = True
            if category in (SemanticCategory.CONCEPTUAL_CONSULTATION, SemanticCategory.NEEDS_MORE_CONTEXT):
                category = (
                    SemanticCategory.CONTINUATION_OR_ANAPHORA
                    if any(w in raw_message.lower() for w in ("sí", "si", "ok", "hazlo", "procede"))
                    else SemanticCategory.DIRECT_ACTION
                )
                resolved_goal = "Sincronizar la base de datos PostgreSQL en Neon con el estado actual del diagrama mediante la herramienta sync_neon_database"
                clarification_question = None

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
        active_continuation: Any | None = None,
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

        if is_neon_sync_prompt(message):
            return SemanticTurnDecision(
                category=(
                    SemanticCategory.CONTINUATION_OR_ANAPHORA
                    if any(w in lower for w in ("sí", "si", "ok", "hazlo", "procede"))
                    else SemanticCategory.DIRECT_ACTION
                ),
                reasoning="Sincronización con Neon detectada en fallback.",
                resolved_goal="Sincronizar la base de datos PostgreSQL en Neon con el estado actual del diagrama mediante la herramienta sync_neon_database",
                requires_mutation=True,
                raw_message=message,
            )

        # Manejo de bucle multi-turno acumulativo si hay continuación activa pendiente
        import re
        if active_continuation is not None and getattr(active_continuation, "missing_fields", None):
            missing_keys = [
                f.get("field") if isinstance(f, dict) else str(f)
                for f in active_continuation.missing_fields
            ]
            prior_goal = getattr(active_continuation, "effective_request", "") or ""
            
            # Si faltaban target_class y attribute_name
            if "target_class" in missing_keys and "attribute_name" in missing_keys:
                cls_match = re.search(r"\b(?:en|para|a)\s+(?:la\s+clase\s+)?([A-Za-z0-9_]+)\b", message, re.IGNORECASE)
                attr_match = re.search(r"\b(?:llamado|nombre|campo|atributo)?\s*([A-Za-z0-9_]+)\b", message, re.IGNORECASE)
                if cls_match:
                    found_cls = cls_match.group(1).strip()
                    rem_missing = ("attribute_name",)
                    return SemanticTurnDecision(
                        category=SemanticCategory.NEEDS_MORE_CONTEXT,
                        reasoning=f"Se recibió la clase {found_cls}, falta el nombre del atributo.",
                        resolved_goal=f"Crear atributo en la clase {found_cls} [pendiente: nombre]",
                        requires_mutation=False,
                        missing_info=rem_missing,
                        clarification_question=f"¿Qué nombre debe tener el atributo para la clase {found_cls}?",
                        raw_message=message,
                    )
            elif "target_class" in missing_keys:
                cls_cand = re.sub(r"^(?:en|para|a)\s+(?:la\s+clase\s+)?", "", message.strip(), flags=re.IGNORECASE).strip(". ")
                if cls_cand and re.fullmatch(r"[A-Za-z0-9_]+", cls_cand):
                    accum_goal = prior_goal.replace("[pendiente: clase]", f"en la clase {cls_cand}").replace("[falta: clase]", f"en la clase {cls_cand}")
                    if "en la clase" not in accum_goal:
                        accum_goal = f"{accum_goal} en la clase {cls_cand}".strip()
                    return SemanticTurnDecision(
                        category=SemanticCategory.CONTINUATION_OR_ANAPHORA,
                        reasoning=f"Se completó la clase destino {cls_cand}.",
                        resolved_goal=accum_goal,
                        requires_mutation=True,
                        raw_message=message,
                    )
            elif "attribute_name" in missing_keys:
                attr_cand = re.sub(r"^(?:llamado|nombre|campo|atributo)?\s*", "", message.strip(), flags=re.IGNORECASE).strip(". ")
                if attr_cand and re.fullmatch(r"[A-Za-z0-9_]+", attr_cand):
                    accum_goal = prior_goal.replace("[pendiente: nombre]", f"llamado {attr_cand}").replace("[falta: nombre]", f"llamado {attr_cand}")
                    if "llamado" not in accum_goal and "atributo" in accum_goal:
                        accum_goal = f"{accum_goal} con nombre {attr_cand}".strip()
                    return SemanticTurnDecision(
                        category=SemanticCategory.CONTINUATION_OR_ANAPHORA,
                        reasoning=f"Se completó el nombre del atributo {attr_cand}.",
                        resolved_goal=accum_goal,
                        requires_mutation=True,
                        raw_message=message,
                    )

        if is_audit_query(message):
            return SemanticTurnDecision(
                category=SemanticCategory.AUDIT_QUERY,
                reasoning="Consulta de auditoría histórica detectada por fallback.",
                resolved_goal=message,
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
            w in lower for w in (
                "crea", "agrega", "añade", "anade", "elimina", "modifica", "aplica",
                "conecta", "coloca", "guarda", "implementa", "haz", "registra",
                "pasa", "convierte",
            )
        ):
            return SemanticTurnDecision(
                category=SemanticCategory.CONCEPTUAL_CONSULTATION,
                reasoning="Pregunta conceptual o solicitud de asesoría detectada por fallback.",
                resolved_goal=message,
                requires_mutation=False,
                raw_message=message,
            )

        # Detección de peticiones incompletas en fallback defensivo
        # 1. Petición de clase sin nombre
        if re.fullmatch(r"^\s*(?:crea(?:r)?|haz|agrega(?:r)?|a[ñn]ade(?:r)?)\s+(?:una\s+)?clase\s*[\.\?!]*$", message, re.IGNORECASE):
            return SemanticTurnDecision(
                category=SemanticCategory.NEEDS_MORE_CONTEXT,
                reasoning="Falta el nombre de la clase.",
                resolved_goal="Crear clase",
                requires_mutation=False,
                missing_info=("class_name",),
                clarification_question="¿Qué nombre deseas asignarle a la nueva clase?",
                raw_message=message,
            )

        # 2. Petición de atributo sin clase ni nombre
        if re.fullmatch(r"^\s*(?:crea(?:r)?|haz|hace|agrega(?:r)?|a[ñn]ade(?:r)?)\s+(?:un\s+)?atributo\s*[\.\?!]*$", message, re.IGNORECASE):
            return SemanticTurnDecision(
                category=SemanticCategory.NEEDS_MORE_CONTEXT,
                reasoning="Faltan la clase destino y el nombre del atributo.",
                resolved_goal="Crear atributo [falta: clase y nombre]",
                requires_mutation=False,
                missing_info=("target_class", "attribute_name"),
                clarification_question="Para crear el atributo necesito que me indiques los siguientes datos:\n- ¿En qué clase deseas agregarlo?\n- ¿Qué nombre debe tener el atributo?",
                raw_message=message,
            )

        # 3. Petición de atributo con clase pero sin nombre
        attr_in_class_match = re.match(
            r"^\s*(?:crea|agrega|añade|hace|haz)\s+(?:un\s+)?atributo\s+(?:en|a)\s+(?:la\s+clase\s+)?([A-Za-z0-9_]+)\s*[\.\?!]*$",
            message,
            re.IGNORECASE,
        )
        if attr_in_class_match:
            cls_target = attr_in_class_match.group(1).strip()
            return SemanticTurnDecision(
                category=SemanticCategory.NEEDS_MORE_CONTEXT,
                reasoning=f"Falta el nombre del atributo para la clase {cls_target}.",
                resolved_goal=f"Crear atributo en la clase {cls_target} [falta: nombre]",
                requires_mutation=False,
                missing_info=("attribute_name",),
                clarification_question=f"¿Qué nombre debe tener el nuevo atributo para la clase {cls_target}?",
                raw_message=message,
            )

        # 4. Petición de relación incompleta
        single_rel_match = re.match(
            r"^\s*(?:relaciona(?:r)?|conecta(?:r)?)\s+(?:la\s+clase\s+)?([A-Za-z0-9_]+)\s*[\.\?!]*$",
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

        # 5. Petición de atributo con nombre pero sin clase
        single_attr_match = re.match(
            r"^\s*(?:crea|agrega|añade|hace|haz)\s+(?:el\s+)?atributo\s+(?:llamado\s+)?([A-Za-z0-9_]+)\s*[\.\?!]*$",
            message,
            re.IGNORECASE,
        )
        if single_attr_match:
            attr_name = single_attr_match.group(1).strip()
            return SemanticTurnDecision(
                category=SemanticCategory.NEEDS_MORE_CONTEXT,
                reasoning=f"Falta la clase destino donde crear el atributo {attr_name}.",
                resolved_goal=f"Crear atributo {attr_name} [falta: clase]",
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
