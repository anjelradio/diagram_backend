# Aplicación Web Colaborativa para el Modelado de Datos — Backend

**Segundo Examen Parcial · Ingeniería de Software I**  
**Universidad Autónoma Gabriel René Moreno (UAGRM)** · Santa Cruz de la Sierra, Bolivia  
**Gestión II/2026**

Backend desarrollado en **Python con FastAPI** para una aplicación web colaborativa orientada al **modelado de datos mediante diagramas de clases UML**. El proyecto integra gestión de proyectos, colaboración entre usuarios y un asistente inteligente capaz de interactuar con el modelo y consultar su historial de modificaciones.

> **Alcance de este repositorio:** contiene el servicio **backend** de la plataforma. El frontend se desarrolla por separado. La **generación de proyectos Spring Boot** es una funcionalidad de la aplicación y no debe confundirse con la tecnología utilizada para implementar este servidor.

## Objetivo

Proporcionar los servicios y la lógica de negocio necesarios para crear, administrar y compartir proyectos de modelado UML, gestionar clases y sus relaciones, asistir a los usuarios mediante lenguaje natural y mantener la trazabilidad de los cambios realizados.

El proyecto se documenta siguiendo el **Proceso Unificado de Desarrollo de Software (PUDS)**, con actividades de requisitos, análisis, diseño, implementación y pruebas.

## Funcionalidades contempladas

- **Gestión de proyectos:** creación, actualización, eliminación e invitaciones a colaboradores.
- **Colaboración y permisos:** propietario, colaborador editor y colaborador lector, con controles según su nivel de acceso.
- **Modelado UML:** operaciones sobre clases, atributos y relaciones, incluidas creación, modificación y eliminación.
- **Asistente inteligente:** interpretación de instrucciones en lenguaje natural, consultas conceptuales, inspección del diagrama y operaciones autorizadas.
- **Auditoría de cambios:** registro del actor, acción, entidad afectada, valores anteriores y posteriores, y fecha de cada modificación.
- **Consultas históricas en lenguaje natural:** preguntas como «¿Quién creó la clase Casa?» o «¿Qué cambios hizo un colaborador ayer?», con interpretación temporal y presentación de horarios locales.
- **Generación de código:** funcionalidad para generar y descargar un proyecto backend **Spring Boot** a partir de los modelos UML.
- **Intercambio e integraciones:** casos de uso para importación/exportación XMI e integración con servicios externos, como Notion y Neon.

> **Nota:** esta lista recoge las capacidades descritas en el documento académico. Para verificar qué funciones están efectivamente disponibles en esta versión, consulta las rutas de la API y el código fuente.

## Tecnologías principales

| Tecnología | Uso |
| --- | --- |
| Python | Lenguaje de programación del servidor |
| FastAPI | Framework para la API backend |
| Uvicorn | Servidor ASGI para ejecutar la aplicación FastAPI |
| UML 2.5+ | Referencia para el modelado de clases y relaciones |
| PUDS | Metodología aplicada al análisis y desarrollo |

Las tecnologías de persistencia, autenticación, servicios de IA y demás dependencias deben consultarse en la configuración y en el archivo de dependencias del repositorio.

## Requisitos previos

- Git instalado.
- Python instalado, en una versión compatible con el proyecto.
- Acceso a las variables de entorno y servicios externos que requiera la implementación.
- Un gestor de dependencias compatible con el repositorio (por ejemplo, `pip`).

## Instalación y ejecución local

### 1. Clonar el repositorio

```bash
git clone https://github.com/USUARIO/NOMBRE-REPOSITORIO.git
cd NOMBRE-REPOSITORIO
```

Reemplaza `USUARIO/NOMBRE-REPOSITORIO` por la URL real de este repositorio.

### 2. Crear un entorno virtual

**Windows (PowerShell):**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Linux / macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Instalar dependencias

Si el repositorio incluye un archivo `requirements.txt`:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Si utiliza `pyproject.toml`, Poetry, uv u otro gestor, sigue el método indicado por esos archivos en lugar del comando anterior.

### 4. Configurar variables de entorno

Si existe un archivo `.env.example`, cópialo como `.env` y completa los valores requeridos.

**Windows (PowerShell):**

```powershell
Copy-Item .env.example .env
```

**Linux / macOS:**

```bash
cp .env.example .env
```

> No subas `.env`, contraseñas, tokens ni claves privadas al repositorio. Los nombres concretos de las variables dependen de la implementación.

### 5. Iniciar el servidor

Para una aplicación FastAPI cuya instancia esté declarada como `app` en `app/main.py`:

```bash
python -m uvicorn app.main:app --reload
```

Si el punto de entrada está en otro archivo, ajusta `app.main:app` a la ruta real de tu aplicación. Por ejemplo, `main:app` cuando `main.py` está en la raíz.

Por defecto, Uvicorn utiliza `http://127.0.0.1:8000`.

### 6. Explorar la API

Cuando el servidor esté activo y las rutas de documentación estén habilitadas:

- **Swagger UI:** http://127.0.0.1:8000/docs
- **ReDoc:** http://127.0.0.1:8000/redoc
- **Esquema OpenAPI:** http://127.0.0.1:8000/openapi.json

Estas direcciones corresponden a las opciones habituales de FastAPI y pueden variar si el proyecto las ha personalizado.

## Auditoría del diagrama

La bitácora `DiagramAuditLog` permite conservar información de los cambios sobre el diagrama, incluyendo:

- Identificación del proyecto y del usuario o asistente responsable.
- Tipo de entidad: clase, atributo o relación.
- Tipo de acción: creación, actualización o eliminación.
- Nombre e identificador del elemento afectado.
- Estado anterior y posterior de la modificación, cuando corresponda.
- Marca temporal del evento.

El asistente puede distinguir entre **consultas históricas**, **preguntas conceptuales**, **inspección del estado actual** y **órdenes de modificación**, evitando que una pregunta sobre el historial provoque cambios no solicitados.

### Ejemplo de consulta

**Pregunta:** ¿A qué hora se creó la clase Casa?

**Ejemplo de respuesta:** La clase **Casa** se creó el **11 de noviembre de 2026 a las 04:27:47 (hora de Bolivia)**.

Las fechas se conservan en UTC para el procesamiento interno y se convierten a la zona horaria configurada para su visualización; la zona predeterminada utilizada en las consultas de auditoría es `America/La_Paz` (UTC−4).

## Pruebas

Si el repositorio incluye pruebas con `pytest`, se pueden ejecutar desde la raíz mediante:

```bash
python -m pytest
```

La implementación de auditoría incluye pruebas orientadas a clasificación de intenciones, consultas por usuario y entidad, interpretación de fechas, conversión de zonas horarias y escenarios de integración del asistente.

> La disponibilidad de `pytest`, los comandos adicionales de preparación y los servicios necesarios para los tests dependen de la configuración real del repositorio.

## Documentación académica

Este proyecto corresponde al **Segundo Examen Parcial de Ingeniería de Software I**, titulado **«Aplicación Web Colaborativa para el Modelado de Datos»**.

La documentación comprende:

1. **Fundamentación teórica:** herramientas CASE, desarrollo basado en componentes, arquitectura de software, inteligencia artificial, PUDS y UML.
2. **Captura de requisitos:** actores, casos de uso, prioridades y especificaciones.
3. **Análisis:** arquitectura, paquetes, comunicación, estados y clases de análisis.
4. **Diseño:** arquitectura física y lógica, datos y diagramas de secuencia.
5. **Implementación y pruebas:** componentes, subsistemas y escenarios de validación.

## Integrantes

| N.º | Nombre completo | Rol / responsabilidad |
| --- | --- | --- |
| 1 | Aradivi Mamani Luciana Paulina | UX/UI |
| 2 | Santos Castro Roberto Anjel | Desarrollador |


**Asignatura:** Ingeniería de Software I  
**Evaluación:** Segundo Examen Parcial  
**Universidad:** Universidad Autónoma Gabriel René Moreno (UAGRM)  
**Gestión:** II/2026  
**Lugar:** Santa Cruz de la Sierra, Bolivia

## Uso académico

Repositorio desarrollado con fines académicos como parte de la evaluación de la asignatura **Ingeniería de Software I**. Su utilización, redistribución y contribuciones están sujetas a las condiciones que establezcan sus autores y a la licencia que se incorpore al repositorio.
