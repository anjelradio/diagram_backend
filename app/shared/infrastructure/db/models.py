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

# Módulo Collaboration
from app.modules.collaboration.infrastructure.persistence.models.invitation_model import InvitationModel
from app.modules.collaboration.infrastructure.persistence.models.project_member_model import ProjectMemberModel

# Módulo Diagram
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import DiagramClassModel
from app.modules.diagram.infrastructure.persistence.models.diagram_attribute_model import DiagramAttributeModel
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import DiagramRelationModel

# Módulo Assistant
from app.modules.assistant.infrastructure.persistence.models.agent_activity_model import AgentActivityModel
