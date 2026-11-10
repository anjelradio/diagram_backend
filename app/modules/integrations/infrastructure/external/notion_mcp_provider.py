from __future__ import annotations

import logging
from typing import Any
import httpx

from app.modules.integrations.application.ports.providers.notion_integration_provider import (
    NotionInitializedWorkspace,
    NotionIntegrationProvider,
    NotionProjectWelcomeContent,
    NotionTaskRecord,
)
from app.modules.integrations.domain.enums.notion_task_priority import (
    NotionTaskPriority,
)
from app.modules.integrations.domain.enums.notion_task_status import (
    NotionTaskStatus,
)
from app.modules.integrations.domain.exceptions import (
    NotionExternalServiceException,
    NotionInvalidCredentialsException,
    NotionTaskNotFoundException,
)

logger = logging.getLogger(__name__)
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key.strip()}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


class NotionMcpProvider(NotionIntegrationProvider):
    """Adaptador que implementa el protocolo oficial de Notion MCP / REST API v1."""

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._client = http_client

    def _get_client(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=15.0)

    def validate_api_key(
        self,
        api_key: str,
        *,
        parent_page_id: str | None = None,
    ) -> tuple[bool, str | None, str | None]:
        if not api_key or not api_key.strip():
            return False, None, None
        try:
            client = self._get_client()
            headers = _headers(api_key)
            # 1. Comprobar identidad / token
            me_resp = client.get(f"{NOTION_API_BASE}/users/me", headers=headers)
            if me_resp.status_code != 200:
                return False, None, None
            me_data = me_resp.json()
            bot_owner = me_data.get("bot", {}).get("owner", {})
            workspace_name = bot_owner.get("workspace_name")

            # 2. Si se proporcionó parent_page_id, verificar acceso
            resolved_parent_id = parent_page_id.strip() if parent_page_id and parent_page_id.strip() else None
            if resolved_parent_id:
                page_resp = client.get(f"{NOTION_API_BASE}/pages/{resolved_parent_id}", headers=headers)
                if page_resp.status_code != 200:
                    return False, None, None
                return True, resolved_parent_id, workspace_name

            # 3. Si no se dio parent_page_id, buscar páginas raíz accesibles
            search_resp = client.post(
                f"{NOTION_API_BASE}/search",
                headers=headers,
                json={"filter": {"value": "page", "property": "object"}, "page_size": 20},
            )
            if search_resp.status_code == 200:
                results = search_resp.json().get("results", [])
                # Filtrar páginas activas (no archivadas ni en papelera)
                active_pages = [
                    p for p in results
                    if not p.get("archived", False) and not p.get("in_trash", False)
                ]
                # Priorizar páginas raíz (cuyo parent no sea una base de datos)
                root_pages = [
                    p for p in active_pages
                    if p.get("parent", {}).get("type") in ("workspace", "page_id")
                ]
                selected = root_pages[0] if root_pages else (active_pages[0] if active_pages else (results[0] if results else None))
                if selected:
                    resolved_parent_id = selected["id"]

            return True, resolved_parent_id, workspace_name
        except Exception as exc:
            logger.warning("Error validando token de Notion: %s", exc)
            return False, None, None

    def initialize_project_workspace(
        self,
        *,
        api_key: str,
        parent_page_id: str,
        project_name: str,
        welcome_content: NotionProjectWelcomeContent,
    ) -> NotionInitializedWorkspace:
        client = self._get_client()
        headers = _headers(api_key)

        # Construir bloques de la página raíz
        blocks: list[dict[str, Any]] = [
            {
                "object": "block",
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"type": "text", "text": {"content": welcome_content.welcome_heading}}]
                },
            },
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"type": "text", "text": {"content": welcome_content.executive_description}}],
                    "icon": {"emoji": "📐"},
                },
            },
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "👥 Equipo de Desarrollo"}}]
                },
            },
        ]

        # Agregar miembros del equipo
        for member in welcome_content.team_members or ["Colaborador"]:
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": member}}]
                },
            })

        # Agregar catálogo de clases
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "🏛️ Estado Inicial de Clases del Diagrama"}}]
            },
        })

        if not welcome_content.diagram_classes_summary:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": "No hay clases registradas en el diagrama aún."}}]
                },
            })
        else:
            for cls_info in welcome_content.diagram_classes_summary:
                c_name = cls_info.get("name", "Clase")
                attrs = cls_info.get("attributes", [])
                attr_str = ", ".join(attrs) if attrs else "Sin atributos definidos"
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [
                            {"type": "text", "text": {"content": f"{c_name}: ", "link": None}, "annotations": {"bold": True}},
                            {"type": "text", "text": {"content": attr_str}},
                        ]
                    },
                })

        # 1. Crear página raíz
        page_payload = {
            "parent": {"page_id": parent_page_id},
            "properties": {
                "title": {
                    "title": [{"type": "text", "text": {"content": project_name}}]
                }
            },
            "children": blocks[:95],  # Notion permite máx 100 bloques por llamada
        }

        resp = client.post(f"{NOTION_API_BASE}/pages", headers=headers, json=page_payload)
        if resp.status_code not in {200, 201}:
            logger.error("Fallo al crear página en Notion: %s", resp.text)
            raise NotionExternalServiceException(f"No se pudo crear la página en Notion: {resp.text}")

        page_data = resp.json()
        root_page_id = page_data["id"]
        page_url = page_data.get("url") or f"https://www.notion.so/{root_page_id.replace('-', '')}"

        # 2. Crear base de datos hija de tareas
        db_payload = {
            "parent": {"type": "page_id", "page_id": root_page_id},
            "title": [{"type": "text", "text": {"content": "Tareas y Observaciones"}}],
            "properties": {
                "Tarea": {"title": {}},
                "Estado": {
                    "select": {
                        "options": [
                            {"name": "Pendiente", "color": "yellow"},
                            {"name": "En progreso", "color": "blue"},
                            {"name": "Done", "color": "green"},
                        ]
                    }
                },
                "Prioridad": {
                    "select": {
                        "options": [
                            {"name": "Alta", "color": "red"},
                            {"name": "Media", "color": "orange"},
                            {"name": "Baja", "color": "gray"},
                        ]
                    }
                },
                "Responsable": {"rich_text": {}},
                "Fecha": {"date": {}},
                "Descripción": {"rich_text": {}},
            },
        }

        db_resp = client.post(f"{NOTION_API_BASE}/databases", headers=headers, json=db_payload)
        if db_resp.status_code not in {200, 201}:
            logger.error("Fallo al crear base de datos en Notion: %s", db_resp.text)
            raise NotionExternalServiceException(f"No se pudo crear la base de datos de tareas en Notion: {db_resp.text}")

        db_data = db_resp.json()
        database_id = db_data["id"]

        return NotionInitializedWorkspace(
            page_id=root_page_id,
            database_id=database_id,
            page_url=page_url,
        )

    def create_task(
        self,
        *,
        api_key: str,
        database_id: str,
        title: str,
        description: str,
        assignee_name: str,
        priority: NotionTaskPriority = NotionTaskPriority.MEDIUM,
        due_date: str | None = None,
    ) -> NotionTaskRecord:
        client = self._get_client()
        headers = _headers(api_key)

        properties: dict[str, Any] = {
            "Tarea": {"title": [{"type": "text", "text": {"content": title.strip()}}]},
            "Estado": {"select": {"name": NotionTaskStatus.PENDING.value}},
            "Prioridad": {"select": {"name": priority.value}},
            "Responsable": {"rich_text": [{"type": "text", "text": {"content": assignee_name.strip()}}]},
        }
        if description and description.strip():
            properties["Descripción"] = {
                "rich_text": [{"type": "text", "text": {"content": description.strip()[:2000]}}]
            }
        if due_date and due_date.strip():
            properties["Fecha"] = {"date": {"start": due_date.strip()[:10]}}

        resp = client.post(
            f"{NOTION_API_BASE}/pages",
            headers=headers,
            json={"parent": {"database_id": database_id}, "properties": properties},
        )
        if resp.status_code not in {200, 201}:
            logger.error("Error creando tarea en Notion: %s", resp.text)
            raise NotionExternalServiceException(f"Fallo al crear tarea en Notion: {resp.text}")

        data = resp.json()
        return self._parse_page_to_task(data)

    def list_tasks(
        self,
        *,
        api_key: str,
        database_id: str,
        assignee_name: str | None = None,
        status: NotionTaskStatus | None = None,
    ) -> list[NotionTaskRecord]:
        client = self._get_client()
        headers = _headers(api_key)

        filters: list[dict[str, Any]] = []
        if assignee_name and assignee_name.strip():
            filters.append({
                "property": "Responsable",
                "rich_text": {"equals": assignee_name.strip()},
            })
        if status is not None:
            filters.append({
                "property": "Estado",
                "select": {"equals": status.value},
            })

        query_payload: dict[str, Any] = {
            "page_size": 100,
            "sorts": [{"property": "Fecha", "direction": "ascending"}],
        }
        if len(filters) == 1:
            query_payload["filter"] = filters[0]
        elif len(filters) > 1:
            query_payload["filter"] = {"and": filters}

        resp = client.post(
            f"{NOTION_API_BASE}/databases/{database_id}/query",
            headers=headers,
            json=query_payload,
        )
        if resp.status_code != 200:
            logger.error("Error consultando tareas en Notion: %s", resp.text)
            raise NotionExternalServiceException(f"Fallo al consultar tareas en Notion: {resp.text}")

        data = resp.json()
        tasks = []
        for page in data.get("results", []):
            if page.get("archived"):
                continue
            task = self._parse_page_to_task(page)
            tasks.append(task)
        return tasks

    def get_task(
        self,
        *,
        api_key: str,
        task_id: str,
    ) -> NotionTaskRecord | None:
        client = self._get_client()
        headers = _headers(api_key)
        resp = client.get(f"{NOTION_API_BASE}/pages/{task_id}", headers=headers)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise NotionExternalServiceException(f"Fallo al obtener tarea en Notion: {resp.text}")
        data = resp.json()
        if data.get("archived"):
            return None
        return self._parse_page_to_task(data)

    def update_task(
        self,
        *,
        api_key: str,
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        status: NotionTaskStatus | None = None,
        priority: NotionTaskPriority | None = None,
        due_date: str | None = None,
    ) -> NotionTaskRecord:
        client = self._get_client()
        headers = _headers(api_key)
        props: dict[str, Any] = {}
        if title is not None and title.strip():
            props["Tarea"] = {"title": [{"type": "text", "text": {"content": title.strip()}}]}
        if description is not None:
            props["Descripción"] = {
                "rich_text": [{"type": "text", "text": {"content": description.strip()[:2000]}}]
            }
        if status is not None:
            props["Estado"] = {"select": {"name": status.value}}
        if priority is not None:
            props["Prioridad"] = {"select": {"name": priority.value}}
        if due_date is not None:
            if due_date.strip():
                props["Fecha"] = {"date": {"start": due_date.strip()[:10]}}
            else:
                props["Fecha"] = {"date": None}

        resp = client.patch(
            f"{NOTION_API_BASE}/pages/{task_id}",
            headers=headers,
            json={"properties": props},
        )
        if resp.status_code == 404:
            raise NotionTaskNotFoundException()
        if resp.status_code != 200:
            raise NotionExternalServiceException(f"Fallo al actualizar tarea en Notion: {resp.text}")
        return self._parse_page_to_task(resp.json())

    def delete_task(
        self,
        *,
        api_key: str,
        task_id: str,
    ) -> bool:
        client = self._get_client()
        headers = _headers(api_key)
        resp = client.patch(
            f"{NOTION_API_BASE}/pages/{task_id}",
            headers=headers,
            json={"archived": True},
        )
        if resp.status_code == 404:
            return False
        if resp.status_code != 200:
            raise NotionExternalServiceException(f"Fallo al archivar tarea en Notion: {resp.text}")
        return True

    def _parse_page_to_task(self, page: dict[str, Any]) -> NotionTaskRecord:
        props = page.get("properties", {})
        task_id = page["id"]
        url = page.get("url")

        # Título
        title_blocks = props.get("Tarea", {}).get("title", [])
        title = "".join(b.get("plain_text", "") for b in title_blocks) or "Sin título"

        # Estado
        st_val = props.get("Estado", {}).get("select", {})
        status_name = st_val.get("name") if isinstance(st_val, dict) else None
        status = NotionTaskStatus.from_raw(status_name)

        # Prioridad
        prio_val = props.get("Prioridad", {}).get("select", {})
        prio_name = prio_val.get("name") if isinstance(prio_val, dict) else None
        priority = NotionTaskPriority.from_raw(prio_name)

        # Responsable
        resp_blocks = props.get("Responsable", {}).get("rich_text", [])
        assignee_name = "".join(b.get("plain_text", "") for b in resp_blocks).strip() or "Sin asignar"

        # Descripción
        desc_blocks = props.get("Descripción", {}).get("rich_text", [])
        description = "".join(b.get("plain_text", "") for b in desc_blocks).strip()

        # Fecha
        date_obj = props.get("Fecha", {}).get("date")
        due_date = date_obj.get("start") if isinstance(date_obj, dict) else None

        return NotionTaskRecord(
            task_id=task_id,
            title=title,
            description=description,
            status=status,
            priority=priority,
            assignee_name=assignee_name,
            due_date=due_date,
            url=url,
        )
