from uuid import uuid4
import pytest

from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramAttributeSnapshotDto,
    DiagramClassSnapshotDto,
    DiagramRelationBridgeSnapshotDto,
    DiagramRelationEndpointSnapshotDto,
    DiagramRelationSnapshotDto,
)
from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.enums.diagram_cardinality import (
    DiagramCardinality,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)
from app.modules.projects.application.services.xmi_project_exporter import (
    XmiProjectExporter,
)
from app.modules.projects.application.services.xmi_project_importer import (
    XmiProjectImporter,
)
from app.modules.projects.application.services.xmi_dtos import (
    XMIRelationDefinition,
)
from app.modules.projects.domain.exceptions import InvalidProjectFileException


SAMPLE_XMI_21 = """<?xml version="1.0" encoding="utf-8"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1">
  <xmi:Documentation exporter="Enterprise Architect" exporterVersion="6.5"/>
  <uml:Model xmi:type="uml:Model" name="ECommerce System">
    <packagedElement xmi:type="uml:Package" xmi:id="EAID_PACKAGE_1" name="ECommerce System">
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_CLASS_CATEGORY" name="Categoria">
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_ATTR_CAT_ID" name="id: uuid"/>
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_ATTR_CAT_NAME" name="nombre: text"/>
      </packagedElement>
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_CLASS_PRODUCT" name="Producto">
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_ATTR_PROD_ID" name="id"/>
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_ATTR_PROD_NAME" name="titulo: string"/>
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_ATTR_PROD_PRICE" name="precio: decimal"/>
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_ATTR_PROD_CAT_FK" name="categoria_id: uuid"/>
      </packagedElement>
      <packagedElement xmi:type="uml:Association" xmi:id="EAID_ASSOC_CAT_PROD" name="Pertenece">
        <memberEnd xmi:idref="EAID_END_CAT"/>
        <memberEnd xmi:idref="EAID_END_PROD"/>
        <ownedEnd xmi:type="uml:Property" xmi:id="EAID_END_CAT" type="EAID_CLASS_CATEGORY">
          <lowerValue xmi:type="uml:LiteralInteger" value="1"/>
          <upperValue xmi:type="uml:LiteralUnlimitedNatural" value="1"/>
        </ownedEnd>
        <ownedEnd xmi:type="uml:Property" xmi:id="EAID_END_PROD" type="EAID_CLASS_PRODUCT">
          <lowerValue xmi:type="uml:LiteralInteger" value="0"/>
          <upperValue xmi:type="uml:LiteralUnlimitedNatural" value="*"/>
        </ownedEnd>
      </packagedElement>
    </packagedElement>
  </uml:Model>
  <xmi:Extension extender="Enterprise Architect" extenderID="6.5">
    <diagrams>
      <diagram xmi:id="EAID_DIAGRAM_1">
        <elements>
          <element geometry="Left=120;Top=100;Right=300;Bottom=240;" subject="EAID_CLASS_CATEGORY"/>
          <element geometry="Left=450;Top=100;Right=630;Bottom=240;" subject="EAID_CLASS_PRODUCT"/>
        </elements>
      </diagram>
    </diagrams>
  </xmi:Extension>
</xmi:XMI>
"""


def test_xmi_importer_parses_classes_and_geometry():
    importer = XmiProjectImporter()
    pkg = importer.parse(SAMPLE_XMI_21)

    assert pkg.name == "ECommerce System"
    assert len(pkg.classes) == 2

    # Verificar categoría
    cat = next(c for c in pkg.classes if c.name == "Categoria")
    assert cat.position_x == 120.0
    assert cat.position_y == 100.0
    # La PK 'id: uuid' debe haber sido descartada, dejando solo 'nombre'
    assert len(cat.attributes) == 1
    assert cat.attributes[0].parsed_name == "nombre"
    assert cat.attributes[0].data_type == DiagramAttributeDataType.TEXT

    # Verificar producto
    prod = next(c for c in pkg.classes if c.name == "Producto")
    assert prod.position_x == 450.0
    assert prod.position_y == 100.0
    # 'id' descartado, 'categoria_id' descartado por coincidir con la asociación
    attr_names = [a.parsed_name for a in prod.attributes]
    assert "titulo" in attr_names
    assert "precio" in attr_names
    assert "id" not in attr_names
    assert "categoria_id" not in attr_names

    # Verificar tipos normalizados
    titulo_attr = next(a for a in prod.attributes if a.parsed_name == "titulo")
    precio_attr = next(a for a in prod.attributes if a.parsed_name == "precio")
    assert titulo_attr.data_type == DiagramAttributeDataType.TEXT
    assert precio_attr.data_type == DiagramAttributeDataType.DECIMAL

    # Verificar relación
    assert len(pkg.relations) == 1
    rel = pkg.relations[0]
    assert rel.relation_type == DiagramRelationType.ASSOCIATION
    assert rel.source_ea_id == "EAID_CLASS_CATEGORY"
    assert rel.target_ea_id == "EAID_CLASS_PRODUCT"
    assert rel.source_cardinality == DiagramCardinality.EXACTLY_ONE
    assert rel.target_cardinality == DiagramCardinality.ZERO_OR_MORE


def test_xmi_importer_grid_layout_fallback_when_no_geometry():
    no_geom_xml = """<?xml version="1.0" encoding="utf-8"?>
    <xmi:XMI xmi:version="2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1">
      <uml:Model name="Fallback Model">
        <packagedElement xmi:type="uml:Class" xmi:id="C1" name="User"/>
        <packagedElement xmi:type="uml:Class" xmi:id="C2" name="Order"/>
        <packagedElement xmi:type="uml:Class" xmi:id="C3" name="Item"/>
        <packagedElement xmi:type="uml:Class" xmi:id="C4" name="Payment"/>
      </uml:Model>
    </xmi:XMI>
    """
    importer = XmiProjectImporter()
    pkg = importer.parse(no_geom_xml)

    assert len(pkg.classes) == 4
    assert pkg.classes[0].position_x == 60.0
    assert pkg.classes[0].position_y == 60.0
    assert pkg.classes[1].position_x == 340.0
    assert pkg.classes[1].position_y == 60.0
    assert pkg.classes[3].position_x == 60.0
    assert pkg.classes[3].position_y == 300.0


def test_xmi_importer_raises_on_invalid_xml_or_no_classes():
    importer = XmiProjectImporter()

    with pytest.raises(InvalidProjectFileException, match="no tiene un formato válido"):
        importer.parse("esto no es un xml")

    empty_xml = """<xmi:XMI xmi:version="2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1">
      <uml:Model name='Empty'/>
    </xmi:XMI>"""
    with pytest.raises(InvalidProjectFileException, match="no contiene un diagrama de clases"):
        importer.parse(empty_xml)


def test_xmi_exporter_generates_valid_xmi_21():
    exporter = XmiProjectExporter()

    class1_id = uuid4()
    class2_id = uuid4()
    rel_id = uuid4()

    classes = [
        DiagramClassSnapshotDto(
            id=class1_id,
            name="Cliente",
            position_x=100.0,
            position_y=150.0,
            attributes=[
                DiagramAttributeSnapshotDto(
                    id=uuid4(),
                    name="id",
                    data_type="UUID",
                    position=0,
                    is_primary_key=True,
                    is_nullable=False,
                ),
                DiagramAttributeSnapshotDto(
                    id=uuid4(),
                    name="email",
                    data_type="TEXT",
                    position=1,
                    is_primary_key=False,
                    is_nullable=False,
                ),
            ],
        ),
        DiagramClassSnapshotDto(
            id=class2_id,
            name="Factura",
            position_x=400.0,
            position_y=150.0,
            attributes=[
                DiagramAttributeSnapshotDto(
                    id=uuid4(),
                    name="monto",
                    data_type="DECIMAL",
                    position=1,
                    is_primary_key=False,
                    is_nullable=False,
                ),
            ],
        ),
    ]

    relations = [
        DiagramRelationSnapshotDto(
            id=rel_id,
            name="Emite",
            relation_type="ASSOCIATION",
            source=DiagramRelationEndpointSnapshotDto(class_id=class1_id, handle="right-center"),
            target=DiagramRelationEndpointSnapshotDto(class_id=class2_id, handle="left-center"),
            source_cardinality="1",
            target_cardinality="0..*",
            bridge=None,
        )
    ]

    xml_out = exporter.export("Billing System", classes, relations)

    assert "xmi:version=\"2.1\"" in xml_out
    assert 'exporter="Enterprise Architect"' in xml_out
    assert 'name="Billing System"' in xml_out
    assert 'name="Cliente"' in xml_out
    assert 'name="Factura"' in xml_out
    assert 'name="email: TEXT"' in xml_out
    assert 'name="monto: DECIMAL"' in xml_out
    assert 'name="Emite"' in xml_out
    assert 'Left=100;Top=150;' in xml_out
    assert 'Left=400;Top=150;' in xml_out

    # Verificaciones de compatibilidad con Enterprise Architect
    assert '<model package="EAID_PACKAGE_1" localID="1" owner="EAID_PACKAGE_1"' in xml_out
    assert f'<type xmi:idref="EAID_{class1_id.hex.upper()}"' in xml_out
    assert f'<type xmi:idref="EAID_{class2_id.hex.upper()}"' in xml_out
    assert '<connectors>' in xml_out
    assert f'<connector xmi:idref="EAID_{rel_id.hex.upper()}"' in xml_out
    assert 'ea_type="Association"' in xml_out
    assert '<labels lb="1" rb="0..*" mt="Emite"/>' in xml_out

    # Verificar que el importador reparsea con las cardinalidades en la orientación correcta
    importer = XmiProjectImporter()
    pkg = importer.parse(xml_out)
    assert len(pkg.relations) == 1
    parsed_rel = pkg.relations[0]
    assert parsed_rel.source_cardinality == DiagramCardinality.EXACTLY_ONE
    assert parsed_rel.target_cardinality == DiagramCardinality.ZERO_OR_MORE
    assert parsed_rel.source_ea_id == f"EAID_{class1_id.hex.upper()}"
    assert parsed_rel.target_ea_id == f"EAID_{class2_id.hex.upper()}"


def test_xmi_exporter_generates_valid_generalization():
    exporter = XmiProjectExporter()
    importer = XmiProjectImporter()

    parent_id = uuid4()
    child_id = uuid4()
    gen_id = uuid4()

    classes = [
        DiagramClassSnapshotDto(
            id=parent_id,
            name="Persona",
            position_x=100.0,
            position_y=100.0,
            attributes=[
                DiagramAttributeSnapshotDto(
                    id=uuid4(),
                    name="nombre",
                    data_type="TEXT",
                    position=0,
                    is_primary_key=False,
                    is_nullable=False,
                )
            ],
        ),
        DiagramClassSnapshotDto(
            id=child_id,
            name="Empleado",
            position_x=100.0,
            position_y=300.0,
            attributes=[
                DiagramAttributeSnapshotDto(
                    id=uuid4(),
                    name="salario",
                    data_type="DECIMAL",
                    position=0,
                    is_primary_key=False,
                    is_nullable=False,
                )
            ],
        ),
    ]

    relations = [
        DiagramRelationSnapshotDto(
            id=gen_id,
            name="Herencia",
            relation_type="GENERALIZATION",
            source=DiagramRelationEndpointSnapshotDto(class_id=child_id, handle="top-center"),
            target=DiagramRelationEndpointSnapshotDto(class_id=parent_id, handle="bottom-center"),
            source_cardinality=None,
            target_cardinality=None,
            bridge=None,
        )
    ]

    xml_out = exporter.export("Empresa", classes, relations)

    assert f'general="EAID_{parent_id.hex.upper()}"' in xml_out
    assert 'ea_type="Generalization"' in xml_out
    assert 'direction="Source -&gt; Destination"' in xml_out

    # Verificar que el importador lo parsea correctamente
    pkg = importer.parse(xml_out)
    assert len(pkg.classes) == 2
    assert len(pkg.relations) == 1
    rel = pkg.relations[0]
    assert rel.relation_type == DiagramRelationType.GENERALIZATION
    assert rel.source_ea_id == f"EAID_{child_id.hex.upper()}"
    assert rel.target_ea_id == f"EAID_{parent_id.hex.upper()}"


def test_xmi_exporter_and_importer_many_to_many_association_class():
    exporter = XmiProjectExporter()
    importer = XmiProjectImporter()

    author_id = uuid4()
    book_id = uuid4()
    bridge_id = uuid4()
    rel_id = uuid4()

    classes = [
        DiagramClassSnapshotDto(
            id=author_id,
            name="Author",
            position_x=100.0,
            position_y=100.0,
            attributes=[
                DiagramAttributeSnapshotDto(
                    id=uuid4(),
                    name="name",
                    data_type="TEXT",
                    position=1,
                    is_primary_key=False,
                    is_nullable=False,
                )
            ],
        ),
        DiagramClassSnapshotDto(
            id=book_id,
            name="Book",
            position_x=500.0,
            position_y=100.0,
            attributes=[
                DiagramAttributeSnapshotDto(
                    id=uuid4(),
                    name="title",
                    data_type="TEXT",
                    position=1,
                    is_primary_key=False,
                    is_nullable=False,
                )
            ],
        ),
        DiagramClassSnapshotDto(
            id=bridge_id,
            name="AuthorBook",
            position_x=300.0,
            position_y=300.0,
            attributes=[
                DiagramAttributeSnapshotDto(
                    id=uuid4(),
                    name="author_id",
                    data_type="UUID",
                    position=1,
                    is_primary_key=False,
                    is_nullable=False,
                ),
                DiagramAttributeSnapshotDto(
                    id=uuid4(),
                    name="book_id",
                    data_type="UUID",
                    position=2,
                    is_primary_key=False,
                    is_nullable=False,
                ),
                DiagramAttributeSnapshotDto(
                    id=uuid4(),
                    name="royalty_percentage",
                    data_type="DECIMAL",
                    position=3,
                    is_primary_key=False,
                    is_nullable=False,
                ),
            ],
        ),
    ]

    relations = [
        DiagramRelationSnapshotDto(
            id=rel_id,
            name="Writes",
            relation_type="ASSOCIATION",
            source=DiagramRelationEndpointSnapshotDto(class_id=author_id, handle="right-center"),
            target=DiagramRelationEndpointSnapshotDto(class_id=book_id, handle="left-center"),
            source_cardinality="0..*",
            target_cardinality="0..*",
            bridge=DiagramRelationBridgeSnapshotDto(class_id=bridge_id, handle="top-center"),
        )
    ]

    xml_out = exporter.export("Publishing", classes, relations)

    # 1. Verificar que la clase puente se serializa como AssociationClass
    bridge_eaid = f"EAID_{bridge_id.hex.upper()}"
    author_eaid = f"EAID_{author_id.hex.upper()}"
    book_eaid = f"EAID_{book_id.hex.upper()}"

    assert f'<packagedElement xmi:type="uml:AssociationClass" xmi:id="{bridge_eaid}" name="AuthorBook"' in xml_out
    assert 'ea_type="AssociationClass"' in xml_out
    assert f'<connector xmi:idref="{bridge_eaid}"' in xml_out
    assert f'<element geometry="Left=300;Top=300;Right=480;Bottom=440;" subject="{bridge_eaid}"' in xml_out

    # 2. Verificar que el importador reconoce la clase y la relación M:N con puente
    pkg = importer.parse(xml_out)
    assert len(pkg.classes) == 3
    class_names = {c.name for c in pkg.classes}
    assert class_names == {"Author", "Book", "AuthorBook"}

    bridge_class_parsed = next(c for c in pkg.classes if c.name == "AuthorBook")
    assert bridge_class_parsed.position_x == 300.0
    assert bridge_class_parsed.position_y == 300.0
    # royalty_percentage debe conservarse (author_id y book_id filtrados por foreign key redundante)
    attr_names = [a.parsed_name for a in bridge_class_parsed.attributes]
    assert "royalty_percentage" in attr_names
    assert "author_id" not in attr_names
    assert "book_id" not in attr_names

    assert len(pkg.relations) == 1
    rel = pkg.relations[0]
    assert rel.relation_type == DiagramRelationType.ASSOCIATION
    assert rel.source_ea_id == author_eaid
    assert rel.target_ea_id == book_eaid
    assert rel.bridge_ea_id == bridge_eaid


def test_xmi_importer_handles_enterprise_architect_negative_y_and_guid_braces():
    """Verifica que el importador resuelva GUIDs con llaves de EA y coordenadas Y negativas respetando el orden vertical."""
    ea_xmi = """<?xml version="1.0" encoding="utf-8"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1">
  <xmi:Documentation exporter="Enterprise Architect" exporterVersion="6.5"/>
  <uml:Model name="EA Model">
    <packagedElement xmi:type="uml:Package" xmi:id="EAID_PKG_1" name="EA Package">
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_65275AC9_F1E8_4ea7_8E4B_2B7A8B733076" name="ParentClass">
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_ATTR_1" name="title: text"/>
      </packagedElement>
      <packagedElement xmi:type="uml:Class" xmi:id="EAID_488C222E_A430_4648_9F8C_03761E4FE923" name="ChildClass">
        <ownedAttribute xmi:type="uml:Property" xmi:id="EAID_ATTR_2" name="detail: text"/>
      </packagedElement>
    </packagedElement>
  </uml:Model>
  <xmi:Extension extender="Enterprise Architect" extenderID="6.5">
    <diagrams>
      <diagram xmi:id="EAID_DIAG_1">
        <elements>
          <!-- En EA, Top=-100 está en la parte superior y Top=-400 está en la parte inferior -->
          <element geometry="Left=150;Top=-100;Right=270;Bottom=-170;" subject="{65275AC9-F1E8-4ea7-8E4B-2B7A8B733076}"/>
          <element geometry="Left=150;Top=-400;Right=270;Bottom=-470;" subject="{488C222E-A430-4648-9F8C-03761E4FE923}"/>
        </elements>
      </diagram>
    </diagrams>
  </xmi:Extension>
</xmi:XMI>"""

    importer = XmiProjectImporter()
    pkg = importer.parse(ea_xmi)

    assert len(pkg.classes) == 2
    parent = next(c for c in pkg.classes if c.name == "ParentClass")
    child = next(c for c in pkg.classes if c.name == "ChildClass")

    # Ambas clases deben haber resuelto sus coordenadas por el GUID normalizado
    assert parent.position_x >= 40.0
    assert child.position_x >= 40.0

    # ParentClass (Top=-100 en EA) DEBE quedar arriba de ChildClass (Top=-400 en EA)
    assert parent.position_y < child.position_y
    # La separación vertical debe ser suficiente y no estar encimadas
    assert (child.position_y - parent.position_y) >= 200.0


def test_xmi_importer_anti_overlap_scaling_for_dense_diagrams():
    """Verifica que diagramas con clases muy apretadas (como las cajas angostas de EA) se expandan para no solaparse."""
    dense_xmi = """<?xml version="1.0" encoding="utf-8"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1">
  <uml:Model name="Dense Model">
    <packagedElement xmi:type="uml:Class" xmi:id="C1" name="LeftBox">
      <ownedAttribute xmi:type="uml:Property" xmi:id="A1" name="a: text"/>
    </packagedElement>
    <packagedElement xmi:type="uml:Class" xmi:id="C2" name="RightBox">
      <ownedAttribute xmi:type="uml:Property" xmi:id="A2" name="b: text"/>
    </packagedElement>
  </uml:Model>
  <xmi:Extension extender="Enterprise Architect">
    <diagrams>
      <diagram xmi:id="D1">
        <elements>
          <!-- Separación en X de sólo 120px (en EA cajas de 100px caben, pero en web colisionan) -->
          <element geometry="Left=100;Top=100;Right=200;Bottom=170;" subject="C1"/>
          <element geometry="Left=220;Top=100;Right=320;Bottom=170;" subject="C2"/>
        </elements>
      </diagram>
    </diagrams>
  </xmi:Extension>
</xmi:XMI>"""

    importer = XmiProjectImporter()
    pkg = importer.parse(dense_xmi)

    left_box = next(c for c in pkg.classes if c.name == "LeftBox")
    right_box = next(c for c in pkg.classes if c.name == "RightBox")

    # Deben estar alineadas en Y
    assert left_box.position_y == right_box.position_y
    # La distancia en X debe haberse escalado proporcionalmente a >= 280px para evitar solapamiento visual
    dx = right_box.position_x - left_box.position_x
    assert dx >= 280.0


def test_xmi_importer_parses_enterprise_architect_xmi_11_uml_13():
    """Verifica que el importador procese archivos XMI 1.1 / UML 1.3 nativos de Enterprise Architect."""
    xmi_11 = """<?xml version="1.0" encoding="windows-1252" standalone="no" ?>
<XMI xmi.version="1.1" xmlns:UML="omg.org/UML1.3" timestamp="2026-09-21 12:28:46">
  <XMI.header>
    <XMI.documentation>
      <XMI.exporter>Enterprise Architect</XMI.exporter>
      <XMI.exporterVersion>2.5</XMI.exporterVersion>
    </XMI.documentation>
  </XMI.header>
  <XMI.content>
    <UML:Model name="EA Model" xmi.id="MX_EAID_PACKAGE_1">
      <UML:Namespace.ownedElement>
        <!-- Clase técnica dummy de EA que DEBE ser descartada -->
        <UML:Class name="EARootClass" xmi.id="EAID_11111111_5487_4080_A7F4_41526CB0AA00"/>
        <UML:Package name="Nuevo proyecto 2" xmi.id="EAPK_PACKAGE_1">
          <UML:Namespace.ownedElement>
            <UML:Class name="Compra" xmi.id="EAID_212370D4BC5D48BB9F0C53B7C40B5F99">
              <UML:Classifier.feature>
                <UML:Attribute name="fecha_compra: TIMESTAMP"/>
                <UML:Attribute name="id: UUID"/>
                <UML:Attribute name="proveedor_id: UUID"/>
              </UML:Classifier.feature>
            </UML:Class>
            <UML:Class name="CompraProducto" xmi.id="EAID_630BE12DDC4649B38C671226B4E49FE3">
              <UML:Classifier.feature>
                <UML:Attribute name="cantidad: INTEGER"/>
                <UML:Attribute name="compra_id: UUID"/>
                <UML:Attribute name="id: UUID"/>
                <UML:Attribute name="precio_unitario: DECIMAL"/>
                <UML:Attribute name="producto_id: UUID"/>
                <UML:Attribute name="total: DECIMAL"/>
              </UML:Classifier.feature>
            </UML:Class>
            <UML:Class name="Proveedor" xmi.id="EAID_AEBF4FA4D1EA461B88430793AEFAAE72">
              <UML:Classifier.feature>
                <UML:Attribute name="contacto: TEXT"/>
                <UML:Attribute name="id: UUID"/>
                <UML:Attribute name="nombre: TEXT"/>
              </UML:Classifier.feature>
            </UML:Class>
            <UML:Class name="Producto" xmi.id="EAID_EE28DE3708494BC6BA946F2B8B55F956">
              <UML:Classifier.feature>
                <UML:Attribute name="id: UUID"/>
                <UML:Attribute name="nombre"/>
                <UML:Attribute name="precio: INTEGER"/>
                <UML:Attribute name="stock: INTEGER"/>
              </UML:Classifier.feature>
            </UML:Class>
            <UML:Association xmi.id="EAID_A52B96D9_4602_480a_BCAB_FA41740BC07D">
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
            <UML:Association name="pertenece" xmi.id="EAID_E7AF290A9627465B983255A96DDCD69D">
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
          </UML:Namespace.ownedElement>
        </UML:Package>
      </UML:Namespace.ownedElement>
    </UML:Model>
    <UML:Diagram name="Nuevo proyecto 2" xmi.id="EAID_DIAGRAM_1">
      <UML:Diagram.element>
        <UML:DiagramElement geometry="Left=613;Top=244;Right=765;Bottom=358;" subject="EAID_630BE12DDC4649B38C671226B4E49FE3"/>
        <UML:DiagramElement geometry="Left=1221;Top=10;Right=1401;Bottom=150;" subject="EAID_AEBF4FA4D1EA461B88430793AEFAAE72"/>
        <UML:DiagramElement geometry="Left=858;Top=45;Right=1022;Bottom=115;" subject="EAID_212370D4BC5D48BB9F0C53B7C40B5F99"/>
        <UML:DiagramElement geometry="Left=850;Top=488;Right=1030;Bottom=628;" subject="EAID_EE28DE3708494BC6BA946F2B8B55F956"/>
      </UML:Diagram.element>
    </UML:Diagram>
  </XMI.content>
</XMI>"""

    importer = XmiProjectImporter()
    pkg = importer.parse(xmi_11)

    # 1. Nombre extraído del paquete interno ignorando EA Model
    assert pkg.name == "Nuevo proyecto 2"

    # 2. EARootClass descartada, quedan exactamente 4 clases
    assert len(pkg.classes) == 4
    class_names = {c.name for c in pkg.classes}
    assert class_names == {"Compra", "CompraProducto", "Proveedor", "Producto"}
    assert "EARootClass" not in class_names

    # 3. Atributos extraídos correctamente desde UML:Classifier.feature
    compra = next(c for c in pkg.classes if c.name == "Compra")
    compra_attrs = [a.parsed_name for a in compra.attributes]
    assert compra_attrs == ["fecha_compra"]

    prod = next(c for c in pkg.classes if c.name == "Producto")
    prod_attrs = {a.parsed_name: a.data_type for a in prod.attributes}
    assert "nombre" in prod_attrs
    # Atributo sin tipo explícito (solo 'nombre') debe mapear a TEXT y ser nullable
    assert prod_attrs["nombre"] == DiagramAttributeDataType.TEXT
    nombre_attr = next(a for a in prod.attributes if a.parsed_name == "nombre")
    assert nombre_attr.is_nullable is True

    # 4. Relaciones extraídas desde UML:Association y UML:AssociationEnd
    assert len(pkg.relations) == 2
    # Asociación M:N con clase intermedia CompraProducto
    mn_rel = next(r for r in pkg.relations if r.bridge_ea_id is not None)
    assert mn_rel.source_cardinality == DiagramCardinality.ZERO_OR_MORE
    assert mn_rel.target_cardinality == DiagramCardinality.ZERO_OR_MORE
    assert mn_rel.bridge_ea_id == "EAID_630BE12DDC4649B38C671226B4E49FE3"

    # Asociación 1:N pertenece (Proveedor -> Compra)
    on_rel = next(r for r in pkg.relations if r.name == "pertenece")
    assert on_rel.source_ea_id == "EAID_AEBF4FA4D1EA461B88430793AEFAAE72"
    assert on_rel.target_ea_id == "EAID_212370D4BC5D48BB9F0C53B7C40B5F99"
    assert on_rel.source_cardinality == DiagramCardinality.EXACTLY_ONE
    assert on_rel.target_cardinality == DiagramCardinality.ZERO_OR_MORE


def test_xmi_importer_raises_when_association_lacks_cardinality():
    """Verifica que se lance InvalidProjectFileException si una asociación carece de cardinalidades."""
    xmi_missing_card = """<?xml version="1.0" encoding="utf-8"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1">
  <uml:Model name="Missing Cardinality">
    <packagedElement xmi:type="uml:Class" xmi:id="C1" name="User"/>
    <packagedElement xmi:type="uml:Class" xmi:id="C2" name="Profile"/>
    <packagedElement xmi:type="uml:Association" xmi:id="A1" name="HasProfile">
      <memberEnd xmi:idref="E1"/>
      <memberEnd xmi:idref="E2"/>
      <!-- Extremos sin lowerValue ni upperValue -->
      <ownedEnd xmi:id="E1" type="C1"/>
      <ownedEnd xmi:id="E2" type="C2"/>
    </packagedElement>
  </uml:Model>
</xmi:XMI>"""

    importer = XmiProjectImporter()
    with pytest.raises(InvalidProjectFileException, match="no tiene cardinalidades definidas"):
        importer.parse(xmi_missing_card)


def test_xmi_importer_directional_handle_selection():
    """Verifica que el importador asigne handles direccionales acordes a la posición relativa."""
    xmi = """<?xml version="1.0" encoding="utf-8"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1">
  <uml:Model name="HandlesTest">
    <packagedElement xmi:type="uml:Class" xmi:id="C_TOP" name="Producto"/>
    <packagedElement xmi:type="uml:Class" xmi:id="C_BOT" name="Categoria"/>
    <packagedElement xmi:type="uml:Association" xmi:id="A_VERT" name="pertenece">
      <memberEnd xmi:idref="E1"/>
      <memberEnd xmi:idref="E2"/>
      <ownedEnd xmi:id="E1" type="C_TOP">
        <lowerValue xmi:type="uml:LiteralInteger" value="1"/>
        <upperValue xmi:type="uml:LiteralUnlimitedNatural" value="*"/>
      </ownedEnd>
      <ownedEnd xmi:id="E2" type="C_BOT">
        <lowerValue xmi:type="uml:LiteralInteger" value="1"/>
        <upperValue xmi:type="uml:LiteralUnlimitedNatural" value="1"/>
      </ownedEnd>
    </packagedElement>
  </uml:Model>
  <xmi:Extension extender="Enterprise Architect">
    <diagrams>
      <diagram xmi:id="D1">
        <elements>
          <!-- Producto arriba (Top=100), Categoria abajo (Top=500) -->
          <element subject="C_TOP" geometry="Left=200;Top=100;Right=380;Bottom=240;"/>
          <element subject="C_BOT" geometry="Left=200;Top=500;Right=380;Bottom=640;"/>
        </elements>
      </diagram>
    </diagrams>
  </xmi:Extension>
</xmi:XMI>"""

    importer = XmiProjectImporter()
    pkg = importer.parse(xmi)

    assert len(pkg.relations) == 1
    rel = pkg.relations[0]
    # C_TOP (Producto arriba) debe tener handle en BOTTOM
    assert rel.source_handle.value.startswith("BOTTOM_")
    # C_BOT (Categoria abajo) debe tener handle en TOP
    assert rel.target_handle.value.startswith("TOP_")


def test_xmi_importer_avoids_handle_collisions_on_multiple_relations():
    """Verifica que múltiples relaciones desde una misma clase se distribuyan en handles distintos."""
    xmi = """<?xml version="1.0" encoding="utf-8"?>
<xmi:XMI xmi:version="2.1" xmlns:uml="http://schema.omg.org/spec/UML/2.1" xmlns:xmi="http://schema.omg.org/spec/XMI/2.1">
  <uml:Model name="CollisionTest">
    <packagedElement xmi:type="uml:Class" xmi:id="C_SRC" name="Origen"/>
    <packagedElement xmi:type="uml:Class" xmi:id="C_T1" name="Destino1"/>
    <packagedElement xmi:type="uml:Class" xmi:id="C_T2" name="Destino2"/>
    <packagedElement xmi:type="uml:Class" xmi:id="C_T3" name="Destino3"/>
    <packagedElement xmi:type="uml:Association" xmi:id="A1" name="rel1">
      <memberEnd xmi:idref="E1_1"/><memberEnd xmi:idref="E1_2"/>
      <ownedEnd xmi:id="E1_1" type="C_SRC"><lowerValue xmi:type="uml:LiteralInteger" value="1"/><upperValue xmi:type="uml:LiteralUnlimitedNatural" value="1"/></ownedEnd>
      <ownedEnd xmi:id="E1_2" type="C_T1"><lowerValue xmi:type="uml:LiteralInteger" value="1"/><upperValue xmi:type="uml:LiteralUnlimitedNatural" value="*"/></ownedEnd>
    </packagedElement>
    <packagedElement xmi:type="uml:Association" xmi:id="A2" name="rel2">
      <memberEnd xmi:idref="E2_1"/><memberEnd xmi:idref="E2_2"/>
      <ownedEnd xmi:id="E2_1" type="C_SRC"><lowerValue xmi:type="uml:LiteralInteger" value="1"/><upperValue xmi:type="uml:LiteralUnlimitedNatural" value="1"/></ownedEnd>
      <ownedEnd xmi:id="E2_2" type="C_T2"><lowerValue xmi:type="uml:LiteralInteger" value="1"/><upperValue xmi:type="uml:LiteralUnlimitedNatural" value="*"/></ownedEnd>
    </packagedElement>
    <packagedElement xmi:type="uml:Association" xmi:id="A3" name="rel3">
      <memberEnd xmi:idref="E3_1"/><memberEnd xmi:idref="E3_2"/>
      <ownedEnd xmi:id="E3_1" type="C_SRC"><lowerValue xmi:type="uml:LiteralInteger" value="1"/><upperValue xmi:type="uml:LiteralUnlimitedNatural" value="1"/></ownedEnd>
      <ownedEnd xmi:id="E3_2" type="C_T3"><lowerValue xmi:type="uml:LiteralInteger" value="1"/><upperValue xmi:type="uml:LiteralUnlimitedNatural" value="*"/></ownedEnd>
    </packagedElement>
  </uml:Model>
  <xmi:Extension extender="Enterprise Architect">
    <diagrams>
      <diagram xmi:id="D1">
        <elements>
          <element subject="C_SRC" geometry="Left=400;Top=100;Right=580;Bottom=240;"/>
          <element subject="C_T1" geometry="Left=100;Top=500;Right=280;Bottom=640;"/>
          <element subject="C_T2" geometry="Left=400;Top=500;Right=580;Bottom=640;"/>
          <element subject="C_T3" geometry="Left=700;Top=500;Right=880;Bottom=640;"/>
        </elements>
      </diagram>
    </diagrams>
  </xmi:Extension>
</xmi:XMI>"""

    importer = XmiProjectImporter()
    pkg = importer.parse(xmi)

    assert len(pkg.relations) == 3
    source_handles = {r.source_handle for r in pkg.relations}
    # Las 3 relaciones deben haber recibido handles distintos en la clase Origen
    assert len(source_handles) == 3


def test_xmi_exporter_outputs_diagram_connector_style_with_edge_and_offsets():
    """Verifica que el exportador incluya el elemento <style> con EDGE y offsets para EA."""
    from uuid import uuid4
    from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
        DiagramSnapshotDto,
        DiagramClassSnapshotDto,
        DiagramRelationSnapshotDto,
        DiagramRelationEndpointSnapshotDto,
    )
    from app.modules.projects.application.services.xmi_project_exporter import XmiProjectExporter


    c1_id = uuid4()
    c2_id = uuid4()
    r_id = uuid4()

    classes = [
        DiagramClassSnapshotDto(
            id=c1_id,
            name="Producto",
            position_x=100.0,
            position_y=100.0,
            attributes=[],
        ),
        DiagramClassSnapshotDto(
            id=c2_id,
            name="Categoria",
            position_x=100.0,
            position_y=500.0,
            attributes=[],
        ),
    ]

    relations = [
        DiagramRelationSnapshotDto(
            id=r_id,
            name="pertenece",
            relation_type="ASSOCIATION",
            source=DiagramRelationEndpointSnapshotDto(class_id=c1_id, handle="BOTTOM_CENTER"),
            target=DiagramRelationEndpointSnapshotDto(class_id=c2_id, handle="TOP_CENTER"),
            source_cardinality="1..*",
            target_cardinality="1",
            bridge=None,
        )
    ]

    exporter = XmiProjectExporter()
    xml_out = exporter.export(project_name="TestExport", classes=classes, relations=relations)


    # Verificar que el conector en <diagram><connectors> contiene el tag <style> con EDGE=1 (Bottom)
    assert 'EDGE=1;' in xml_out
    assert 'SX=' in xml_out
    assert 'EX=' in xml_out


def test_xmi_relation_definition_ignores_name_and_cardinalities_for_non_associative():
    """Verifica que XMIRelationDefinition fuerce nombre vacío y cardinalidades None si el tipo no es ASSOCIATION."""
    for rel_type in (
        DiagramRelationType.GENERALIZATION,
        DiagramRelationType.COMPOSITION,
        DiagramRelationType.AGGREGATION,
        DiagramRelationType.REALIZATION,
        DiagramRelationType.DEPENDENCY,
    ):
        rel = XMIRelationDefinition(
            ea_id="test_id",
            source_ea_id="src",
            target_ea_id="tgt",
            relation_type=rel_type,
            name="NombreQueDebeSerIgnorado",
            source_cardinality=DiagramCardinality.EXACTLY_ONE,
            target_cardinality=DiagramCardinality.ZERO_OR_MORE,
        )
        assert rel.name == ""
        assert rel.source_cardinality is None
        assert rel.target_cardinality is None

    # En ASSOCIATION sí se respeta el nombre y las cardinalidades
    assoc_rel = XMIRelationDefinition(
        ea_id="assoc_id",
        source_ea_id="src",
        target_ea_id="tgt",
        relation_type=DiagramRelationType.ASSOCIATION,
        name="AsociacionValida",
        source_cardinality=DiagramCardinality.EXACTLY_ONE,
        target_cardinality=DiagramCardinality.ZERO_OR_MORE,
    )
    assert assoc_rel.name == "AsociacionValida"
    assert assoc_rel.source_cardinality == DiagramCardinality.EXACTLY_ONE
    assert assoc_rel.target_cardinality == DiagramCardinality.ZERO_OR_MORE






