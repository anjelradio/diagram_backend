import io
import uuid
from tests.modules.projects.test_xmi_services import SAMPLE_XMI_21


def test_export_project_success(client):
    # 1. Importar un proyecto primero para tener datos reales de clases y diagrama
    file_content = SAMPLE_XMI_21.encode("utf-8")
    file = io.BytesIO(file_content)

    import_res = client.post(
        "/api/projects/import",
        files={"file": ("ecommerce.xmi", file, "application/xml")},
    )
    assert import_res.status_code == 201
    project_id = import_res.json()["id"]

    # 2. Exportar el proyecto
    export_res = client.get(f"/api/projects/{project_id}/export")
    assert export_res.status_code == 200
    assert "application/xml" in export_res.headers["content-type"]
    assert 'attachment; filename="ecommerce_system.xmi"' in export_res.headers["content-disposition"]

    xml_text = export_res.text
    assert "<xmi:XMI" in xml_text
    assert 'xmi:version="2.1"' in xml_text
    assert "Enterprise Architect" in xml_text
    assert "Categoria" in xml_text
    assert "Producto" in xml_text
    assert "titulo: TEXT" in xml_text
    assert "precio: DECIMAL" in xml_text
    assert "geometry=" in xml_text


def test_export_project_not_found(client):
    random_id = uuid.uuid4()
    response = client.get(f"/api/projects/{random_id}/export")
    assert response.status_code == 404
