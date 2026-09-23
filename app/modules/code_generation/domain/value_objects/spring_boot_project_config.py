from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SpringBootProjectConfig:
    """Configuración de generación para un proyecto Spring Boot."""

    project_name: str
    artifact_id: str = "backend-service"
    group_id: str = "app"
    package_name: str = "app.backend"
    java_version: str = "17"
    spring_boot_version: str = "3.3.4"
    database_name: str = "app_db"
    database_username: str = "postgres"
    database_password: str = "postgres"
    server_port: int = 8080


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    """Representa un archivo generado listo para ser empaquetado en el ZIP."""

    relative_path: str
    content: str | bytes
    is_executable: bool = False
