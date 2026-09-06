"""
app/core/errors

Manejo centralizado de excepciones y errores HTTP de la API.
"""

from app.core.errors.exceptions import APIHTTPException
from app.core.errors.handlers import format_error, setup_exception_handlers

__all__ = ["APIHTTPException", "setup_exception_handlers", "format_error"]
