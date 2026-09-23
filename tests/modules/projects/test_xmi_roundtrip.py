"""Pruebas de ciclo completo (round-trip) e interoperabilidad con Enterprise Architect XMI."""

import io
import uuid
import pytest
from tests.modules.projects.test_xmi_services import SAMPLE_XMI_21


def test_roundtrip_export_and_reimport_preserves_diagram_fidelity(client):
    """Verifica que exportar un proyecto y reimportarlo mantiene clases, atributos, tipos, relaciones y coordenadas."""
    # 1. Importar proyecto original (Proyecto A)
    file_a = io.BytesIO(SAMPLE_XMI_21.encode("utf-8"))
    res_a = client.post(
        "/api/projects/import",
        files={"file": ("original.xmi", file_a, "application/xml")},
    )
    assert res_a.status_code == 201
    proj_a_id = res_a.json()["id"]

    # 2. Consultar diagrama de Proyecto A
    diagram_a_res = client.get(f"/api/projects/{proj_a_id}/diagram")
    assert diagram_a_res.status_code == 200
    diag_a = diagram_a_res.json()

    classes_a = diag_a["classes"]
    assert len(classes_a) == 2
    relations_a = diag_a["relations"]
    assert len(relations_a) == 1

    # 3. Exportar Proyecto A a XMI
    export_res = client.get(f"/api/projects/{proj_a_id}/export")
    assert export_res.status_code == 200
    exported_xml = export_res.text
    assert "<xmi:XMI" in exported_xml

    # 4. Reimportar el XML exportado como Proyecto B
    file_b = io.BytesIO(exported_xml.encode("utf-8"))
    res_b = client.post(
        "/api/projects/import",
        files={"file": ("reimported.xmi", file_b, "application/xml")},
    )
    assert res_b.status_code == 201
    proj_b_id = res_b.json()["id"]
    assert proj_b_id != proj_a_id

    # 5. Consultar diagrama de Proyecto B y verificar fidelidad
    diagram_b_res = client.get(f"/api/projects/{proj_b_id}/diagram")
    assert diagram_b_res.status_code == 200
    diag_b = diagram_b_res.json()

    classes_b = diag_b["classes"]
    relations_b = diag_b["relations"]

    # Verificar clases
    assert len(classes_b) == len(classes_a)
    classes_b_by_name = {c["name"]: c for c in classes_b}

    for class_a in classes_a:
        name = class_a["name"]
        assert name in classes_b_by_name
        class_b = classes_b_by_name[name]

        # Verificar coordenadas espaciales (tolerancia por redondeo)
        assert abs(class_a["position_x"] - class_b["position_x"]) <= 2.0
        assert abs(class_a["position_y"] - class_b["position_y"]) <= 2.0

        # Verificar atributos secundarios (excluyendo PK autogenerada id)
        attrs_a = {a["name"]: a["data_type"] for a in class_a["attributes"] if a["name"] != "id"}
        attrs_b = {a["name"]: a["data_type"] for a in class_b["attributes"] if a["name"] != "id"}
        assert attrs_a == attrs_b

    # Verificar relaciones
    assert len(relations_b) == len(relations_a)
    rel_a = relations_a[0]
    rel_b = relations_b[0]
    assert rel_b["relation_type"] == rel_a["relation_type"]
    assert rel_b["source_cardinality"] == rel_a["source_cardinality"]
    assert rel_b["target_cardinality"] == rel_a["target_cardinality"]


def test_import_with_operations_safely_ignored(client):
    """Verifica que elementos <ownedOperation> se ignoren limpiamente sin causar fallos."""
    xml_with_operations = """<?xml version="1.0" encoding="utf-8"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1">
  <uml:Model xmi:type="uml:Model" name="ServicioModelo">
    <packagedElement xmi:type="uml:Package" xmi:id="EAID_1" name="ServicioModelo">
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_C1" name="Factura">
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_A1" name="numero: TEXT"/>
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_A2" name="monto: DECIMAL"/>
        <ownedOperation xmi:type="uml:Operation" xmi:id="EAID_OP1" name="calcularTotal"/>
        <ownedOperation xmi:type="uml:Operation" xmi:id="EAID_OP2" name="imprimir"/>
      </packagedElement>
    </packagedElement>
  </uml:Model>
</xmi:XMI>"""

    file = io.BytesIO(xml_with_operations.encode("utf-8"))
    res = client.post(
        "/api/projects/import",
        files={"file": ("operations.xmi", file, "application/xml")},
    )
    assert res.status_code == 201
    proj_id = res.json()["id"]

    diag_res = client.get(f"/api/projects/{proj_id}/diagram")
    assert diag_res.status_code == 200
    diag = diag_res.json()
    assert len(diag["classes"]) == 1
    cls = diag["classes"][0]
    assert cls["name"] == "Factura"
    attr_names = [a["name"] for a in cls["attributes"]]
    assert "numero" in attr_names
    assert "monto" in attr_names
    assert "calcularTotal" not in attr_names


def test_import_non_class_elements_only_raises_422(client):
    """Verifica que un archivo con solo actores o casos de uso sea rechazado con 422."""
    xml_actors_only = """<?xml version="1.0" encoding="utf-8"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1">
  <uml:Model xmi:type="uml:Model" name="CasosDeUso">
    <packagedElement xmi:type="uml:Package" xmi:id="EAID_1" name="CasosDeUso">
      <packagedElement xmi:type="uml:Actor" xmi:id="EAID_ACTOR" name="Administrador"/>
      <packagedElement xmi:type="uml:UseCase" xmi:id="EAID_UC1" name="Iniciar Sesion"/>
    </packagedElement>
  </uml:Model>
</xmi:XMI>"""

    file = io.BytesIO(xml_actors_only.encode("utf-8"))
    res = client.post(
        "/api/projects/import",
        files={"file": ("use_cases.xmi", file, "application/xml")},
    )
    assert res.status_code in (400, 422)
    error_str = res.text
    assert "no contiene un diagrama de clases" in error_str


def test_roundtrip_many_to_many_with_association_class(client):
    """Verifica el ciclo completo de exportación y reimportación para relaciones M:N con clase intermedia."""
    xmi_many_to_many = """<?xml version="1.0" encoding="utf-8"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1">
  <xmi:Documentation exporter="Enterprise Architect" exporterVersion="6.5"/>
  <uml:Model xmi:type="uml:Model" name="Academics">
    <packagedElement xmi:type="uml:Package" xmi:id="EAID_PACKAGE_1" name="Academics">
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_STUDENT" name="Student">
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_S_NAME" name="name: text"/>
      </packagedElement>
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_COURSE" name="Course">
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_C_TITLE" name="title: text"/>
      </packagedElement>
      <packagedElement xmi:type="uml:AssociationClass" xmi:id="EAID_ENROLLMENT" name="Enrollment">
        <memberEnd xmi:idref="EAID_END_S"/>
        <memberEnd xmi:idref="EAID_END_C"/>
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_E_GRADE" name="grade: decimal"/>
        <ownedEnd xmi:type="uml:Property" xmi:id="EAID_END_S" type="EAID_STUDENT">
          <type xmi:idref="EAID_STUDENT"/>
          <lowerValue xmi:type="uml:LiteralInteger" value="0"/>
          <upperValue xmi:type="uml:LiteralUnlimitedNatural" value="*"/>
        </ownedEnd>
        <ownedEnd xmi:type="uml:Property" xmi:id="EAID_END_C" type="EAID_COURSE">
          <type xmi:idref="EAID_COURSE"/>
          <lowerValue xmi:type="uml:LiteralInteger" value="0"/>
          <upperValue xmi:type="uml:LiteralUnlimitedNatural" value="*"/>
        </ownedEnd>
      </packagedElement>
    </packagedElement>
  </uml:Model>
  <xmi:Extension extender="Enterprise Architect" extenderID="6.5">
    <connectors>
      <connector xmi:idref="EAID_ENROLLMENT">
        <source xmi:idref="EAID_STUDENT"><model type="Class"/><type multiplicity="0..*"/></source>
        <target xmi:idref="EAID_COURSE"><model type="Class"/><type multiplicity="0..*"/></target>
        <properties ea_type="AssociationClass" direction="Unspecified"/>
      </connector>
    </connectors>
    <diagrams>
      <diagram xmi:id="EAID_DIAGRAM_1">
        <model package="EAID_PACKAGE_1" localID="1" owner="EAID_PACKAGE_1"/>
        <elements>
          <element geometry="Left=100;Top=100;Right=280;Bottom=240;" subject="EAID_STUDENT"/>
          <element geometry="Left=500;Top=100;Right=680;Bottom=240;" subject="EAID_COURSE"/>
          <element geometry="Left=300;Top=300;Right=480;Bottom=440;" subject="EAID_ENROLLMENT"/>
        </elements>
        <connectors>
          <connector xmi:idref="EAID_ENROLLMENT"/>
        </connectors>
      </diagram>
    </diagrams>
  </xmi:Extension>
</xmi:XMI>"""

    # 1. Importar el proyecto original
    file_orig = io.BytesIO(xmi_many_to_many.encode("utf-8"))
    res_orig = client.post(
        "/api/projects/import",
        files={"file": ("academics.xmi", file_orig, "application/xml")},
    )
    assert res_orig.status_code == 201
    proj_id = res_orig.json()["id"]

    # 2. Consultar diagrama y verificar que Enrollment es la clase puente
    diag_res = client.get(f"/api/projects/{proj_id}/diagram")
    assert diag_res.status_code == 200
    diag = diag_res.json()

    assert len(diag["classes"]) == 3
    classes_by_name = {c["name"]: c for c in diag["classes"]}
    assert set(classes_by_name.keys()) == {"Student", "Course", "Enrollment"}

    enrollment_cls = classes_by_name["Enrollment"]
    attr_names = [a["name"] for a in enrollment_cls["attributes"]]
    assert "grade" in attr_names

    assert len(diag["relations"]) == 1
    rel = diag["relations"][0]
    assert rel["bridge"] is not None
    assert rel["bridge"]["class_id"] == enrollment_cls["id"]

    # 3. Exportar a XMI
    export_res = client.get(f"/api/projects/{proj_id}/export")
    assert export_res.status_code == 200
    exported_xml = export_res.text

    assert '<packagedElement xmi:type="uml:AssociationClass"' in exported_xml
    assert 'name="Enrollment"' in exported_xml
    assert 'ea_type="AssociationClass"' in exported_xml

    # 4. Reimportar el XML exportado (comprobar que NO se duplican clases y se preserva el puente)
    file_reimport = io.BytesIO(exported_xml.encode("utf-8"))
    res_reimport = client.post(
        "/api/projects/import",
        files={"file": ("reimported_academics.xmi", file_reimport, "application/xml")},
    )
    assert res_reimport.status_code == 201
    reimported_proj_id = res_reimport.json()["id"]

    # 5. Consultar diagrama del proyecto reimportado
    reimport_diag_res = client.get(f"/api/projects/{reimported_proj_id}/diagram")
    assert reimport_diag_res.status_code == 200
    reimport_diag = reimport_diag_res.json()

    # Verificar que NO se crearon clases duplicadas
    assert len(reimport_diag["classes"]) == 3
    reimport_classes_by_name = {c["name"]: c for c in reimport_diag["classes"]}
    assert set(reimport_classes_by_name.keys()) == {"Student", "Course", "Enrollment"}

    # Verificar que la relación conserva el puente hacia Enrollment
    assert len(reimport_diag["relations"]) == 1
    reimport_rel = reimport_diag["relations"][0]
    reimport_enrollment = reimport_classes_by_name["Enrollment"]
    assert reimport_rel["bridge"] is not None
    assert reimport_rel["bridge"]["class_id"] == reimport_enrollment["id"]


def test_roundtrip_one_to_many_cardinality_preservation(client):
    """Verifica que relaciones 1:N preserven cardinalidades exactas sin inversión en exportación y reimportación."""
    # 1. Importar muestra con Categoria (1) y Producto (0..*)
    file_orig = io.BytesIO(SAMPLE_XMI_21.encode("utf-8"))
    res_orig = client.post(
        "/api/projects/import",
        files={"file": ("ecommerce.xmi", file_orig, "application/xml")},
    )
    assert res_orig.status_code == 201
    proj_a_id = res_orig.json()["id"]

    diag_a_res = client.get(f"/api/projects/{proj_a_id}/diagram")
    assert diag_a_res.status_code == 200
    diag_a = diag_a_res.json()

    classes_a = {c["name"]: c for c in diag_a["classes"]}
    cat_a = classes_a["Categoria"]
    prod_a = classes_a["Producto"]

    rel_a = diag_a["relations"][0]
    assert rel_a["source_cardinality"] == "1"
    assert rel_a["target_cardinality"] == "0..*"
    assert rel_a["source"]["class_id"] == cat_a["id"]
    assert rel_a["target"]["class_id"] == prod_a["id"]

    # 2. Exportar a XMI
    export_res = client.get(f"/api/projects/{proj_a_id}/export")
    assert export_res.status_code == 200
    xml_exported = export_res.text

    # Verificar etiquetas específicas para Enterprise Architect
    assert '<labels lb="1" rb="0..*" mt="Pertenece"/>' in xml_exported
    # Verificar orden de extremos en UML (destino primero)
    assert '<memberEnd xmi:idref="EAID_END_TGT_' in xml_exported

    # 3. Reimportar el XMI generado
    file_reimport = io.BytesIO(xml_exported.encode("utf-8"))
    res_reimport = client.post(
        "/api/projects/import",
        files={"file": ("reimported_ecommerce.xmi", file_reimport, "application/xml")},
    )
    assert res_reimport.status_code == 201
    proj_b_id = res_reimport.json()["id"]

    # 4. Verificar proyecto reimportado
    diag_b_res = client.get(f"/api/projects/{proj_b_id}/diagram")
    assert diag_b_res.status_code == 200
    diag_b = diag_b_res.json()

    classes_b = {c["name"]: c for c in diag_b["classes"]}
    cat_b = classes_b["Categoria"]
    prod_b = classes_b["Producto"]

    rel_b = diag_b["relations"][0]
    # Cardinalidades deben ser idénticas: Categoria = 1, Producto = 0..*
    assert rel_b["source_cardinality"] == "1"
    assert rel_b["target_cardinality"] == "0..*"
    assert rel_b["source"]["class_id"] == cat_b["id"]
    assert rel_b["target"]["class_id"] == prod_b["id"]

    # Clave foránea debe estar en Producto apuntando a Categoria
    prod_fk = next((a for a in prod_b["attributes"] if a.get("is_foreign_key")), None)
    assert prod_fk is not None
    assert prod_fk["referenced_class_id"] == cat_b["id"]


def test_import_user_real_enterprise_architect_xmi_11_project(client):
    """Verifica que el endpoint de importación acepte el archivo XMI 1.1 exportado por Enterprise Architect."""
    from tests.modules.projects.test_xmi_services import test_xmi_importer_parses_enterprise_architect_xmi_11_uml_13
    import io

    # Archivo exacto exportado por EA en formato XMI 1.1 / UML 1.3
    ea_file_content = """<?xml version="1.0" encoding="windows-1252" standalone="no" ?>
<XMI xmi.version="1.1" xmlns:UML="omg.org/UML1.3" timestamp="2026-09-21 12:28:46">
	<XMI.header>
		<XMI.documentation>
			<XMI.exporter>Enterprise Architect</XMI.exporter>
			<XMI.exporterVersion>2.5</XMI.exporterVersion>
			<XMI.exporterID>1721</XMI.exporterID>
		</XMI.documentation>
	</XMI.header>
	<XMI.content>
		<UML:Model name="EA Model" xmi.id="MX_EAID_PACKAGE_1">
			<UML:Namespace.ownedElement>
				<UML:Class name="EARootClass" xmi.id="EAID_11111111_5487_4080_A7F4_41526CB0AA00" isRoot="true" isLeaf="false" isAbstract="false"/>
				<UML:Package name="Nuevo proyecto 2" xmi.id="EAPK_PACKAGE_1" isRoot="false" isLeaf="false" isAbstract="false" visibility="public">
					<UML:Namespace.ownedElement>
						<UML:Class name="Compra" xmi.id="EAID_212370D4BC5D48BB9F0C53B7C40B5F99" visibility="public">
							<UML:Classifier.feature>
								<UML:Attribute name="fecha_compra: TIMESTAMP"/>
								<UML:Attribute name="id: UUID"/>
								<UML:Attribute name="proveedor_id: UUID"/>
							</UML:Classifier.feature>
						</UML:Class>
						<UML:Association xmi.id="EAID_A52B96D9_4602_480a_BCAB_FA41740BC07D" visibility="public">
							<UML:ModelElement.taggedValue>
								<UML:TaggedValue tag="ea_type" value="Association"/>
								<UML:TaggedValue tag="associationclass" value="EAID_630BE12DDC4649B38C671226B4E49FE3"/>
								<UML:TaggedValue tag="lb" value="0..*"/>
								<UML:TaggedValue tag="rb" value="0..*"/>
							</UML:ModelElement.taggedValue>
							<UML:Association.connection>
								<UML:AssociationEnd visibility="public" multiplicity="0..*" type="EAID_212370D4BC5D48BB9F0C53B7C40B5F99">
									<UML:ModelElement.taggedValue>
										<UML:TaggedValue tag="ea_end" value="source"/>
									</UML:ModelElement.taggedValue>
								</UML:AssociationEnd>
								<UML:AssociationEnd visibility="public" multiplicity="0..*" type="EAID_EE28DE3708494BC6BA946F2B8B55F956">
									<UML:ModelElement.taggedValue>
										<UML:TaggedValue tag="ea_end" value="target"/>
									</UML:ModelElement.taggedValue>
								</UML:AssociationEnd>
							</UML:Association.connection>
						</UML:Association>
						<UML:Association name="pertenece" xmi.id="EAID_E7AF290A9627465B983255A96DDCD69D" visibility="public">
							<UML:ModelElement.taggedValue>
								<UML:TaggedValue tag="ea_type" value="Association"/>
								<UML:TaggedValue tag="lb" value="1"/>
								<UML:TaggedValue tag="mt" value="pertenece"/>
								<UML:TaggedValue tag="rb" value="0..*"/>
							</UML:ModelElement.taggedValue>
							<UML:Association.connection>
								<UML:AssociationEnd visibility="public" multiplicity="1" type="EAID_AEBF4FA4D1EA461B88430793AEFAAE72">
									<UML:ModelElement.taggedValue>
										<UML:TaggedValue tag="ea_end" value="source"/>
									</UML:ModelElement.taggedValue>
								</UML:AssociationEnd>
								<UML:AssociationEnd visibility="public" multiplicity="0..*" type="EAID_212370D4BC5D48BB9F0C53B7C40B5F99">
									<UML:ModelElement.taggedValue>
										<UML:TaggedValue tag="ea_end" value="target"/>
									</UML:ModelElement.taggedValue>
								</UML:AssociationEnd>
							</UML:Association.connection>
						</UML:Association>
						<UML:Class name="CompraProducto" xmi.id="EAID_630BE12DDC4649B38C671226B4E49FE3" visibility="public">
							<UML:Classifier.feature>
								<UML:Attribute name="cantidad: INTEGER"/>
								<UML:Attribute name="compra_id: UUID"/>
								<UML:Attribute name="id: UUID"/>
								<UML:Attribute name="precio_unitario: DECIMAL"/>
								<UML:Attribute name="producto_id: UUID"/>
								<UML:Attribute name="total: DECIMAL"/>
							</UML:Classifier.feature>
						</UML:Class>
						<UML:Class name="Proveedor" xmi.id="EAID_AEBF4FA4D1EA461B88430793AEFAAE72" visibility="public">
							<UML:Classifier.feature>
								<UML:Attribute name="contacto: TEXT"/>
								<UML:Attribute name="id: UUID"/>
								<UML:Attribute name="nombre: TEXT"/>
							</UML:Classifier.feature>
						</UML:Class>
						<UML:Class name="Producto" xmi.id="EAID_EE28DE3708494BC6BA946F2B8B55F956" visibility="public">
							<UML:Classifier.feature>
								<UML:Attribute name="id: UUID"/>
								<UML:Attribute name="nombre: TEXT"/>
								<UML:Attribute name="precio: INTEGER"/>
								<UML:Attribute name="stock: INTEGER"/>
							</UML:Classifier.feature>
						</UML:Class>
					</UML:Namespace.ownedElement>
				</UML:Package>
			</UML:Namespace.ownedElement>
		</UML:Model>
		<UML:Diagram name="Nuevo proyecto 2" xmi.id="EAID_DIAGRAM_1" diagramType="ClassDiagram">
			<UML:Diagram.element>
				<UML:DiagramElement geometry="Left=613;Top=244;Right=765;Bottom=358;" subject="EAID_630BE12DDC4649B38C671226B4E49FE3"/>
				<UML:DiagramElement geometry="Left=1221;Top=10;Right=1401;Bottom=150;" subject="EAID_AEBF4FA4D1EA461B88430793AEFAAE72"/>
				<UML:DiagramElement geometry="Left=858;Top=45;Right=1022;Bottom=115;" subject="EAID_212370D4BC5D48BB9F0C53B7C40B5F99"/>
				<UML:DiagramElement geometry="Left=850;Top=488;Right=1030;Bottom=628;" subject="EAID_EE28DE3708494BC6BA946F2B8B55F956"/>
			</UML:Diagram.element>
		</UML:Diagram>
	</XMI.content>
</XMI>"""

    file_bytes = io.BytesIO(ea_file_content.encode("windows-1252"))
    res = client.post(
        "/api/projects/import",
        files={"file": ("ea_model.xml", file_bytes, "application/xml")},
    )
    assert res.status_code == 201
    proj_id = res.json()["id"]

    diag_res = client.get(f"/api/projects/{proj_id}/diagram")
    assert diag_res.status_code == 200
    diag = diag_res.json()

    # Verificar que EARootClass NO fue importada, quedando 4 clases
    assert len(diag["classes"]) == 4
    class_names = {c["name"] for c in diag["classes"]}
    assert class_names == {"Compra", "CompraProducto", "Proveedor", "Producto"}

    # Verificar que se crearon las 2 relaciones
    assert len(diag["relations"]) == 2
    relations_by_name = {r["name"]: r for r in diag["relations"]}
    assert "pertenece" in relations_by_name

    # Verificar que CompraProducto actúa como puente de la relación M:N
    compra_prod_class = next(c for c in diag["classes"] if c["name"] == "CompraProducto")
    mn_rel = next(r for r in diag["relations"] if r["bridge"] is not None)
    assert mn_rel["bridge"]["class_id"] == compra_prod_class["id"]

    # Verificar posiciones canónicas en la clase intermedia reutilizada:
    # 0: id (PK)
    # 1: compra_id (FK)
    # 2: producto_id (FK)
    # 3+: Atributos de negocio (cantidad, precio_unitario, total)
    ordered_attrs = sorted(compra_prod_class["attributes"], key=lambda a: a["position"])
    assert [a["position"] for a in ordered_attrs] == [0, 1, 2, 3, 4, 5]
    assert ordered_attrs[0]["name"] == "id"
    assert ordered_attrs[0]["is_primary_key"] is True
    assert ordered_attrs[1]["name"] == "compra_id"
    assert ordered_attrs[1]["is_foreign_key"] is True
    assert ordered_attrs[2]["name"] == "producto_id"
    assert ordered_attrs[2]["is_foreign_key"] is True
    assert [a["name"] for a in ordered_attrs[3:]] == ["cantidad", "precio_unitario", "total"]
    assert all(not a["is_foreign_key"] and not a["is_primary_key"] for a in ordered_attrs[3:])


def test_roundtrip_recursive_association_preservation(client):
    """Verifica que una asociación recursiva (auto-referenciada) se exporte y reimporte correctamente conservando extremos y FK nullable."""
    xmi_self_ref = """<?xml version="1.0" encoding="utf-8"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1">
  <xmi:Documentation exporter="Enterprise Architect" exporterVersion="6.5"/>
  <uml:Model xmi:type="uml:Model" name="OrgChart">
    <packagedElement xmi:type="uml:Package" xmi:id="EAID_PACKAGE_1" name="OrgChart">
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_EMPLOYEE" name="Employee">
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_EMP_NAME" name="name: text"/>
      </packagedElement>
      <packagedElement xmi:type="uml:Association" xmi:id="EAID_SELF_REL" name="Supervises">
        <memberEnd xmi:idref="EAID_END_TGT"/>
        <memberEnd xmi:idref="EAID_END_SRC"/>
        <ownedEnd xmi:type="uml:Property" xmi:id="EAID_END_TGT" type="EAID_EMPLOYEE">
          <type xmi:idref="EAID_EMPLOYEE"/>
          <lowerValue xmi:type="uml:LiteralInteger" value="0"/>
          <upperValue xmi:type="uml:LiteralInteger" value="1"/>
        </ownedEnd>
        <ownedEnd xmi:type="uml:Property" xmi:id="EAID_END_SRC" type="EAID_EMPLOYEE">
          <type xmi:idref="EAID_EMPLOYEE"/>
          <lowerValue xmi:type="uml:LiteralInteger" value="0"/>
          <upperValue xmi:type="uml:LiteralUnlimitedNatural" value="*"/>
        </ownedEnd>
      </packagedElement>
    </packagedElement>
  </uml:Model>
  <xmi:Extension extender="Enterprise Architect" extenderID="6.5">
    <connectors>
      <connector xmi:idref="EAID_SELF_REL">
        <source xmi:idref="EAID_EMPLOYEE"><model type="Class"/><type multiplicity="0..*"/></source>
        <target xmi:idref="EAID_EMPLOYEE"><model type="Class"/><type multiplicity="0..1"/></target>
        <properties ea_type="Association" direction="Unspecified"/>
        <labels lb="0..*" rb="0..1" mt="Supervises"/>
      </connector>
    </connectors>
    <diagrams>
      <diagram xmi:id="EAID_DIAGRAM_1">
        <model package="EAID_PACKAGE_1" localID="1" owner="EAID_PACKAGE_1"/>
        <elements>
          <element geometry="Left=100;Top=100;Right=280;Bottom=240;" subject="EAID_EMPLOYEE"/>
        </elements>
        <connectors>
          <connector xmi:idref="EAID_SELF_REL"/>
        </connectors>
      </diagram>
    </diagrams>
  </xmi:Extension>
</xmi:XMI>"""

    # 1. Importar el proyecto con auto-referencia
    file_orig = io.BytesIO(xmi_self_ref.encode("utf-8"))
    res_orig = client.post(
        "/api/projects/import",
        files={"file": ("orgchart.xmi", file_orig, "application/xml")},
    )
    assert res_orig.status_code == 201
    proj_id = res_orig.json()["id"]

    # 2. Consultar diagrama y verificar relación reflexiva
    diag_res = client.get(f"/api/projects/{proj_id}/diagram")
    assert diag_res.status_code == 200
    diag = diag_res.json()

    assert len(diag["classes"]) == 1
    emp_cls = diag["classes"][0]
    assert emp_cls["name"] == "Employee"

    # Verificar atributo FK generado en la propia clase y nullable
    fk_attr = next((a for a in emp_cls["attributes"] if a.get("is_foreign_key")), None)
    assert fk_attr is not None
    assert fk_attr["referenced_class_id"] == emp_cls["id"]
    assert fk_attr["is_nullable"] is True

    # Verificar que la relación conecta la clase consigo misma con handles distintos
    assert len(diag["relations"]) == 1
    rel = diag["relations"][0]
    assert rel["source"]["class_id"] == emp_cls["id"]
    assert rel["target"]["class_id"] == emp_cls["id"]
    assert rel["source"]["handle"] != rel["target"]["handle"]

    # 3. Exportar a XMI
    export_res = client.get(f"/api/projects/{proj_id}/export")
    assert export_res.status_code == 200
    exported_xml = export_res.text
    assert '<packagedElement xmi:type="uml:Association"' in exported_xml

    # 4. Reimportar el XMI exportado
    file_reimport = io.BytesIO(exported_xml.encode("utf-8"))
    res_reimport = client.post(
        "/api/projects/import",
        files={"file": ("reimported_orgchart.xmi", file_reimport, "application/xml")},
    )
    assert res_reimport.status_code == 201
    reimported_proj_id = res_reimport.json()["id"]

    # 5. Consultar diagrama reimportado y validar fidelidad
    reimport_diag_res = client.get(f"/api/projects/{reimported_proj_id}/diagram")
    assert reimport_diag_res.status_code == 200
    reimport_diag = reimport_diag_res.json()

    assert len(reimport_diag["classes"]) == 1
    assert len(reimport_diag["relations"]) == 1
    reimport_emp = reimport_diag["classes"][0]
    reimport_rel = reimport_diag["relations"][0]

    assert reimport_rel["source"]["class_id"] == reimport_emp["id"]
    assert reimport_rel["target"]["class_id"] == reimport_emp["id"]
    assert reimport_rel["source"]["handle"] != reimport_rel["target"]["handle"]


def test_roundtrip_recursive_many_to_many_association_class(client):
    """Verifica que una relación M:N reflexiva (recursiva) con clase intermedia se importe con FKs canónicas (_a_id, _b_id) y atributos de negocio desplazados a pos 3+."""
    xmi_mn_recursive = """<?xml version="1.0" encoding="utf-8"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1">
  <xmi:Documentation exporter="Enterprise Architect" exporterVersion="6.5"/>
  <uml:Model xmi:type="uml:Model" name="TaxonomyModel">
    <packagedElement xmi:type="uml:Package" xmi:id="EAID_PACKAGE_1" name="TaxonomyModel">
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_CAT" name="Categoria">
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_CAT_ID" name="id: UUID"/>
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_CAT_NOM" name="nombre: TEXT"/>
      </packagedElement>
      <packagedElement xmi:type="uml:AssociationClass" xmi:id="EAID_CAT_REL" name="CategoriaRelation">
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_CR_ID" name="id: UUID"/>
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_CR_FA" name="categoria_a_id: UUID"/>
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_CR_FB" name="categoria_b_id: UUID"/>
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_CR_PROF" name="profundidad: INTEGER"/>
        <memberEnd xmi:idref="EAID_END_TGT"/>
        <memberEnd xmi:idref="EAID_END_SRC"/>
        <ownedEnd xmi:type="uml:Property" xmi:id="EAID_END_TGT" type="EAID_CAT">
          <type xmi:idref="EAID_CAT"/>
          <lowerValue xmi:type="uml:LiteralInteger" value="0"/>
          <upperValue xmi:type="uml:LiteralUnlimitedNatural" value="*"/>
        </ownedEnd>
        <ownedEnd xmi:type="uml:Property" xmi:id="EAID_END_SRC" type="EAID_CAT">
          <type xmi:idref="EAID_CAT"/>
          <lowerValue xmi:type="uml:LiteralInteger" value="0"/>
          <upperValue xmi:type="uml:LiteralUnlimitedNatural" value="*"/>
        </ownedEnd>
      </packagedElement>
    </packagedElement>
  </uml:Model>
  <xmi:Extension extender="Enterprise Architect" extenderID="6.5">
    <connectors>
      <connector xmi:idref="EAID_CAT_REL">
        <source xmi:idref="EAID_CAT"><model type="Class"/><type multiplicity="0..*"/></source>
        <target xmi:idref="EAID_CAT"><model type="Class"/><type multiplicity="0..*"/></target>
        <properties ea_type="AssociationClass" direction="Unspecified"/>
      </connector>
    </connectors>
    <diagrams>
      <diagram xmi:id="EAID_DIAG_1">
        <model package="EAID_PACKAGE_1" localID="1" owner="EAID_PACKAGE_1"/>
        <elements>
          <element geometry="Left=100;Top=100;Right=260;Bottom=220;" subject="EAID_CAT"/>
          <element geometry="Left=350;Top=100;Right=550;Bottom=260;" subject="EAID_CAT_REL"/>
        </elements>
        <connectors>
          <connector xmi:idref="EAID_CAT_REL"/>
        </connectors>
      </diagram>
    </diagrams>
  </xmi:Extension>
</xmi:XMI>"""

    # 1. Importar el proyecto con M:N recursivo
    file_orig = io.BytesIO(xmi_mn_recursive.encode("utf-8"))
    res_orig = client.post(
        "/api/projects/import",
        files={"file": ("taxonomy.xmi", file_orig, "application/xml")},
    )
    assert res_orig.status_code == 201
    proj_id = res_orig.json()["id"]

    # 2. Consultar diagrama y verificar clases y relación puente
    diag_res = client.get(f"/api/projects/{proj_id}/diagram")
    assert diag_res.status_code == 200
    diag = diag_res.json()

    assert len(diag["classes"]) == 2
    classes_by_name = {c["name"]: c for c in diag["classes"]}
    assert "Categoria" in classes_by_name
    assert "CategoriaRelation" in classes_by_name

    cat_cls = classes_by_name["Categoria"]
    bridge_cls = classes_by_name["CategoriaRelation"]

    # Verificar relación M:N reflexiva con puente CategoriaRelation
    assert len(diag["relations"]) == 1
    rel = diag["relations"][0]
    assert rel["source"]["class_id"] == cat_cls["id"]
    assert rel["target"]["class_id"] == cat_cls["id"]
    assert rel["bridge"] is not None
    assert rel["bridge"]["class_id"] == bridge_cls["id"]

    # Verificar orden y nombres canónicos de atributos en CategoriaRelation:
    # 0: id (PK)
    # 1: categoria_a_id (FK)
    # 2: categoria_b_id (FK)
    # 3: profundidad (INTEGER)
    attrs = sorted(bridge_cls["attributes"], key=lambda a: a["position"])
    assert len(attrs) == 4
    assert [a["position"] for a in attrs] == [0, 1, 2, 3]

    assert attrs[0]["name"] == "id"
    assert attrs[0]["is_primary_key"] is True

    assert attrs[1]["name"] == "categoria_a_id"
    assert attrs[1]["is_foreign_key"] is True
    assert attrs[1]["referenced_class_id"] == cat_cls["id"]

    assert attrs[2]["name"] == "categoria_b_id"
    assert attrs[2]["is_foreign_key"] is True
    assert attrs[2]["referenced_class_id"] == cat_cls["id"]

    assert attrs[3]["name"] == "profundidad"
    assert attrs[3]["data_type"] == "INTEGER"
    assert attrs[3]["is_foreign_key"] is False
    assert attrs[3]["is_primary_key"] is False

    # 3. Exportar a XMI
    export_res = client.get(f"/api/projects/{proj_id}/export")
    assert export_res.status_code == 200
    exported_xml = export_res.text
    assert "<xmi:XMI" in exported_xml
    assert "CategoriaRelation" in exported_xml

    # 4. Reimportar el XMI exportado
    file_reimport = io.BytesIO(exported_xml.encode("utf-8"))
    res_reimport = client.post(
        "/api/projects/import",
        files={"file": ("reimported_taxonomy.xmi", file_reimport, "application/xml")},
    )
    assert res_reimport.status_code == 201
    reimport_proj_id = res_reimport.json()["id"]

    # 5. Validar diagrama reimportado
    reimport_diag_res = client.get(f"/api/projects/{reimport_proj_id}/diagram")
    assert reimport_diag_res.status_code == 200
    reimport_diag = reimport_diag_res.json()

    assert len(reimport_diag["classes"]) == 2
    reimport_bridge = next(c for c in reimport_diag["classes"] if c["name"] == "CategoriaRelation")
    reimport_attrs = sorted(reimport_bridge["attributes"], key=lambda a: a["position"])

    assert len(reimport_attrs) == 4
    assert [a["position"] for a in reimport_attrs] == [0, 1, 2, 3]
    assert reimport_attrs[0]["name"] == "id"
    assert reimport_attrs[1]["name"] == "categoria_a_id"
    assert reimport_attrs[1]["is_foreign_key"] is True
    assert reimport_attrs[2]["name"] == "categoria_b_id"
    assert reimport_attrs[2]["is_foreign_key"] is True
    assert reimport_attrs[3]["name"] == "profundidad"
    assert reimport_attrs[3]["is_foreign_key"] is False




