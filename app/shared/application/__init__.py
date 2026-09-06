"""
app/shared/application

Puertos y contratos genéricos de la capa de aplicación.
"""

from app.shared.application.ports import IRepository, IUnitOfWork, Repository, UnitOfWork

__all__ = ["UnitOfWork", "IUnitOfWork", "Repository", "IRepository"]
