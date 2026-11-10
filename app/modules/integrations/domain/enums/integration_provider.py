from enum import Enum


class IntegrationProvider(str, Enum):
    """Proveedores externos soportados por el módulo de integraciones MCP."""

    NOTION = "NOTION"
    NEON = "NEON"
