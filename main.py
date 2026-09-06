# main.py
# Permite ejecutar la aplicación tanto con `uvicorn main:app --reload`
# como con el estándar de FastAPI `uvicorn app.main:app --reload`.

from app.main import app  # noqa: F401