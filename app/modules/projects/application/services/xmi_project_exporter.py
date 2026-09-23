"""Servicio para generar documentos XML en formato XMI 2.1 compatibles con Enterprise Architect."""

import xml.dom.minidom
import xml.etree.ElementTree as ET
from uuid import UUID

from app.modules.diagram.application.ports.readers.diagram_snapshot_reader import (
    DiagramClassSnapshotDto,
    DiagramRelationSnapshotDto,
)


class XmiProjectExporter:
    """Genera representaciones XML conformes a OMG UML 2.1 (XMI 2.1) con geometría de Enterprise Architect."""

    def export(
        self,
        project_name: str,
        classes: list[DiagramClassSnapshotDto],
        relations: list[DiagramRelationSnapshotDto],
    ) -> str:
        """Serializa clases, atributos y relaciones a un string XML XMI 2.1."""
        clean_project_name = project_name.strip() or "Proyecto"

        # Elemento raíz XMI
        root = ET.Element(
            "xmi:XMI",
            {
                "xmi:version": "2.1",
                "xmlns:uml": "http://schema.omg.org/spec/UML/2.1",
                "xmlns:xmi": "http://schema.omg.org/spec/XMI/2.1",
            },
        )

        # Encabezado de documentación de Enterprise Architect
        ET.SubElement(
            root,
            "xmi:Documentation",
            {"exporter": "Enterprise Architect", "exporterVersion": "6.5"},
        )

        # Modelo UML
        model = ET.SubElement(
            root,
            "uml:Model",
            {"xmi:type": "uml:Model", "name": clean_project_name},
        )

        # Paquete contenedor
        package_id = "EAID_PACKAGE_1"
        package = ET.SubElement(
            model,
            "packagedElement",
            {
                "xmi:type": "uml:Package",
                "xmi:id": package_id,
                "name": clean_project_name,
            },
        )

        # Identificar relaciones que poseen clase intermedia (puente N:M)
        bridge_to_rel: dict[UUID, DiagramRelationSnapshotDto] = {}
        for rel in relations:
            if rel.bridge is not None:
                bridge_to_rel[rel.bridge.class_id] = rel

        # Clases y Atributos (incluyendo AssociationClass para clases puente)
        class_elements: dict[UUID, ET.Element] = {}
        for c in classes:
            class_eaid = f"EAID_{c.id.hex.upper()}"
            is_bridge = c.id in bridge_to_rel
            xmi_type = "uml:AssociationClass" if is_bridge else "uml:Class"

            class_elem = ET.SubElement(
                package,
                "packagedElement",
                {
                    "xmi:type": xmi_type,
                    "xmi:id": class_eaid,
                    "name": c.name,
                    "visibility": "public",
                },
            )
            class_elements[c.id] = class_elem

            for attr in c.attributes:
                attr_eaid = f"EAID_{attr.id.hex.upper()}"
                type_name = attr.data_type if attr.data_type else "TEXT"
                # Formato solicitado: "nombre: TIPO" para interoperabilidad bidireccional
                attr_display = f"{attr.name}: {type_name}"

                ET.SubElement(
                    class_elem,
                    "ownedAttribute",
                    {
                        "xmi:type": "uml:Property",
                        "xmi:id": attr_eaid,
                        "name": attr_display,
                        "visibility": "public",
                    },
                )

            # Si es AssociationClass, los extremos de la asociación residen dentro de ella
            if is_bridge:
                rel = bridge_to_rel[c.id]
                src_class_eaid = f"EAID_{rel.source.class_id.hex.upper()}"
                tgt_class_eaid = f"EAID_{rel.target.class_id.hex.upper()}"
                end_src_id = f"EAID_END_SRC_{rel.id.hex.upper()}"
                end_tgt_id = f"EAID_END_TGT_{rel.id.hex.upper()}"

                # En el metamodelo UML 2.1, memberEnd[0] es el extremo destino (Target/Supplier)
                # y memberEnd[1] es el extremo origen (Source/Client)
                ET.SubElement(class_elem, "memberEnd", {"xmi:idref": end_tgt_id})
                ET.SubElement(class_elem, "memberEnd", {"xmi:idref": end_src_id})

                owned_tgt = ET.SubElement(
                    class_elem,
                    "ownedEnd",
                    {
                        "xmi:type": "uml:Property",
                        "xmi:id": end_tgt_id,
                        "type": tgt_class_eaid,
                    },
                )
                ET.SubElement(owned_tgt, "type", {"xmi:idref": tgt_class_eaid})
                self._append_multiplicity(owned_tgt, rel.target_cardinality)

                owned_src = ET.SubElement(
                    class_elem,
                    "ownedEnd",
                    {
                        "xmi:type": "uml:Property",
                        "xmi:id": end_src_id,
                        "type": src_class_eaid,
                    },
                )
                ET.SubElement(owned_src, "type", {"xmi:idref": src_class_eaid})
                self._append_multiplicity(owned_src, rel.source_cardinality)

        # Relaciones
        for rel in relations:
            # Si tiene clase puente, ya fue serializada como uml:AssociationClass
            if rel.bridge is not None and rel.bridge.class_id in class_elements:
                continue

            rel_eaid = f"EAID_{rel.id.hex.upper()}"
            src_class_eaid = f"EAID_{rel.source.class_id.hex.upper()}"
            tgt_class_eaid = f"EAID_{rel.target.class_id.hex.upper()}"

            if rel.relation_type == "GENERALIZATION":
                src_class_elem = class_elements.get(rel.source.class_id)
                if src_class_elem is not None:
                    gen_elem = ET.SubElement(
                        src_class_elem,
                        "generalization",
                        {
                            "xmi:type": "uml:Generalization",
                            "xmi:id": rel_eaid,
                            "general": tgt_class_eaid,
                        },
                    )
                    ET.SubElement(gen_elem, "general", {"xmi:idref": tgt_class_eaid})
                else:
                    ET.SubElement(
                        package,
                        "packagedElement",
                        {
                            "xmi:type": "uml:Generalization",
                            "xmi:id": rel_eaid,
                            "specific": src_class_eaid,
                            "general": tgt_class_eaid,
                        },
                    )
            else:
                assoc_elem = ET.SubElement(
                    package,
                    "packagedElement",
                    {
                        "xmi:type": "uml:Association",
                        "xmi:id": rel_eaid,
                        "name": rel.name or "Asociación",
                    },
                )

                end_src_id = f"EAID_END_SRC_{rel.id.hex.upper()}"
                end_tgt_id = f"EAID_END_TGT_{rel.id.hex.upper()}"

                # En el metamodelo UML 2.1, memberEnd[0] es el extremo destino (Target/Supplier)
                # y memberEnd[1] es el extremo origen (Source/Client)
                ET.SubElement(assoc_elem, "memberEnd", {"xmi:idref": end_tgt_id})
                ET.SubElement(assoc_elem, "memberEnd", {"xmi:idref": end_src_id})

                # Atributos de agregación
                agg_src = {}
                agg_tgt = {}
                if rel.relation_type == "AGGREGATION":
                    agg_src["aggregation"] = "shared"
                elif rel.relation_type == "COMPOSITION":
                    agg_src["aggregation"] = "composite"

                owned_tgt = ET.SubElement(
                    assoc_elem,
                    "ownedEnd",
                    {
                        "xmi:type": "uml:Property",
                        "xmi:id": end_tgt_id,
                        "type": tgt_class_eaid,
                        **agg_tgt,
                    },
                )
                ET.SubElement(owned_tgt, "type", {"xmi:idref": tgt_class_eaid})
                self._append_multiplicity(owned_tgt, rel.target_cardinality)

                owned_src = ET.SubElement(
                    assoc_elem,
                    "ownedEnd",
                    {
                        "xmi:type": "uml:Property",
                        "xmi:id": end_src_id,
                        "type": src_class_eaid,
                        **agg_src,
                    },
                )
                ET.SubElement(owned_src, "type", {"xmi:idref": src_class_eaid})
                self._append_multiplicity(owned_src, rel.source_cardinality)

        # Extensión de diagramas de Enterprise Architect para visualización y geometría
        ext_elem = ET.SubElement(
            root,
            "xmi:Extension",
            {"extender": "Enterprise Architect", "extenderID": "6.5"},
        )

        # Conectores en la extensión de EA
        if relations:
            connectors_elem = ET.SubElement(ext_elem, "connectors")
            for rel in relations:
                src_class_eaid = f"EAID_{rel.source.class_id.hex.upper()}"
                tgt_class_eaid = f"EAID_{rel.target.class_id.hex.upper()}"

                is_bridge = rel.bridge is not None and rel.bridge.class_id in class_elements
                if is_bridge:
                    conn_eaid = f"EAID_{rel.bridge.class_id.hex.upper()}"
                    ea_type = "AssociationClass"
                else:
                    conn_eaid = f"EAID_{rel.id.hex.upper()}"
                    ea_type = "Association"

                conn_elem = ET.SubElement(
                    connectors_elem, "connector", {"xmi:idref": conn_eaid}
                )

                direction = "Unspecified"
                agg_val = "none"

                if rel.relation_type == "GENERALIZATION":
                    ea_type = "Generalization"
                    direction = "Source -> Destination"
                elif rel.relation_type == "AGGREGATION":
                    ea_type = "Aggregation"
                    agg_val = "shared"
                elif rel.relation_type == "COMPOSITION":
                    ea_type = "Aggregation"
                    agg_val = "composite"

                source_elem = ET.SubElement(
                    conn_elem, "source", {"xmi:idref": src_class_eaid}
                )
                ET.SubElement(source_elem, "model", {"type": "Class"})
                ET.SubElement(
                    source_elem,
                    "type",
                    {
                        "aggregation": agg_val,
                        "multiplicity": rel.source_cardinality or "",
                    },
                )

                target_elem = ET.SubElement(
                    conn_elem, "target", {"xmi:idref": tgt_class_eaid}
                )
                ET.SubElement(target_elem, "model", {"type": "Class"})
                ET.SubElement(
                    target_elem,
                    "type",
                    {
                        "aggregation": "none",
                        "multiplicity": rel.target_cardinality or "",
                    },
                )

                ET.SubElement(
                    conn_elem,
                    "properties",
                    {"ea_type": ea_type, "direction": direction},
                )

                ET.SubElement(
                    conn_elem,
                    "labels",
                    {
                        "lb": rel.source_cardinality or "",
                        "rb": rel.target_cardinality or "",
                        "mt": rel.name or "",
                    },
                )

        diagrams_elem = ET.SubElement(ext_elem, "diagrams")
        diagram_elem = ET.SubElement(
            diagrams_elem, "diagram", {"xmi:id": "EAID_DIAGRAM_1"}
        )
        ET.SubElement(
            diagram_elem,
            "model",
            {"package": package_id, "localID": "1", "owner": package_id},
        )
        ET.SubElement(
            diagram_elem,
            "properties",
            {"name": clean_project_name, "type": "Logical"},
        )
        ET.SubElement(
            diagram_elem,
            "project",
            {"author": "DIAgram", "version": "1.0"},
        )

        elements_elem = ET.SubElement(diagram_elem, "elements")
        for c in classes:
            class_eaid = f"EAID_{c.id.hex.upper()}"
            left = round(c.position_x)
            top = round(c.position_y)
            right = left + 180
            bottom = top + 140
            geom = f"Left={left};Top={top};Right={right};Bottom={bottom};"
            ET.SubElement(
                elements_elem,
                "element",
                {"geometry": geom, "subject": class_eaid},
            )

        if relations:
            diag_connectors = ET.SubElement(diagram_elem, "connectors")
            for rel in relations:
                if rel.bridge is not None and rel.bridge.class_id in class_elements:
                    conn_eaid = f"EAID_{rel.bridge.class_id.hex.upper()}"
                else:
                    conn_eaid = f"EAID_{rel.id.hex.upper()}"
                diag_conn_elem = ET.SubElement(
                    diag_connectors, "connector", {"xmi:idref": conn_eaid}
                )
                style_str = self._build_ea_connector_style(
                    rel.source.handle, rel.target.handle
                )
                ET.SubElement(diag_conn_elem, "style", {"value": style_str})

        # Formatear con sangrías bonitas y encabezado xml

        raw_xml = ET.tostring(root, encoding="utf-8")
        parsed = xml.dom.minidom.parseString(raw_xml)
        return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

    def _append_multiplicity(self, end_elem: ET.Element, cardinality: str | None) -> None:
        """Añade los elementos lowerValue y upperValue según la cardinalidad UML."""
        lower = "1"
        upper = "1"

        if cardinality == "0..1":
            lower = "0"
            upper = "1"
        elif cardinality == "0..*":
            lower = "0"
            upper = "*"
        elif cardinality == "1..*":
            lower = "1"
            upper = "*"
        elif cardinality == "1":
            lower = "1"
            upper = "1"

        ET.SubElement(
            end_elem, "lowerValue", {"xmi:type": "uml:LiteralInteger", "value": lower}
        )
        ET.SubElement(
            end_elem,
            "upperValue",
            {"xmi:type": "uml:LiteralUnlimitedNatural", "value": upper},
        )

    def _build_ea_connector_style(
        self, source_handle: str | None, target_handle: str | None
    ) -> str:
        """Construye la cadena de estilo geométrico para conectores en diagramas de Enterprise Architect."""
        src_edge, sx, sy = self._handle_to_ea_edge_and_offset(source_handle, is_source=True)
        _, ex, ey = self._handle_to_ea_edge_and_offset(target_handle, is_source=False)
        return f"Mode=3;EO=0;SO=0;Color=-1;LWidth=0;EDGE={src_edge};SX={sx};SY={sy};EX={ex};EY={ey};"

    def _handle_to_ea_edge_and_offset(
        self, handle: str | None, is_source: bool = True
    ) -> tuple[int, int, int]:
        """Mapea un DiagramRelationHandle a la tupla (EDGE, offset_x, offset_y) de Enterprise Architect.
        EDGE: 1=Bottom, 2=Left, 3=Top, 4=Right.
        """
        h = (handle or "").upper()
        if "TOP" in h:
            edge = 3
            sy = -50
            if "LEFT" in h:
                sx = -45
            elif "RIGHT" in h:
                sx = 45
            else:
                sx = 0
            return edge, sx, sy
        elif "BOTTOM" in h:
            edge = 1
            sy = 50
            if "LEFT" in h:
                sx = -45
            elif "RIGHT" in h:
                sx = 45
            else:
                sx = 0
            return edge, sx, sy
        elif "LEFT" in h:
            edge = 2
            sx = -60
            if "TOP" in h:
                sy = -35
            elif "BOTTOM" in h:
                sy = 35
            else:
                sy = 0
            return edge, sx, sy
        elif "RIGHT" in h:
            edge = 4
            sx = 60
            if "TOP" in h:
                sy = -35
            elif "BOTTOM" in h:
                sy = 35
            else:
                sy = 0
            return edge, sx, sy

        return (4, 60, 0) if is_source else (2, -60, 0)

