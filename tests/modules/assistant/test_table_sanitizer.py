"""Pruebas unitarias para la erradicación y conversión de tablas Markdown."""

import pytest
from app.modules.assistant.application.services.execution.agent_response import (
    convert_markdown_tables_to_lists,
    sanitize_markdown_response,
)


def test_convert_two_column_table():
    md = """### Atributos

| Campo | Tipo |
|---|---|
| nombre | TEXT |
| total | DECIMAL |
"""
    result = convert_markdown_tables_to_lists(md)
    assert "|" not in result
    assert "- **nombre**: TEXT" in result
    assert "- **total**: DECIMAL" in result


def test_convert_multi_column_table():
    md = """### Diferencias con la Agregación

| Característica | Composición | Agregación |
|---|---|---|
| **Dependencia** | Fuerte: la parte no existe sin el todo | Débil: la parte puede existir independientemente |
| **Borrado** | En cascada: al borrar el todo, se borran las partes | Independiente: al borrar el todo, las partes permanecen |
"""
    result = convert_markdown_tables_to_lists(md)
    assert "|" not in result
    assert "- **Dependencia**:" in result
    assert "  - **Composición**: Fuerte: la parte no existe sin el todo" in result
    assert "  - **Agregación**: Débil: la parte puede existir independientemente" in result
    assert "- **Borrado**:" in result


def test_convert_preserves_plain_text_and_headings():
    md = """# Encabezado 1
Este es un párrafo normal.

### Diferencias
- Elemento lista 1
- Elemento lista 2
"""
    result = convert_markdown_tables_to_lists(md)
    assert result == md


def test_sanitize_markdown_response_strips_tables_and_uuids():
    md = """La relación recomendada para la clase Pedido (ID: `11111111-2222-3333-4444-555555555555`) es:

| Opción | Motivo |
|---|---|
| Composición | Ciclo de vida |
"""
    cleaned = sanitize_markdown_response(md)
    assert "11111111-2222-3333-4444-555555555555" not in cleaned
    assert "|" not in cleaned
    assert "- **Composición**: Ciclo de vida" in cleaned
