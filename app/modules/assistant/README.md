# Asistente backend

El módulo recibe prompts autenticados de un proyecto, ejecuta inferencias acotadas con Qwen Model Studio, conserva memoria individual por usuario/proyecto y permite al agente consultar o cambiar el diagrama mediante un catálogo cerrado de herramientas.

## Continuidad y planificación del diálogo

Antes de planificar, `DialogManager` interpreta cada turno con el estado pendiente del usuario y los intercambios recientes del mismo proyecto. Una orden nueva y autosuficiente cierra la aclaración anterior; respuestas breves como «sí», «continúa» o el dato solicitado completan el objetivo pendiente. El cambio explícito de tema también inicia un objetivo nuevo. Los marcos de diálogo guardan los campos faltantes y las propuestas estructuradas en `AgentContinuation`; las propuestas del último mensaje también se pueden recuperar desde `AgentMessage.plan.dialog_state` sin interpretar Markdown. La reclamación del objetivo pendiente usa CAS para evitar dos continuaciones simultáneas.

Las consultas que piden sugerencias de atributos o relaciones leen las clases actuales con autorización de Diagram. Solo se propone una mutación tras verificar que las clases son inequívocas y que el detalle no está truncado. Los atributos sugeridos se comparan con los existentes y se filtran PK, FK, campos de ID, tipos inválidos y duplicados. La propuesta conserva nombres, tipos y nulabilidad hasta que el usuario la acepte. Las relaciones sugeridas se validan según tipo, cardinalidades y roles antes de ofrecerlas. Una recomendación nunca modifica el diagrama por sí sola.

El planificador agrupa creaciones independientes de clases y atributos por clase cuando procede, y registra las dependencias antes de relaciones. Cada tarea puede incluir `expected_actions`: una lista acotada de operaciones esperadas, opcionalmente con el nombre objetivo. El ejecutor compara esa lista con operaciones *confirmadas* en el ledger; si falta alguna, pide una sola corrección al modelo para realizar solo lo pendiente y luego falla la tarea si sigue incompleta. Esta verificación solo aplica cuando el plan contiene la lista; no sustituye las validaciones de permisos, contratos y estado actual que ejecutan las herramientas.

## Crear un mensaje

`POST /api/projects/{project_id}/assistant/messages` requiere autenticación y `multipart/form-data`:

| Campo | Requerido | Detalle |
| --- | --- | --- |
| `message_id` | Sí | UUID asignado por el cliente; no se puede reutilizar. |
| `prompt` | Sí | De 1 a 10 000 caracteres después de recortar espacios. |
| `image` | No | PNG, JPEG o WebP válido, hasta 10 MiB. |

La identidad viene del token y el acceso se valida contra el proyecto. El primer mensaje activo de un usuario en un proyecto se guarda como `running`; los siguientes se guardan como `queued`. La base de datos protege la exclusividad del estado `running`.

La aceptación devuelve `202` con el mensaje persistido en `running`; un reintento idéntico con el mismo UUID devuelve el registro existente con `200`. El POST no espera a Qwen: un ejecutor de fondo toma el trabajo después del commit y guarda un estado terminal (`completed`, `failed` o `cancelled`) y un `response_markdown` no vacío. El endpoint `GET .../active` permite recuperar la ejecución propia, y `POST .../{message_id}/cancel` solicita su cancelación cooperativa.

La cola visible de hasta tres prompts es local al navegador y no se persiste. El cliente envía el siguiente solo tras confirmar el estado terminal del anterior. Un `queued` histórico se conserva como dato inerte: el worker nunca lo promueve ni lo ejecuta.

Las solicitudes simples usan la ejecución directa; las solicitudes compuestas se dividen en tareas con dependencias y consultas al final. El plan y su ledger se guardan en `AgentMessage.plan` con control optimista de versión. Si una tarea falla, el mensaje termina como `failed`, el ledger conserva los cambios confirmados y la respuesta advierte que no se completó toda la solicitud. No se reintentan operaciones inciertas automáticamente.

## Solicitudes con imágenes UML/ERD

Un mensaje con imagen requiere también un prompt no vacío. El orquestador analiza primero solo el texto con el rol `PLANNING`; no incluye la URL ni el binario en esa llamada. Si hace falta evidencia visual, el rol `VISION` recibe la URL HTTPS de Cloudinary y el alcance textual (clases, atributos y relaciones solicitados). El resultado debe pasar el contrato estructurado antes de planificar o ejecutar herramientas. Una imagen incompatible o una incertidumbre estructural bloqueante termina sin mutaciones. El texto detectado dentro de la imagen se trata como dato no confiable.

Los selectores de clase, atributo y relación se filtran en el servidor, no solo por instrucciones al modelo. Las solicitudes de análisis llaman al modelo principal sin herramientas de mutación. Las llaves primarias, foráneas y clases puente no se importan como atributos/clases ordinarios: se obtienen de la creación de clases y relaciones existente. Tipos de atributo fuera del catálogo o llaves visuales contradictorias requieren precisión; un tipo sin inferencia razonable permanece `null`, y la nulabilidad omitida por el agente usa `true`.

Las coincidencias exactas e inequívocas por nombre de clase/atributo y las relaciones equivalentes se reutilizan para evitar duplicados. Si hay varias clases con el mismo nombre, el asistente pide al usuario el ID de una de ellas antes de cambiarla; la elección se comprueba en el proyecto y limita las operaciones posteriores a esa clase. Una clase/atributo existente no se sobrescribe por el simple hecho de reutilizarlo: las actualizaciones requieren una operación explícita. Si se solicita una eliminación, la confirmación afirmativa se pide por separado; la respuesta de confirmación se limita a esa solicitud original.

Las aclaraciones visuales se guardan como metadata versionada dentro del plan del mensaje, vinculadas a usuario/proyecto/imagen original y con vigencia de 24 horas. Solo se pueden consumir una vez mediante comparación atómica; una respuesta sin referencia inequívoca no se asocia arbitrariamente. Si una ambigüedad aparece después de cambios confirmados, el marcador conserva el progreso previo. No se crea una tabla ni una ruta nueva.

Ejemplos: «Analiza la clase Producto» no cambia el diagrama; «crea solo Producto sin relaciones» no importa clases vecinas; «recrea todo el diagrama» incorpora los elementos legibles, pero conserva el resto del proyecto. En N:M, la relación crea el puente y sus llaves; un atributo adicional de esa tabla usa únicamente el ID confirmado que devuelve Diagram.

## Herramientas del diagrama

El modelo dispone de `search_diagram_elements`, `get_diagram_element` y `apply_diagram_changes`. Las consultas devuelven páginas acotadas (cursor opaco) o el detalle de una clase, atributo o relación; nunca se envía el snapshot completo. La identidad de proyecto/usuario/mensaje y las políticas se fijan en el servidor, se rechaza cualquier intento del modelo de sobreescribirla y se vuelve a validar autorización y pertenencia por cada mutación.

`apply_diagram_changes` admite crear/renombrar/eliminar clases; crear/actualizar/reordenar/eliminar atributos secundarios; y crear/renombrar/eliminar relaciones. Cada operación pasa por los casos de uso existentes de Diagram y hace commit por separado: un lote no es atómico y los cambios anteriores permanecen si una operación posterior falla. No se permite mover clases ni crear PK, FK o clases puente manualmente. La creación de relaciones aplica la política vigente de Diagram (incluida la clase puente N:M y sus dos FK); las peticiones redundantes de PK/FK/puente se tratan como efectos derivados. Se puede añadir un atributo al puente usando el ID confirmado devuelto al crear la relación.

Cada mutación confirmada publica `diagram_mutation` después del commit con `sender_id: "assistant"` y la proyección materializada necesaria para aplicar relaciones, llaves foráneas y clases puente sin esperar la respuesta final. Al cerrar, se emite `agent_message_finished` con la respuesta persistida y el estado terminal. No se emiten locks globales del agente ni eventos de progreso; la aurora es estado local del autor.

## Configuración de imágenes

La carga requiere `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY` y `CLOUDINARY_API_SECRET`. `CLOUDINARY_TIMEOUT_SECONDS` limita la espera (30 segundos por defecto). Qwen requiere `QWEN_API_KEY`; `QWEN_BASE_URL` debe apuntar al endpoint HTTPS compatible con Chat Completions de la región/workspace de la cuenta. Si la clave no está configurada, otros módulos pueden iniciar, pero una inferencia creada finaliza como `failed`.

Los modelos por rol se editan en el entorno: `QWEN_MODEL_MAIN`, `QWEN_MODEL_VISION`, `QWEN_MODEL_PLANNING` y `QWEN_MODEL_COMPACTION`. La plantilla incluye nombres iniciales de ejemplo que pueden no estar disponibles en toda cuenta o región. `QWEN_TIMEOUT_SECONDS` limita cada solicitud HTTP (120 segundos por defecto) para permitir planificación con razonamiento amplio. No se añaden dependencias: el backend reutiliza `httpx` ya instalado. Nunca registrar ni incluir la clave en errores.

Para diagnosticar localmente el flujo completo, configura `QWEN_DEBUG_LOG_CONTENT=true` junto con `ENVIRONMENT=DEV` y reinicia el backend. La consola mostrará cada inferencia con `message_id`, `inference_id`, propósito (`action_plan`, `visual_intent`, `visual_evidence`, `task_execution`, `final_synthesis`, etc.), modelo, duración, payload enviado y cuerpo recibido. También registra inicio y cierre de tareas, tool calls, argumentos, resultados y progreso de mutaciones. El header de autorización y `QWEN_API_KEY` nunca se escriben. Este modo sí expone prompts, memoria, URLs de imágenes y resultados de herramientas en la consola; debe permanecer desactivado fuera del diagnóstico local.

El modelo de visión recibe el alcance textual validado y la URL HTTPS persistida de Cloudinary, no el prompt original ni el binario. Su evidencia textual se acota y se envía como dato no confiable al modelo principal, que siempre redacta la respuesta final.

La URL de imagen es un enlace compartible; HTTPS no la hace privada. El servidor crea un identificador remoto nuevo por intento y, si falla la persistencia, intenta eliminar solamente el activo de ese intento. Cloudinary y la base de datos no comparten una transacción distribuida, por lo que una interrupción del proceso puede dejar un activo huérfano.

## Persistencia y compatibilidad

Aplicar las migraciones Alembic `031_agent_msgs_memories` y `032_agent_message_plan_version` antes de usar PostgreSQL. La última añade la versión CAS requerida para guardar progreso del plan sin sobrescribir una ejecución concurrente.

`AGENT_CONTEXT_MAX_TOKENS` limita a 20000 el presupuesto total estimado de cada llamada: entrada, definiciones de tools y salida reservada. `AGENT_MEMORY_MAX_TOKENS` mantiene aparte la memoria persistida por usuario/proyecto en 7000 tokens. Desde `ceil(0.9 × presupuesto)` (6300 con el valor inicial), se compacta con el modelo dedicado antes de visión o respuesta principal. La salida debe ser Markdown no vacío y caber dentro de la mitad del presupuesto. La memoria compactada se confirma antes de continuar; al finalizar correctamente, memoria y mensaje `completed` se guardan en la misma transacción. Los extractos no guardan binarios ni URLs.

La planificación reserva `AGENT_PLANNING_MAX_OUTPUT_TOKENS` (6000) y habilita razonamiento. Cada llamada de ejecución con tools reserva `AGENT_TASK_MAX_OUTPUT_TOKENS` (2000); la síntesis final usa `AGENT_FINAL_MAX_OUTPUT_TOKENS` (700) y mantiene el estilo breve definido en el prompt del sistema. La estimación local usa caracteres y es conservadora, pero no sustituye el conteo del proveedor ni amplía la ventana nativa del modelo seleccionado.

`AgentUserMemory` está aislada por usuario y proyecto, y nunca incorpora memoria de otros colaboradores. No se persiste un contador de tokens; se reutilizan `agent_messages` y `agent_user_memories` con una columna `plan_version` para CAS. Las rutas antiguas `/api/assistant/voice` y `/api/assistant/image` están retiradas; texto e imagen opcional usan el endpoint unificado.

`AGENT_MAX_PLAN_TASKS` (20), `AGENT_MAX_DIAGRAM_ACTIONS` (30), `AGENT_MAX_TOOL_CALLS` (20), `AGENT_MAX_TOOL_ARGUMENTS_CHARS` (12000), `AGENT_MAX_TOOL_RESULT_CHARS` (16000), `AGENT_MAX_ELEMENT_DETAIL_ITEMS` (20) y `AGENT_MAX_EXECUTION_SECONDS` (240) acotan la planificación, el tamaño de lecturas y la ejecución. El detalle de clase/relación limita sus listas y señala cuándo hay contenido omitido; la respuesta también se recorta al máximo configurado para no saturar el contexto. Los valores deben ser positivos; los límites superiores se validan en configuración. La memoria guarda extractos Markdown de la solicitud/respuesta y solo referencias a operaciones con estado confirmado `applied`; no guarda el plan bruto ni hechos de operaciones rechazadas.

El runner reclama mensajes `running` mediante lease y los recupera tras reinicio cuando el lease vence. Los leases y el ledger evitan repetir automáticamente una mutación cuyo resultado no pueda verificarse; en ese caso el mensaje termina en `failed` con una explicación segura y conserva los commits ya confirmados. El runner y el WebSocket residen en el proceso ASGI y no hay transporte distribuido para difundir eventos entre procesos: mantener un único proceso ASGI por instancia/despliegue hasta añadir y validar un bus compartido. La URL de imagen es compartible y HTTPS no la hace privada; no se elimina tras una falla de inferencia porque ya está referenciada.

## Diagnóstico de planes inválidos

El aviso `InvalidExecutionPlanException` incluye `message_id` y un `plan_reason` fijo, sin registrar prompts, respuestas del proveedor ni contenido del plan. Los fallos `planner.*` identifican problemas en la respuesta estructurada del planificador; `plan.*`, en las invariantes del plan; y `executor.*`, en el orden de ejecución. El mensaje termina en `failed` como antes.

Para investigar, correlaciona el `message_id` con el momento de fallo y usa el código: `planner.invalid_json` o `planner.not_object` indican que la respuesta no cumplió el formato JSON esperado; revisa la configuración y el comportamiento del modelo de planificación. `planner.task_limit_exceeded` indica que se superó `AGENT_MAX_PLAN_TASKS`; divide la solicitud o revisa ese límite. `plan.invalid_dependency`, `plan.cyclic_dependency`, `plan.duplicate_task_id` y los códigos de dependencias del ejecutor indican que el grafo de tareas no es válido; revisa las instrucciones y la validación del planificador. Los demás códigos señalan el campo o grupo de campos que incumplió el contrato. No reintentes automáticamente mutaciones que ya puedan haberse confirmado; consulta el estado y ledger antes de decidir cómo continuar.

## Optimización y Composición del Sistema de Prompts (`043-prompt-system-optimization`)

El módulo del asistente admite composición modular de instrucciones de sistema orientadas a reducir el consumo de tokens y maximizar el aprovechamiento de la ventana de contexto sin sacrificar seguridad, precisión de relaciones ni capacidades visuales o de continuidad.

### Variantes de Configuración

La variante activa se define en `app/core/config.py` mediante la propiedad `AGENT_PROMPT_VARIANT`:

- `AGENT_PROMPT_VARIANT="legacy"` (**Predeterminado**): Emplea las cadenas de prompts monolíticas originales re-exportadas en `agent_prompts.py`. Garantiza 100% de retrocompatibilidad y retorno seguro e instantáneo ante cualquier divergencia.
- `AGENT_PROMPT_VARIANT="modular"`: Emplea el catálogo canónico (`PromptCatalog`) y el compositor determinista puro (`PromptComposer`). Compone dinámicamente las políticas aplicables según la fase (`planning`, `execution`, `synthesis`, `vision_query`, etc.) y las herramientas o evidencias activas, excluyendo reglas irrelevantes en flujos simples.

La alternancia entre variantes es puramente de configuración en tiempo de despliegue, sin requerir migraciones de base de datos ni modificaciones de contrato público HTTP/WebSocket.

### Criterios Formales de Promoción

La promoción de `modular` a variante predeterminada en entornos de producción exige el cumplimiento simultáneo y verificable de los siguientes criterios:

1. **SC-001 (Seguridad y Autorización)**: 100% de escenarios de autenticación, límites de proyecto, inyección y comandos destructivos permanecen estrictamente protegidos.
2. **SC-004 (Políticas Especializadas)**: 100% de los flujos de relaciones (asociación con cardinalidades obligatorias, estructurales sin cardinalidades), visuales y continuidad conversacional reciente incorporan sus módulos especializados.
3. **SC-002 (Equivalencia Global)**: $\ge 95\%$ de equivalencia conductual global contra la línea base histórica en el corpus canónico de calidad (`prompt_quality_corpus.json`).
4. **SC-003 (Eficiencia en Tareas Simples)**: $\ge 30\%$ de reducción en tokens de instrucciones en tareas textuales simples (creación básica, consultas o aclaraciones).
5. **Cero Inferencias Añadidas**: La selección y composición de políticas es 100% determinista y en memoria; queda prohibido utilizar routers de IA o clasificadores semánticos adicionales.
6. **Cero Regresiones Reproducibles**: Ningún escenario del corpus puede presentar degradación no justificada.

### Verificación y Evaluación

Para validar y generar el informe de calidad previo a la activación:

```bash
cd application/server
./venv/bin/python scripts/evaluate_prompt_quality.py \
  --variant both \
  --corpus tests/modules/assistant/fixtures/prompt_quality_corpus.json \
  --output ../../specs/043-prompt-system-optimization/evaluation_report.json
```

Si la evaluación resulta en `is_promotable: true` y todos los umbrales se cumplen, se puede establecer con seguridad `AGENT_PROMPT_VARIANT="modular"` en las variables de entorno.

## Fallo rápido ante conflictos de dominio (`044-agent-fast-failure`)

El asistente detecta conflictos de dominio definitivos ocurridos durante la ejecución de herramientas de consulta o mutación del diagrama, interrumpiendo de inmediato el plan y finalizando la solicitud con estado `failed` y una respuesta en Markdown determinista y cordial en español, sin emitir nuevas llamadas al modelo de IA, herramientas adicionales ni resúmenes/síntesis.

### Categorías de Fallo Soportadas

1. **`class_not_found`**: La clase requerida no existe o ya no está disponible en el diagrama (`DiagramClassNotFoundException`).
2. **`attribute_not_found`**: El atributo solicitado no existe en la clase indicada (`DiagramAttributeNotFoundException`).
3. **`relation_not_found`**: La relación indicada no existe en el diagrama (`DiagramRelationNotFoundException`).
4. **`incompatible_diagram_state`**: El estado del diagrama impide la operación solicitada (conflictos de nombres/IDs existentes, restricciones de llaves primarias/foráneas, clases puente, generalizaciones duplicadas, cardinalidades incompatibles, lienzo bloqueado concurrentemente).
5. **`generic_domain_conflict`**: Cualquier otro conflicto de negocio originado estrictamente en el dominio de diagramas (`DomainException`).

### Garantías de Parada e Invariantes

- **Corte Estricto de Recursos**: Al detectar el primer error de dominio, se interrumpen de inmediato las llamadas restantes del lote actual y se bloquean todas las tareas pendientes (descendientes e independientes).
- **Cero Inferencias Posteriores**: Se omiten por completo `_synthesize` y `_safe_failure_summary`. El modelo Qwen no recibe nuevas solicitudes de inferencia para ese mensaje.
- **Preservación de Commits Previos**: Las operaciones confirmadas y aplicadas anteriormente en la misma solicitud se conservan intactas en la base de datos y en el `operation_ledger`; no se realiza reversión automática.
- **Respuesta Segura y Determinista**: La respuesta Markdown se genera localmente mediante plantillas predefinidas en español; incluye advertencia explícita de conservación de cambios si los hubo y orienta a revisar el diagrama antes de reintentar. Se excluyen rigurosamente identificadores técnicos (UUIDs), sentencias SQL, trazas de pila y prompts.
- **Precedencia de Cancelación**: La cancelación por parte del usuario siempre prevalece si ocurre de forma concurrente; el fallo terminal jamás sobreescribe un mensaje ya cancelado.
- **Aislamiento de Cola**: La finalización del mensaje libera slots y leases, permitiendo que los siguientes mensajes en cola se procesen normalmente sin interferencias.

### Exclusiones Estrictas de Alcance

Permanecen en sus rutas existentes y jamás ingresan a la ruta de fallo terminal de dominio:
- Errores de argumentos de herramientas (`AgentToolArgumentsException`) y ambigüedad de clases (`AgentAmbiguousClassException`).
- Fallos del proveedor de IA (`AiProviderError`, `AiProviderUnavailableException`).
- Fallos de infraestructura y persistencia (`AgentMessagePersistenceException`, `SQLAlchemyError`).
- Errores de timeout (`TimeoutError`) y límite de tool calls (`AgentToolLimitException`).
- Errores de permisos/autorización (`DiagramWriteForbiddenException`, `ProjectNotFoundException`).

### Comandos de Validación

Ejecutar desde `application/server/`:

```bash
# Suite focalizada de fallo terminal:
./venv/bin/pytest tests/modules/assistant/test_terminal_failure.py tests/modules/assistant/test_plan_executor.py tests/modules/assistant/test_process_agent_message.py tests/modules/assistant/test_agent_realtime_integration.py -q

# Suite completa del módulo de asistente:
./venv/bin/pytest tests/modules/assistant -q
```

## Resultados parciales y reintento de tareas (`045-retry-failed-tasks`)

Sustituye la parada global indiscriminada de `044` permitiendo que las tareas independientes de un plan continúen ante conflictos de dominio localizados en una rama. El resultado final distingue el éxito parcial y permite reintentar únicamente el trabajo pendiente.

### Semántica de Estado Terminal `partial`

- **Transición**: Un mensaje termina en estado persistido `partial` (`AgentMessageStatus.PARTIAL`) cuando al menos una tarea del plan completó y aplicó cambios confirmados, y al menos una tarea falló o fue bloqueada por un conflicto de dominio.
- **Liberación de Cola**: Un mensaje `partial` es terminal a efectos de cola y bloqueos activos; libera inmediatamente la cola del usuario/proyecto (`active` retorna `None`).
- **Resumen Seguro y Determinista**: La respuesta Markdown se compone localmente a partir del ledger y el estado del DAG sin invocar al proveedor de IA para explicar errores:
  ```markdown
  Se completó 1 tarea y quedó 1 pendiente.

  **Cambios aplicados:**
  - Se creó clase **Cliente** (creada).

  **Tareas no completadas:**
  - Añadir detalle: la clase requerida ya no está disponible en el diagrama.

  Revisa el diagrama y pide reintentar.
  ```

### Reintento Residual Sin Duplicación

- **Plan Residual (`ResidualPlanBuilder`)**: Al reintentar, se excluyen estrictamente las tareas completadas y operaciones ya aplicadas (`status: applied`).
- **Resolución de Dependencias**: Las dependencias hacia tareas aplicadas se marcan como satisfechas; solo subsisten dependencias entre tareas no completadas.
- **Trazabilidad de Intentos**: Cada nuevo intento se materializa como un mensaje separado e inmutable, vinculado a `source_plan_message_id` y `root_message_id`. Los intentos previos permanecen inalterados en la base de datos.
- **Reclamo Atómico y Concurrencia**: `AgentContinuation` usa control de versión optimista (CAS) en `claim_atomic` para evitar que peticiones concurrentes o duplicadas reintenten el mismo residuo simultáneamente.

### Rutas con Parada Global Innegociable

Conservan la detención global inmediata del plan sin permitir continuación de tareas independientes:
1. **Límite de tiempo / Timeout** (`asyncio.TimeoutError`).
2. **Cancelación explícita del usuario** (`AgentMessageStatus.CANCELLED`).
3. **Fallas técnicas o caídas del proveedor de IA** (`AiProviderError`).
4. **Límites de herramientas del agente** (`AgentToolLimitException`).
5. **Operaciones inciertas (`status: uncertain`)**: La ejecución se detiene de inmediato ante cualquier operación cuyo efecto en el diagrama no haya sido verificado y reconciliado fehacientemente contra el estado real.

## Reservas efímeras de componentes del agente (`046-agent-class-reservations`)

El asistente emite reservas visuales efímeras sobre componentes del diagrama (clases, atributos y relaciones) cuando interactúa con ellos de forma concreta:

- **Modo Consulta (`query`)**: Emitido al invocar `get_diagram_element` con un ID exacto confirmado en el proyecto (para clases, atributos con su clase propietaria, y relaciones con sus clases extremas). Las búsquedas textuales o listados generales (`search_diagram_elements`) no generan reservas para evitar bloquear elementos ambiguos.
- **Modo Edición (`edit`)**: Emitido de forma anticipada antes de confirmar mutaciones en `apply_diagram_changes` con IDs reales ya resueltos. Promueve de forma irreversible una reserva previa `query` a `edit`.
- **Difusión en Tiempo Real**: Se transmiten vía WebSocket como `agent_component_reserved` (`project_id`, `message_id`, `sequence`, `component_type`, `component_id`, `activity_type`, `attribute_id`). El snapshot de sala (`presence_snapshot`) incluye las reservas activas reconciliadas con TTL seguro de 300 segundos.
- **Liberación Determinista**: Al alcanzar cualquier estado terminal (`completed`, `partial`, `failed` o `cancelled`), se emite `agent_component_reservations_released` liberando únicamente las reservas asociadas a ese `message_id`. Si otro mensaje concurrente reservó los mismos componentes, sus reservas permanecen vigentes.
- **Límites de Protección y Alcance**:
  - **Protección**: Aplica estrictamente en el cliente canvas para bloquear acciones humanas directas (renombrar clases, arrastrar nodos, añadir/editar/eliminar atributos, abrir popovers de tipo, crear conexiones o renombrar/eliminar relaciones reservadas o con extremos reservados).
  - **Límites**: En esta versión, la protección no incluye rechazo de mutaciones concurrentes a nivel de API HTTP ni exclusión mutua coordinada entre múltiples agentes autónomos paralelos.
  - **Compatibilidad**: La actividad textual del chat (`agent_message_activity`) y el evento terminal (`agent_message_finished`) conservan 100% de compatibilidad de esquema y comportamiento.




