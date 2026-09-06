from collections.abc import Mapping

from fastapi import HTTPException


class APIHTTPException(HTTPException):
    """Excepción HTTP con un código de error estable para los clientes de la API."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.code = code
        super().__init__(
            status_code=status_code,
            detail=message,
            headers=dict(headers) if headers is not None else None,
        )
