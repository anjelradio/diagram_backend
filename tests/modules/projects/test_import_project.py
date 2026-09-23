import io
import uuid
from tests.modules.projects.test_xmi_services import SAMPLE_XMI_21


def test_import_project_success(client):
    file_content = SAMPLE_XMI_21.encode("utf-8")
    file = io.BytesIO(file_content)

    response = client.post(
        "/api/projects/import",
        files={"file": ("model.xmi", file, "application/xml")},
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    project_id = uuid.UUID(data["id"])
    assert project_id is not None

    # Verificar que el proyecto aparece en la lista con el nombre extraído
    list_response = client.get("/api/projects")
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    imported = next((p for p in items if p["id"] == str(project_id)), None)
    assert imported is not None
    assert imported["name"] == "ECommerce System"
    assert imported["is_owner"] is True

    # Verificar que el diagrama contiene las 2 clases importadas
    diagram_response = client.get(f"/api/projects/{project_id}/diagram")
    assert diagram_response.status_code == 200
    diagram_data = diagram_response.json()

    classes = diagram_data["classes"]
    assert len(classes) == 2
    class_names = [c["name"] for c in classes]
    assert "Categoria" in class_names
    assert "Producto" in class_names

    # Verificar atributos
    prod = next(c for c in classes if c["name"] == "Producto")
    attr_names = [a["name"] for a in prod["attributes"]]
    assert "id" in attr_names
    assert "titulo" in attr_names
    assert "precio" in attr_names


def test_import_project_invalid_file_rejected(client):
    invalid_file = io.BytesIO(b"not an xml file content")

    response = client.post(
        "/api/projects/import",
        files={"file": ("corrupt.xml", invalid_file, "application/xml")},
    )
    assert response.status_code == 400 or response.status_code == 422


def test_import_project_with_non_associative_relations_ignores_names(client):
    """Verifica que si una relación no asociativa en XMI trae nombre o cardinalidad, se ignoren limpiamente y se cree con nombre vacío."""
    xml_with_named_non_assoc = """<?xml version="1.0" encoding="utf-8"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1">
  <xmi:Documentation exporter="Enterprise Architect" exporterVersion="6.5"/>
  <uml:Model xmi:type="uml:Model" name="Corporate Model">
    <packagedElement xmi:type="uml:Package" xmi:id="EAID_PACKAGE_1" name="Corporate Model">
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_PERSON" name="Persona">
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_P_NAME" name="nombre: text"/>
      </packagedElement>
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_EMPLOYEE" name="Empleado">
        <generalization xmi:type="uml:Generalization" xmi:id="EAID_GEN_1" general="EAID_PERSON" name="Herencia"/>
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_E_SALARY" name="salario: decimal"/>
      </packagedElement>
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_DEPT" name="Departamento">
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_D_NAME" name="nombre: text"/>
      </packagedElement>
      <packagedElement xmi:type="uml:Association" xmi:id="EAID_COMP_1" name="Compone">
        <memberEnd xmi:idref="EAID_END_D"/>
        <memberEnd xmi:idref="EAID_END_E"/>
        <ownedEnd xmi:type="uml:Property" xmi:id="EAID_END_D" type="EAID_DEPT"/>
        <ownedEnd xmi:type="uml:Property" xmi:id="EAID_END_E" type="EAID_EMPLOYEE" aggregation="composite"/>
      </packagedElement>
    </packagedElement>
  </uml:Model>
  <xmi:Extension extender="Enterprise Architect" extenderID="6.5">
    <connectors>
      <connector xmi:idref="EAID_GEN_1">
        <source xmi:idref="EAID_EMPLOYEE"/>
        <target xmi:idref="EAID_PERSON"/>
        <properties ea_type="Generalization" direction="Source -> Destination"/>
        <labels mt="Es un"/>
      </connector>
      <connector xmi:idref="EAID_COMP_1">
        <source xmi:idref="EAID_DEPT"/>
        <target xmi:idref="EAID_EMPLOYEE"/>
        <properties ea_type="Composition" direction="Unspecified"/>
        <labels lb="1" rb="0..*" mt="Contiene"/>
      </connector>
    </connectors>
    <diagrams>
      <diagram xmi:id="EAID_DIAGRAM_1">
        <elements>
          <element geometry="Left=100;Top=100;Right=280;Bottom=240;" subject="EAID_PERSON"/>
          <element geometry="Left=100;Top=350;Right=280;Bottom=490;" subject="EAID_EMPLOYEE"/>
          <element geometry="Left=400;Top=350;Right=580;Bottom=490;" subject="EAID_DEPT"/>
        </elements>
      </diagram>
    </diagrams>
  </xmi:Extension>
</xmi:XMI>"""

    file = io.BytesIO(xml_with_named_non_assoc.encode("utf-8"))
    response = client.post(
        "/api/projects/import",
        files={"file": ("corporate.xmi", file, "application/xml")},
    )
    assert response.status_code == 201
    project_id = response.json()["id"]

    diagram_response = client.get(f"/api/projects/{project_id}/diagram")
    assert diagram_response.status_code == 200
    diag = diagram_response.json()

    assert len(diag["classes"]) == 3
    assert len(diag["relations"]) == 2

    # Verificar que NINGUNA relación no asociativa retuvo su nombre, todas tienen ""
    for rel in diag["relations"]:
        assert rel["name"] == ""
        assert rel["relation_type"] in ("GENERALIZATION", "COMPOSITION")
        assert rel["source_cardinality"] is None
        assert rel["target_cardinality"] is None

    # Verificar materialización de SHARED_PRIMARY_KEY en la subclase Empleado
    emp_class = next(c for c in diag["classes"] if c["name"] == "Empleado")
    emp_pk = next(a for a in emp_class["attributes"] if a["is_primary_key"])
    person_class = next(c for c in diag["classes"] if c["name"] == "Persona")
    assert emp_pk["referenced_class_id"] == person_class["id"]

