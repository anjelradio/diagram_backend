"""Proyección de hechos comunicables, sanitización y redacción de respuestas seguras."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

ResponseType = Literal["mutation", "query", "mixed", "partial_failure", "cancelled", "clarification"]

_UUID_HEX = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_UUID_TOKEN = rf"`?{_UUID_HEX}`?"

_UUID_PATTERN = re.compile(rf"\b{_UUID_HEX}\b", re.IGNORECASE)
_THOUGHT_PATTERN = re.compile(r"<(?:thought|thinking)>.*?</(?:thought|thinking)>", re.DOTALL | re.IGNORECASE)
_PAREN_UUID_PATTERN = re.compile(
    rf"\s*\((?:el\s+)?(?:id|identificador|uuid)?\s*:?\s*{_UUID_TOKEN}\s*\)",
    re.IGNORECASE,
)
_WITH_ID_PATTERN = re.compile(
    rf"\s+(?:con\s+(?:el\s+)?)?(?:id|identificador|uuid)\s*:?\s*{_UUID_TOKEN}",
    re.IGNORECASE,
)
_BACKTICKED_UUID_PATTERN = re.compile(rf"`{_UUID_HEX}`", re.IGNORECASE)
_EMPTY_PARENS_PATTERN = re.compile(r"\s*\(\s*(?:id\s*:?\s*|identificador\s*:?\s*)?\)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CommunicableFact:
    result_type: str  # confirmed_change | query_answer | pending | failed | cancelled | clarification
    entity_type: str  # class | attribute | relation | query | general
    entity_name: str
    action: str  # created | updated | deleted | answered | blocked | failed | cancelled | clarify
    details: str = ""


def convert_markdown_tables_to_lists(text: str) -> str:
    """Convierte cualquier tabla Markdown (| col | col |) en texto limpio con títulos y listas con viñetas.
    Garantiza que la IA nunca devuelva tablas con filas y columnas tabulares.
    """
    if "|" not in text:
        return text

    lines = text.split("\n")
    output_lines: list[str] = []
    i = 0
    n = len(lines)

    def is_table_row(line: str) -> bool:
        s = line.strip()
        return s.startswith("|") and s.endswith("|") and s.count("|") >= 2

    def is_delimiter_row(line: str) -> bool:
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            return False
        cells = [c.strip() for c in s[1:-1].split("|")]
        return len(cells) >= 1 and all(bool(re.match(r"^:?-{2,}:?$", c)) for c in cells if c)

    def parse_cells(line: str) -> list[str]:
        s = line.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        return [c.strip() for c in s.split("|")]

    while i < n:
        line = lines[i]
        # Detectar cabecera seguida de fila delimitadora
        if (
            i + 1 < n
            and is_table_row(line)
            and is_delimiter_row(lines[i + 1])
        ):
            headers = parse_cells(line)
            i += 2  # Saltar cabecera y separador

            data_rows: list[list[str]] = []
            while i < n and is_table_row(lines[i]):
                data_rows.append(parse_cells(lines[i]))
                i += 1

            # Convertir tabla a formato de viñetas estructuradas
            converted_items: list[str] = []
            for row in data_rows:
                if not row or not any(row):
                    continue
                first_cell = row[0]
                if len(headers) == 2 and len(row) >= 2:
                    k = first_cell.strip("* ")
                    v = row[1]
                    converted_items.append(f"- **{k}**: {v}")
                elif len(headers) > 2 and len(row) >= 2:
                    k = first_cell.strip("* ")
                    converted_items.append(f"- **{k}**:")
                    for col_idx in range(1, min(len(headers), len(row))):
                        col_header = headers[col_idx].strip("* ")
                        val = row[col_idx]
                        if val:
                            converted_items.append(f"  - **{col_header}**: {val}")
                else:
                    item_str = " - ".join(c for c in row if c)
                    converted_items.append(f"- {item_str}")

            if converted_items:
                output_lines.extend(converted_items)
            continue

        output_lines.append(line)
        i += 1

    return "\n".join(output_lines)


def sanitize_markdown_response(text: str) -> str:
    """Limpia el texto Markdown eliminando razonamiento privado, UUIDs internos y tablas."""
    if not text:
        return ""
    # 1. Remover etiquetas de pensamiento interno
    cleaned = _THOUGHT_PATTERN.sub("", text).strip()
    # 2. Convertir cualquier tabla Markdown a listas con viñetas (prohibidas tablas en UI)
    cleaned = convert_markdown_tables_to_lists(cleaned)
    # 3. Remover referencias parentizadas a UUIDs (ej. " (ID: `uuid`)" o " (id: uuid)")
    cleaned = _PAREN_UUID_PATTERN.sub("", cleaned)
    # 4. Remover frases con ID (ej. " con ID `uuid`" o " con el ID: uuid")
    cleaned = _WITH_ID_PATTERN.sub("", cleaned)
    # 5. Remover cualquier UUID entre backticks o aislado restante
    cleaned = _BACKTICKED_UUID_PATTERN.sub("", cleaned)
    cleaned = _UUID_PATTERN.sub("", cleaned).strip()
    # 6. Limpiar paréntesis vacíos dejados por remociones
    cleaned = _EMPTY_PARENS_PATTERN.sub("", cleaned)
    # 7. Limpiar espacios y puntuación anómala dejada por remociones
    cleaned = re.sub(r"  +", " ", cleaned)
    cleaned = re.sub(r" \.", ".", cleaned)
    cleaned = re.sub(r" ,", ",", cleaned)
    return cleaned.strip()


def _extract_clean_name(ref: dict[str, Any], task: dict[str, Any] | None) -> str:
    """Extrae un nombre de entidad legible para el usuario, sin UUIDs ni oraciones completas."""
    name = ref.get("name")
    if name and not _UUID_PATTERN.search(str(name)):
        return str(name)
    if task:
        obj = str(task.get("objective", ""))
        cleaned = _UUID_PATTERN.sub("", obj).strip()
        # Si contiene nombre entre comillas (ej. 'Tarea' o "Tarea")
        quote_match = re.search(r"['\"]([^'\"]+)['\"]", cleaned)
        if quote_match and len(quote_match.group(1).strip()) > 1:
            return quote_match.group(1).strip()
        # Si el objetivo expresa una relación entre dos entidades (ej. "entre Factura y DetalleFactura")
        rel_match = re.search(
            r"entre\s+(?:la\s+clase\s+)?([A-Za-z0-9_]+)\s+y\s+(?:la\s+clase\s+)?([A-Za-z0-9_]+)",
            cleaned,
            re.IGNORECASE,
        )
        if rel_match:
            return f"{rel_match.group(1)} ↔ {rel_match.group(2)}"

        match = re.search(r"(?:clase|atributo|relación|entidad)\s+([A-Za-z0-9_]+)", cleaned, re.IGNORECASE)
        if match and len(match.group(1)) > 1:
            return match.group(1)

        end_match = re.search(r"\b([A-Za-z0-9_]+)[.\s]*$", cleaned)
        if end_match and len(end_match.group(1)) > 1:
            word = end_match.group(1)
            if word.lower() not in {"creada", "creado", "modificada", "modificado", "eliminada", "eliminado", "diagrama", "proyecto", "notion", "tarea", "tareas", "done", "pendiente"}:
                return word

    ref_id = ref.get("id")
    if ref_id and not _UUID_PATTERN.search(str(ref_id)):
        return str(ref_id)
    return "elemento"


def extract_communicable_facts(
    ledger_entries: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
    task_results: list[dict[str, Any]] | None = None,
    cancelled: bool = False,
) -> list[CommunicableFact]:
    """Extrae hechos comunicables únicamente desde resultados confirmados y estado de tareas."""
    facts: list[CommunicableFact] = []

    if cancelled:
        facts.append(
            CommunicableFact(
                result_type="cancelled",
                entity_type="general",
                entity_name="Operación",
                action="cancelled",
                details="Operación cancelada por el usuario antes de completarse.",
            )
        )
        return facts

    tasks_by_id = {t.get("id"): t for t in (tasks or []) if isinstance(t, dict) and t.get("id")}

    # 1. Hechos desde el ledger (operaciones confirmadas/aplicadas)
    handled_task_ids: set[str] = set()
    for entry in ledger_entries or []:
        status = entry.get("status")
        if status != "applied":
            continue
        task_id = entry.get("task_id")
        if task_id:
            handled_task_ids.add(str(task_id))
        task = tasks_by_id.get(task_id) if task_id else None
        kind = entry.get("action_kind") or ""
        refs = entry.get("entity_refs") or []
        derived_effects = entry.get("derived_effects") or []
        derived_attr_ids = {
            str(eff.get("id"))
            for eff in derived_effects
            if isinstance(eff, dict) and eff.get("type") in {"attribute", "fk"}
        }

        if not refs:
            ent_name = _extract_clean_name({}, task)
            is_neon_entry = "NEON" in kind or (task and "neon" in str(task.get("objective", "")).lower())
            if is_neon_entry:
                ent_type = "neon_sync"
                ent_name = "Base de datos Neon"
                action = "updated"
                details = str(entry.get("message") or "Base de datos Neon sincronizada correctamente.")
                facts.append(
                    CommunicableFact(
                        result_type="confirmed_change",
                        entity_type=ent_type,
                        entity_name=ent_name,
                        action=action,
                        details=details,
                    )
                )
                continue
            is_notion_entry = "NOTION" in kind or (task and ("notion" in str(task.get("objective", "")).lower() or task.get("notion_task_id")))
            ent_type = "notion_task" if is_notion_entry else ("clase" if task and "clase" in str(task.get("objective", "")).lower() else "elemento")
            action = "created"
            if "UPDATE" in kind or "RENAME" in kind:
                action = "updated"
            elif "DELETE" in kind:
                action = "deleted"
            details = f"{ent_type.capitalize()} {ent_name} {action}."
            if is_notion_entry and (task and str(task.get("id", "")).startswith("close-notion-")):
                details = f"Tarea de Notion '{ent_name}' marcada como Done."
            facts.append(
                CommunicableFact(
                    result_type="confirmed_change",
                    entity_type=ent_type,
                    entity_name=ent_name,
                    action=action,
                    details=details,
                )
            )
            continue

        for ref in refs:
            ent_type = ref.get("type", "entity")
            if ref.get("kind") == "NOTION_TASK" or "NOTION" in kind:
                ent_type = "notion_task"
            ref_id = str(ref.get("id") or "")
            # Omitir atributos que son efectos secundarios de relaciones o creación interna de clase sin nombre explícito
            if ent_type in {"attribute", "atributo"} and (
                kind == "CREATE_RELATION"
                or ref_id in derived_attr_ids
                or (kind == "CREATE_CLASS" and not ref.get("name"))
            ):
                continue

            raw_ref = dict(ref)
            if not raw_ref.get("name") and entry.get("target_name") and ent_type in {"class", "clase"}:
                raw_ref["name"] = entry.get("target_name")
            ent_name = _extract_clean_name(raw_ref, task)

            action = "created"
            if "UPDATE" in kind or "RENAME" in kind:
                action = "updated"
            elif "DELETE" in kind:
                action = "deleted"

            details = f"{ent_type.capitalize()} {ent_name} {action}."
            if ent_type == "notion_task" and (task and str(task.get("id", "")).startswith("close-notion-")):
                details = f"Tarea de Notion '{ent_name}' marcada como Done."

            facts.append(
                CommunicableFact(
                    result_type="confirmed_change",
                    entity_type=ent_type,
                    entity_name=ent_name,
                    action=action,
                    details=details,
                )
            )

    # 2. Respaldo para tareas de mutación completadas sin entradas separadas en el ledger
    for task in tasks or []:
        if isinstance(task, dict) and task.get("status") == "completed" and task.get("kind") == "mutation":
            task_id = str(task.get("id", ""))
            if task_id not in handled_task_ids:
                handled_task_ids.add(task_id)
                obj = str(task.get("objective", ""))
                ent_name = _extract_clean_name({}, task)
                is_notion_task = bool(task.get("notion_task_id") or task_id.startswith("close-notion-") or "notion" in obj.lower())
                action = "created"
                if any(w in obj.lower() for w in ("modifica", "actualiza", "renombra", "edita", "done", "marcar")):
                    action = "updated"
                elif any(w in obj.lower() for w in ("elimina", "borra", "quita")):
                    action = "deleted"

                ent_type = "notion_task" if is_notion_task else ("clase" if "clase" in obj.lower() else "elemento")
                details = f"Completado: {obj}"
                if task_id.startswith("close-notion-"):
                    details = f"Tarea de Notion '{ent_name}' marcada como Done."

                facts.append(
                    CommunicableFact(
                        result_type="confirmed_change",
                        entity_type=ent_type,
                        entity_name=ent_name,
                        action=action,
                        details=details,
                    )
                )

    # 3. Hechos desde tareas fallidas o bloqueadas
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        task_status = task.get("status")
        objective = task.get("objective", "Tarea")
        if task_status == "failed":
            facts.append(
                CommunicableFact(
                    result_type="failed",
                    entity_type="task",
                    entity_name=objective,
                    action="failed",
                    details=f"No se pudo completar: {objective}.",
                )
            )
        elif task_status == "blocked":
            facts.append(
                CommunicableFact(
                    result_type="pending",
                    entity_type="task",
                    entity_name=objective,
                    action="blocked",
                    details=f"Pendiente (bloqueada por error previo): {objective}.",
                )
            )

    # 4. Hechos desde resultados de consulta
    for res in task_results or []:
        if isinstance(res, dict):
            if res.get("status") == "query_answer":
                facts.append(
                    CommunicableFact(
                        result_type="query_answer",
                        entity_type="query",
                        entity_name="Consulta",
                        action="answered",
                        details=str(res.get("answer", "")),
                    )
                )
            elif res.get("status") == "completed":
                task_id = res.get("task_id")
                task = tasks_by_id.get(task_id) if task_id else None
                if task and task.get("kind") == "query" and res.get("result"):
                    facts.append(
                        CommunicableFact(
                            result_type="query_answer",
                            entity_type="query",
                            entity_name="Consulta",
                            action="answered",
                            details=str(res.get("result", "")),
                        )
                    )

    return facts


def determine_response_type(
    facts: list[CommunicableFact],
    has_failed_or_blocked: bool = False,
    cancelled: bool = False,
) -> ResponseType:
    """Determina el tipo de estructura de respuesta según los hechos confirmados."""
    if cancelled:
        return "cancelled"
    if has_failed_or_blocked:
        return "partial_failure"

    has_mutation = any(f.result_type == "confirmed_change" for f in facts)
    has_query = any(f.result_type == "query_answer" for f in facts)

    if has_mutation and has_query:
        return "mixed"
    if has_mutation:
        return "mutation"
    if has_query:
        return "query"
    return "query"


def format_deterministic_response(facts: list[CommunicableFact], response_type: ResponseType) -> str:
    """Genera una respuesta en Markdown cordial, clara y estructurada según el tipo de resultado."""
    if response_type == "cancelled":
        return "La operación fue cancelada. No se aplicaron cambios adicionales al diagrama."

    if response_type == "clarification":
        clarifications = [f for f in facts if f.result_type == "clarification"]
        if clarifications:
            details = [c.details for c in clarifications if c.details]
            if details:
                return "Por favor aclara tu solicitud (es necesario aclarar los siguientes puntos):\n" + "\n".join(f"- {d}" for d in details)
        return "Por favor proporciona más detalles para aclarar la solicitud antes de continuar."

    def _format_item(f: CommunicableFact) -> str:
        if f.entity_type in {"neon_sync", "neon_database", "neon"}:
            return f"- {f.details}"

        if f.entity_type in {"notion_task", "tarea_notion", "tarea de notion"}:
            if f.action == "created":
                return f"- Se creó la tarea de Notion **{f.entity_name}**."
            if f.action == "updated":
                if "done" in f.details.lower():
                    return f"- Se marcó la tarea de Notion **{f.entity_name}** como Done."
                return f"- Se actualizó la tarea de Notion **{f.entity_name}**."
            if f.action == "deleted":
                return f"- Se eliminó la tarea de Notion **{f.entity_name}**."
            return f"- Tarea de Notion **{f.entity_name}**: {f.action}."

        ent_type_str = "clase" if f.entity_type in {"class", "clase"} else "atributo" if f.entity_type in {"attribute", "atributo"} else "relación" if f.entity_type in {"relation", "relación"} else "elemento"
        if f.action == "created":
            participle = "creada" if ent_type_str in {"clase", "relación"} else "creado"
            return f"- Se creó {ent_type_str} **{f.entity_name}** ({participle})."
        if f.action == "updated":
            participle = "actualizada" if ent_type_str in {"clase", "relación"} else "actualizado"
            return f"- Se actualizó {ent_type_str} **{f.entity_name}** ({participle})."
        if f.action == "deleted":
            participle = "eliminada" if ent_type_str in {"clase", "relación"} else "eliminado"
            return f"- Se eliminó {ent_type_str} **{f.entity_name}** ({participle})."
        return f"- {ent_type_str.capitalize()} **{f.entity_name}**: {f.action}."

    def _dedupe_facts(items: list[CommunicableFact]) -> list[CommunicableFact]:
        seen: set[tuple[str, str, str]] = set()
        deduped: list[CommunicableFact] = []
        for item in items:
            key = (item.entity_type, item.entity_name, item.action)
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped

    if response_type == "partial_failure":
        confirmed = _dedupe_facts([f for f in facts if f.result_type == "confirmed_change"])
        failed = [f for f in facts if f.result_type in {"failed", "pending"}]

        lines = ["No pude completar todas las tareas solicitadas. Aquí tienes el detalle:"]
        if confirmed:
            lines.append("\n**Cambios aplicados:**")
            for f in confirmed:
                lines.append(_format_item(f))
        if failed:
            lines.append("\n**Tareas no completadas o pendientes:**")
            for f in failed:
                lines.append(f"- {f.details}")
        lines.append("\nPuedes revisar el diagrama antes de continuar.")
        return "\n".join(lines)

    if response_type == "mutation":
        confirmed = _dedupe_facts([f for f in facts if f.result_type == "confirmed_change"])
        if not confirmed:
            return "Listo. No fue necesario realizar cambios en el diagrama."
        lines = ["¡Listo! He aplicado los siguientes cambios en el diagrama:"]
        for f in confirmed:
            lines.append(_format_item(f))
        return "\n".join(lines)

    if response_type == "mixed":
        confirmed = _dedupe_facts([f for f in facts if f.result_type == "confirmed_change"])
        queries = [f for f in facts if f.result_type == "query_answer"]

        lines = ["¡Con gusto! He procesado tu solicitud:"]
        if confirmed:
            lines.append("\n**Cambios confirmados:**")
            for f in confirmed:
                lines.append(_format_item(f))
        if queries:
            lines.append("\n**Respuesta a tu consulta:**")
            for q in queries:
                lines.append(q.details)
        return "\n".join(lines)

    if response_type == "query":
        queries = [f for f in facts if f.result_type == "query_answer"]
        if queries:
            return "\n\n".join(q.details for q in queries)
        return "He consultado el diagrama según tu solicitud."

    return "Listo. He completado tu solicitud."


def format_plan_execution_response(plan: Any) -> str:
    """Compone una respuesta Markdown determinista a partir del estado de tareas y ledger del plan."""
    from app.modules.assistant.application.services.execution.terminal_failure import (
        map_error_code_to_safe_reason,
    )

    tasks = getattr(plan, "tasks", [])
    ledger = getattr(plan, "operation_ledger", [])
    status = getattr(plan, "status", "completed")

    completed_tasks = [t for t in tasks if t.get("status") == "completed"]
    failed_or_blocked = [t for t in tasks if t.get("status") in {"failed", "blocked"}]
    pending_tasks = [t for t in tasks if t.get("status") == "pending"]
    uncompleted = failed_or_blocked + pending_tasks

    # Extraer cambios confirmados (solo applied en el ledger)
    confirmed_facts: list[CommunicableFact] = []
    seen_confirmed: set[tuple[str, str, str]] = set()
    tasks_by_id = {t.get("id"): t for t in tasks if isinstance(t, dict) and t.get("id")}

    for entry in ledger:
        if entry.get("status") != "applied":
            continue
        kind = str(entry.get("action_kind") or "")
        task_id = entry.get("task_id")
        task = tasks_by_id.get(task_id) if task_id else None
        action = "created"
        if "UPDATE" in kind or "RENAME" in kind:
            action = "updated"
        elif "DELETE" in kind:
            action = "deleted"

        derived_effects = entry.get("derived_effects") or []
        derived_attr_ids = {
            str(eff.get("id"))
            for eff in derived_effects
            if isinstance(eff, dict) and eff.get("type") in {"attribute", "fk"}
        }

        for ref in entry.get("entity_refs", []):
            ent_type = ref.get("type", "elemento")
            ref_id = str(ref.get("id") or "")
            if ent_type in {"attribute", "atributo"} and (
                kind == "CREATE_RELATION"
                or ref_id in derived_attr_ids
                or (kind == "CREATE_CLASS" and not ref.get("name"))
            ):
                continue
            raw_ref = dict(ref)
            if not raw_ref.get("name") and entry.get("target_name") and ent_type in {"class", "clase"}:
                raw_ref["name"] = entry.get("target_name")
            ent_name = str(raw_ref.get("name") or _extract_clean_name(raw_ref, task))
            if ent_name != "elemento" and not _UUID_PATTERN.search(ent_name):
                key = (ent_type, ent_name, action)
                if key not in seen_confirmed:
                    seen_confirmed.add(key)
                    confirmed_facts.append(
                        CommunicableFact(
                            result_type="confirmed_change",
                            entity_type=ent_type,
                            entity_name=ent_name,
                            action=action,
                        )
                    )

    def _format_item(f: CommunicableFact) -> str:
        if f.entity_type in {"neon_sync", "neon_database", "neon"}:
            return f"- {f.details}"

        ent_type_str = (
            "clase"
            if f.entity_type in {"class", "clase"}
            else "atributo"
            if f.entity_type in {"attribute", "atributo"}
            else "relación"
            if f.entity_type in {"relation", "relación"}
            else "elemento"
        )
        if f.action == "created":
            participle = "creada" if ent_type_str in {"clase", "relación"} else "creado"
            return f"- Se creó {ent_type_str} **{f.entity_name}** ({participle})."
        if f.action == "updated":
            participle = "actualizada" if ent_type_str in {"clase", "relación"} else "actualizado"
            return f"- Se actualizó {ent_type_str} **{f.entity_name}** ({participle})."
        if f.action == "deleted":
            participle = "eliminada" if ent_type_str in {"clase", "relación"} else "eliminado"
            return f"- Se eliminó {ent_type_str} **{f.entity_name}** ({participle})."
        return f"- {ent_type_str.capitalize()} **{f.entity_name}**: {f.action}."

    lines: list[str] = []

    if status == "partial":
        c_count = len(completed_tasks)
        u_count = len(uncompleted)
        c_str = f"{c_count} tarea" if c_count == 1 else f"{c_count} tareas"
        u_str = f"{u_count} pendiente" if u_count == 1 else f"{u_count} pendientes"
        lines.append(f"Se completó {c_str} y quedó {u_str}.")

        if confirmed_facts:
            lines.append("\n**Cambios aplicados:**")
            for f in confirmed_facts:
                lines.append(_format_item(f))

        if uncompleted:
            lines.append("\n**Tareas no completadas:**")
            for t in uncompleted:
                obj = sanitize_markdown_response(t.get("objective", "Tarea"))
                reason = map_error_code_to_safe_reason(
                    t.get("error_code"), t.get("failure_reason")
                )
                lines.append(f"- {obj}: {reason}.")

        missing_class = None
        for t in uncompleted:
            code = (t.get("error_code") or "").lower()
            if "class_not_found" in code:
                target_cls = t.get("target_class")
                if not target_cls:
                    reason = t.get("failure_reason") or ""
                    m = re.search(r"\*\*([^*]+)\*\*", reason)
                    if m:
                        target_cls = m.group(1)
                if target_cls:
                    missing_class = target_cls
                    break

        if missing_class:
            lines.append(f"\n¿Deseas que cree la clase **{missing_class}** y continúe con las tareas pendientes? (puedes responder 'sí' o 'créala').")
        else:
            lines.append("\nRevisa el diagrama. ¿Deseas que intente retomar lo que quedó pendiente? (puedes responder 'sí' o 'continúa').")

    elif status == "failed":
        missing_class = None
        for t in uncompleted:
            code = (t.get("error_code") or "").lower()
            if "class_not_found" in code:
                target_cls = t.get("target_class")
                if not target_cls:
                    reason = t.get("failure_reason") or ""
                    m = re.search(r"\*\*([^*]+)\*\*", reason)
                    if m:
                        target_cls = m.group(1)
                if target_cls:
                    missing_class = target_cls
                    break

        lines.append(
            "No pude completar las tareas solicitadas debido a conflictos en el diagrama."
        )
        if confirmed_facts:
            lines.append("\n**Cambios aplicados:**")
            for f in confirmed_facts:
                lines.append(_format_item(f))
        if uncompleted:
            lines.append("\n**Tareas no completadas:**")
            for t in uncompleted:
                obj = sanitize_markdown_response(t.get("objective", "Tarea"))
                reason = map_error_code_to_safe_reason(
                    t.get("error_code"), t.get("failure_reason")
                )
                lines.append(f"- {obj}: {reason}.")
        lines.append("\nTe sugerimos revisar el diagrama antes de volver a intentarlo.")
        if missing_class:
            lines.append(f"\n¿Deseas que cree la clase **{missing_class}** primero para poder continuar? (puedes responder 'sí' o 'créala').")

    else:
        if confirmed_facts:
            lines.append("¡Listo! He aplicado los siguientes cambios en el diagrama:")
            for f in confirmed_facts:
                lines.append(_format_item(f))
        else:
            lines.append("¡Listo! Todas las tareas se completaron con éxito.")

    return sanitize_markdown_response("\n".join(lines))

