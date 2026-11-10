"""Corpus de pruebas de lenguaje natural para intenciones del asistente."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ActionKind = Literal["create", "update", "delete", "query", "clarify", "none"]


@dataclass(frozen=True, slots=True)
class LanguageTestCase:
    prompt: str
    expected_action: ActionKind
    requires_mutation: bool
    category: str
    description: str


LANGUAGE_TEST_CASES: list[LanguageTestCase] = [
    # 1-6: Creación equivalente
    LanguageTestCase(
        prompt="crea una clase Papanatas con atributo Arcoiris",
        expected_action="create",
        requires_mutation=True,
        category="create_equivalent",
        description="crear explícito con atributo",
    ),
    LanguageTestCase(
        prompt="haz una clase Papanatas con atributo Arcoiris",
        expected_action="create",
        requires_mutation=True,
        category="create_equivalent",
        description="haz equivalente a crea",
    ),
    LanguageTestCase(
        prompt="agrega una clase Cliente con atributo email",
        expected_action="create",
        requires_mutation=True,
        category="create_equivalent",
        description="agrega clase",
    ),
    LanguageTestCase(
        prompt="añade una clase Factura con atributo total",
        expected_action="create",
        requires_mutation=True,
        category="create_equivalent",
        description="añade clase",
    ),
    LanguageTestCase(
        prompt="hazme una clase Pedido",
        expected_action="create",
        requires_mutation=True,
        category="create_equivalent",
        description="hazme clase simple",
    ),
    LanguageTestCase(
        prompt="genera una nueva clase Producto",
        expected_action="create",
        requires_mutation=True,
        category="create_equivalent",
        description="genera nueva clase",
    ),
    # 7-12: Modificación equivalente
    LanguageTestCase(
        prompt="modifica la clase Usuario cambiando su nombre a Persona",
        expected_action="update",
        requires_mutation=True,
        category="update_equivalent",
        description="modifica clase",
    ),
    LanguageTestCase(
        prompt="edita el atributo nombre de la clase Cliente",
        expected_action="update",
        requires_mutation=True,
        category="update_equivalent",
        description="edita atributo",
    ),
    LanguageTestCase(
        prompt="actualiza la clase Factura",
        expected_action="update",
        requires_mutation=True,
        category="update_equivalent",
        description="actualiza clase",
    ),
    LanguageTestCase(
        prompt="renombra la clase Pedido a Orden",
        expected_action="update",
        requires_mutation=True,
        category="update_equivalent",
        description="renombra clase",
    ),
    LanguageTestCase(
        prompt="cambia el nombre de la clase Producto a Articulo",
        expected_action="update",
        requires_mutation=True,
        category="update_equivalent",
        description="cambia el nombre clase",
    ),
    LanguageTestCase(
        prompt="ajusta los atributos de la clase Cuenta",
        expected_action="update",
        requires_mutation=True,
        category="update_equivalent",
        description="ajusta atributos",
    ),
    # 13-17: Eliminación equivalente
    LanguageTestCase(
        prompt="elimina la clase Borrador",
        expected_action="delete",
        requires_mutation=True,
        category="delete_equivalent",
        description="elimina clase",
    ),
    LanguageTestCase(
        prompt="borra la clase Temporal",
        expected_action="delete",
        requires_mutation=True,
        category="delete_equivalent",
        description="borra clase",
    ),
    LanguageTestCase(
        prompt="quita el atributo fecha de la clase Evento",
        expected_action="delete",
        requires_mutation=True,
        category="delete_equivalent",
        description="quita atributo",
    ),
    LanguageTestCase(
        prompt="remueve la relación entre Usuario y Perfil",
        expected_action="delete",
        requires_mutation=True,
        category="delete_equivalent",
        description="remueve relación",
    ),
    LanguageTestCase(
        prompt="suprime la clase Invalida",
        expected_action="delete",
        requires_mutation=True,
        category="delete_equivalent",
        description="suprime clase",
    ),
    # 18-22: Negadas (no deben mutar)
    LanguageTestCase(
        prompt="no crees ninguna clase",
        expected_action="none",
        requires_mutation=False,
        category="negated",
        description="negación de creación",
    ),
    LanguageTestCase(
        prompt="no borres la clase Usuario",
        expected_action="none",
        requires_mutation=False,
        category="negated",
        description="negación de borrado",
    ),
    LanguageTestCase(
        prompt="no agregues atributos a la clase Factura",
        expected_action="none",
        requires_mutation=False,
        category="negated",
        description="negación de adición",
    ),
    LanguageTestCase(
        prompt="no modifiques nada del diagrama",
        expected_action="none",
        requires_mutation=False,
        category="negated",
        description="negación total",
    ),
    LanguageTestCase(
        prompt="no elimines la relación entre Cliente y Orden",
        expected_action="none",
        requires_mutation=False,
        category="negated",
        description="negación de relación",
    ),
    # 23-28: Interrogativas / consultas (no deben mutar)
    LanguageTestCase(
        prompt="¿qué clases hay en el diagrama?",
        expected_action="query",
        requires_mutation=False,
        category="question",
        description="pregunta sobre clases",
    ),
    LanguageTestCase(
        prompt="¿puedes decirme qué atributos tiene la clase Usuario?",
        expected_action="query",
        requires_mutation=False,
        category="question",
        description="pregunta sobre atributos",
    ),
    LanguageTestCase(
        prompt="¿debería crear una clase para los pagos?",
        expected_action="query",
        requires_mutation=False,
        category="question",
        description="duda/pregunta de diseño",
    ),
    LanguageTestCase(
        prompt="dime cómo se relacionan Cliente y Factura",
        expected_action="query",
        requires_mutation=False,
        category="question",
        description="consulta de relaciones",
    ),
    LanguageTestCase(
        prompt="¿cuál es la estructura actual del proyecto?",
        expected_action="query",
        requires_mutation=False,
        category="question",
        description="consulta de estructura",
    ),
    LanguageTestCase(
        prompt="revisa si la clase Producto tiene clave foránea",
        expected_action="query",
        requires_mutation=False,
        category="question",
        description="revisión/consulta",
    ),
    # 29-32: Ambigüedad (debe pedir aclaración y no mutar directamente)
    LanguageTestCase(
        prompt="tal vez una clase o quizás modificarla",
        expected_action="clarify",
        requires_mutation=False,
        category="ambiguous",
        description="ambigüedad crear o modificar",
    ),
    LanguageTestCase(
        prompt="hacer algo con usuario en el diagrama",
        expected_action="clarify",
        requires_mutation=False,
        category="ambiguous",
        description="verbo vago sin acción concreta",
    ),
    LanguageTestCase(
        prompt="podríamos ver si clase o atributo nuevo",
        expected_action="clarify",
        requires_mutation=False,
        category="ambiguous",
        description="propuesta indecisa",
    ),
    # 33-35: Ejemplos citados (no deben mutar)
    LanguageTestCase(
        prompt="un ejemplo de instrucción sería: crea una clase Factura",
        expected_action="none",
        requires_mutation=False,
        category="cited_example",
        description="ejemplo de creación en texto",
    ),
    LanguageTestCase(
        prompt="por ejemplo: elimina la clase Pedido",
        expected_action="none",
        requires_mutation=False,
        category="cited_example",
        description="ejemplo de eliminación en texto",
    ),
    # 36-38: Solicitudes combinadas / múltiples
    LanguageTestCase(
        prompt="haz una clase Factura y agrega un atributo total",
        expected_action="create",
        requires_mutation=True,
        category="combined",
        description="crear y agregar dependiente",
    ),
    LanguageTestCase(
        prompt="crea una clase Cliente y luego dime qué atributos tiene",
        expected_action="create",
        requires_mutation=True,
        category="combined",
        description="mutación y consulta secuencial",
    ),
]
