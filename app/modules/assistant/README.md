# Módulo Assistant — Arquitectura del Flujo Conversacional y Agéntico

Este módulo implementa el asistente de IA para modelado de diagramas UML e integración con el tablero de tareas de Notion.

## Fases del Pipeline (`ProcessAgentMessageUseCase`)

1. **Fase 0 — Ingesta y Contexto (`submit_agent_message_command.py` / `context_builder.py`)**:
   - Encolado asíncrono con clave de idempotencia y subida opcional de imagen a Cloudinary.
   - Análisis multimodal (`MultimodalImageAnalyzer`) si hay imagen adjunta, generando `visual_scope`.
   - Carga de turnos recientes (`recent_turns` incluyendo `notion_tasks_snapshot`), continuación activa (`AgentContinuation`), clases del diagrama (`existing_class_names`) y atributos por clase (`existing_class_attributes`).

2. **Fase 1 — Pre-Flight Checks Deterministas (0 Tokens)**:
   - Rechazo inmediato si se solicita ejecutar múltiples tareas de Notion al mismo tiempo.
   - Verificación temprana de Notion (`_check_notion_integration_readiness`): valida que el proyecto tenga API Key configurada (`has_api_key`) y página inicializada (`is_initialized`) antes de gastar tokens de LLM.
   - Compuerta determinista del metamodelo UML (`check_pre_plan_metamodel_gate`).
   - Resolución de ejecución de una tarea individual de Notion (`_handle_single_notion_task_execution`) usando caché reciente (`notion_tasks_snapshot`) o consulta MCP, soportando ordinales (`"primera"`, `"segunda"`, `"última"`), números (`"1"`, `"2"`) y títulos.

3. **Fase 2 — Enrutador Semántico y Bucle Multi-Turno (`SemanticIntentRouter`)**:
   - Se omite automáticamente (`_needs_semantic_context_resolution = False`) cuando el mensaje es un comando nuevo y auto-contenido sin continuación previa.
   - Distingue entre nueva acción (`DIRECT_GOAL`), continuación o acción compuesta (`CONTINUE_GOAL`), reintento de fallos parciales (`RESIDUAL_RETRY` con `ResidualPlanBuilder`), consulta conceptual (`CONCEPTUAL_QUERY`), cancelación (`CANCEL_CONTINUATION`) y falta de datos obligatorios (`NEEDS_MORE_CONTEXT`).
   - **Inferencia autónoma vs. Datos obligatorios**: Infiere tipos de relación, cardinalidades y tipos de datos consultando `existing_class_attributes`, pero solicita confirmación cuando faltan datos estructurales obligatorios (ej. clase destino o nombre de un atributo).
   - **Bucle multi-turno acumulativo**: Agrupa todos los datos faltantes en un solo mensaje con viñetas (`-`) y acumula respuestas parciales turno a turno en `AgentContinuation`.

4. **Fase 3 — Planificación Canónica (`ActionPlanner`)**:
   - Soporta peticiones **"Dos en Uno"** (sugerencia/explicación + mutación en diagrama o Notion).
   - Construye un DAG respetando el orden canónico:
     1. Crear clases (`create_class` con atributos inline).
     2. Agregar atributos a clases existentes (`create_attribute`).
     3. Crear/actualizar relaciones (`create_relation` / `update_relation`).
     4. Operaciones de Notion y cierre automático `update_notion_task(..., status='Done')`.
     5. Tarea `answer` para responder preguntas o explicar sugerencias.

5. **Fase 4 — Ejecución (`PlanExecutor` & `ToolRegistry`)**:
   - Ejecución topológica con agrupación de atributos por clase y reserva efímera de coordenadas.
   - `visual_scope` se aplica únicamente a herramientas con `visual_scope_validator` (diagrama), permitiendo usar herramientas de Notion tras analizar imágenes.
   - Resolución flexible de tareas en `NotionAgentTools._resolve_task_id` (UUID, ordinal, índice numérico o título).

6. **Fase 5 — Síntesis Híbrida (`agent_response.py`)**:
   - **Fast-Path determinista (0 tokens)** para mutaciones puras (diagrama y Notion) basado en `plan.operation_ledger`.
   - **Síntesis con LLM** cuando hay tareas `answer` o sugerencias (*"Dos en Uno"*), combinando la explicación con los hechos verificados del ledger.
