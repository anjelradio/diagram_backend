# app/shared/infrastructure/db/models.py
#
# ============================================================
# REGISTRY CENTRAL DE MODELOS  ─  ALEMBIC LO IMPORTA AQUÍ
# ============================================================
# Cada vez que agregues un nuevo módulo con tablas SQLModel,
# importa su modelo en este archivo.  Eso es todo lo que
# necesitas para que `alembic revision --autogenerate` lo detecte.
# ============================================================

# ruff: noqa: F401

# Módulo Projects
from app.modules.projects.infrastructure.persistence.models.project_model import ProjectModel
from app.modules.projects.infrastructure.persistence.models.invitation_model import InvitationModel
from app.modules.projects.infrastructure.persistence.models.project_member_model import ProjectMemberModel
