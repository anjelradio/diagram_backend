"""Servicio de importación y parseo tolerante de archivos XMI 2.1 / XMI 1.1 de Enterprise Architect."""

import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict


from app.modules.diagram.domain.enums.diagram_attribute_data_type import (
    DiagramAttributeDataType,
)
from app.modules.diagram.domain.enums.diagram_cardinality import (
    DiagramCardinality,
)
from app.modules.diagram.domain.enums.diagram_relation_handle import (
    DiagramRelationHandle,
)
from app.modules.diagram.domain.enums.diagram_relation_type import (
    DiagramRelationType,
)
from app.modules.projects.application.services.xmi_dtos import (
    XMIAttributeDefinition,
    XMIClassDefinition,
    XMIProjectPackage,
    XMIRelationDefinition,
)
from app.modules.projects.domain.exceptions import InvalidProjectFileException


TYPE_MAPPING: dict[str, DiagramAttributeDataType] = {
    "str": DiagramAttributeDataType.TEXT,
    "string": DiagramAttributeDataType.TEXT,
    "text": DiagramAttributeDataType.TEXT,
    "varchar": DiagramAttributeDataType.TEXT,
    "char": DiagramAttributeDataType.TEXT,
    "int": DiagramAttributeDataType.INTEGER,
    "integer": DiagramAttributeDataType.INTEGER,
    "bigint": DiagramAttributeDataType.INTEGER,
    "smallint": DiagramAttributeDataType.INTEGER,
    "number": DiagramAttributeDataType.INTEGER,
    "float": DiagramAttributeDataType.DECIMAL,
    "double": DiagramAttributeDataType.DECIMAL,
    "decimal": DiagramAttributeDataType.DECIMAL,
    "numeric": DiagramAttributeDataType.DECIMAL,
    "real": DiagramAttributeDataType.DECIMAL,
    "bool": DiagramAttributeDataType.BOOLEAN,
    "boolean": DiagramAttributeDataType.BOOLEAN,
    "date": DiagramAttributeDataType.DATE,
    "datetime": DiagramAttributeDataType.TIMESTAMP,
    "timestamp": DiagramAttributeDataType.TIMESTAMP,
    "uuid": DiagramAttributeDataType.UUID,
}


class XmiProjectImporter:
    """Parser robusto para extraer paquetes de clases, atributos y relaciones desde archivos XMI."""

    def parse(self, xml_content: str | bytes) -> XMIProjectPackage:
        """Parsea el contenido XML/XMI y retorna un XMIProjectPackage normalizado."""
        if isinstance(xml_content, str):
            xml_content = xml_content.encode("utf-8")

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            raise InvalidProjectFileException(
                f"El archivo XML proporcionado no tiene un formato válido: {e}"
            ) from e

        project_name = self._extract_project_name(root)
        geometry_map = self._extract_geometry(root)
        classes, class_id_set = self._extract_classes(root, geometry_map)
        connector_styles = self._extract_diagram_connector_styles(root)
        relations = self._extract_relations(root, class_id_set)

        if not classes:
            raise InvalidProjectFileException(
                "El archivo no contiene un diagrama de clases UML válido compatible con Enterprise Architect."
            )

        # Asignar handles direccionales e inteligentes evitando colisiones y sobrecargas
        self._resolve_optimal_handles(relations, classes, connector_styles)

        # Filtrar atributos foráneos redundantes que coincidan con relaciones existentes
        self._filter_redundant_foreign_keys(classes, relations)

        return XMIProjectPackage(
            name=project_name,
            classes=classes,
            relations=relations,
        )


    def _extract_project_name(self, root: ET.Element) -> str:
        """Extrae el nombre del modelo o paquete principal."""
        fallback_name = None
        for elem in root.iter():
            tag = self._clean_tag(elem.tag)
            if tag in ("Model", "Package"):
                name = elem.attrib.get("name", "").strip()
                if name:
                    if name not in ("EA_Model", "EA Model", "Model"):
                        return name
                    if fallback_name is None:
                        fallback_name = name
        return fallback_name or "Proyecto Importado"

    def _normalize_id(self, val: str) -> str:
        """Normaliza GUIDs y IDs de EA removiendo prefijos EAID_, llaves, guiones y espacios."""
        if not val:
            return ""
        clean = re.sub(r"[{}\-\s_]", "", val).upper()
        if clean.startswith("EAID"):
            clean = clean[4:]
        return clean

    def _find_geometry(
        self,
        ea_id: str,
        name: str,
        geometry_map: dict[str, tuple[float, float]],
    ) -> tuple[float, float] | None:
        """Busca las coordenadas de un elemento por ID exacto, GUID normalizado o nombre."""
        if ea_id in geometry_map:
            return geometry_map[ea_id]

        norm_key = f"NORM_{self._normalize_id(ea_id)}"
        if norm_key in geometry_map:
            return geometry_map[norm_key]

        name_key = f"NAME_{name.strip().lower()}"
        if name_key in geometry_map:
            return geometry_map[name_key]

        return None

    def _extract_geometry(self, root: ET.Element) -> dict[str, tuple[float, float]]:
        """Extrae y normaliza las coordenadas espaciales Left y Top de la extensión de diagramas de EA."""
        raw_items: list[dict] = []

        for elem in root.iter():
            tag = self._clean_tag(elem.tag)
            if tag in ("element", "DiagramElement") and "geometry" in elem.attrib and "subject" in elem.attrib:
                subject = elem.attrib.get("subject", "").strip()
                name = elem.attrib.get("name", "").strip()
                geom_str = elem.attrib.get("geometry", "")
                left_match = re.search(r"Left=(-?\d+)", geom_str)
                top_match = re.search(r"Top=(-?\d+)", geom_str)
                if left_match and top_match:
                    try:
                        x = float(left_match.group(1))
                        y = float(top_match.group(1))
                        raw_items.append({
                            "subject": subject,
                            "name": name,
                            "x": x,
                            "y": y,
                        })
                    except ValueError:
                        continue

        if not raw_items:
            return {}

        # 1. Resolver orientación del eje Y de Enterprise Architect
        # En EA las coordenadas Top internas son negativas (Top=-100 arriba, Top=-400 abajo).
        # En la web, el eje Y crece hacia abajo (positivo).
        has_negative_y = any(item["y"] < 0 for item in raw_items)
        points: list[tuple[float, float]] = [
            (item["x"], -item["y"] if has_negative_y else item["y"])
            for item in raw_items
        ]

        # 2. Desplazar duplicados exactos si dos elementos tienen la misma coordenada exacta
        seen_points: set[tuple[float, float]] = set()
        adjusted_points: list[tuple[float, float]] = []
        for pt in points:
            curr = pt
            while curr in seen_points:
                curr = (curr[0] + 280.0, curr[1])
            seen_points.add(curr)
            adjusted_points.append(curr)
        points = adjusted_points

        # 3. Detección y escalado proporcional anti-solapamiento (Anti-overlap Scaling)
        # En EA las cajas de clases son compactas (~110-130px ancho, ~70-90px alto).
        # En la web, las tarjetas miden ~240-260px ancho y ~140-180px alto.
        # Solo escalamos si hay colisiones o solapamientos efectivos entre elementos.
        has_overlap = False
        if len(points) >= 2:
            for i in range(len(points)):
                for j in range(i + 1, len(points)):
                    dx = abs(points[i][0] - points[j][0])
                    dy = abs(points[i][1] - points[j][1])
                    if dx < 260.0 and dy < 160.0:
                        has_overlap = True
                        break
                if has_overlap:
                    break

        min_x = min(pt[0] for pt in points)
        min_y = min(pt[1] for pt in points)

        scale_x = 1.0
        scale_y = 1.0

        if has_overlap:
            overlapping_dx = [
                abs(points[i][0] - points[j][0])
                for i in range(len(points))
                for j in range(i + 1, len(points))
                if abs(points[i][0] - points[j][0]) > 10.0 and abs(points[i][1] - points[j][1]) < 160.0
            ]
            overlapping_dy = [
                abs(points[i][1] - points[j][1])
                for i in range(len(points))
                for j in range(i + 1, len(points))
                if abs(points[i][1] - points[j][1]) > 10.0 and abs(points[i][0] - points[j][0]) < 260.0
            ]

            if overlapping_dx:
                min_dx = min(overlapping_dx)
                if min_dx < 280.0:
                    scale_x = min(2.5, max(1.2, 290.0 / min_dx))
            else:
                scale_x = 1.6

            if overlapping_dy:
                min_dy = min(overlapping_dy)
                if min_dy < 200.0:
                    scale_y = min(2.5, max(1.2, 220.0 / min_dy))
            else:
                scale_y = 1.6

        scaled_coords: list[tuple[float, float]] = []
        for orig_x, orig_y in points:
            sc_x = min_x + (orig_x - min_x) * scale_x
            sc_y = min_y + (orig_y - min_y) * scale_y
            scaled_coords.append((sc_x, sc_y))

        # 4. Ajuste de márgenes para asegurar que queden en área visible cómoda
        cur_min_x = min(p[0] for p in scaled_coords)
        cur_min_y = min(p[1] for p in scaled_coords)
        shift_x = max(0.0, 60.0 - cur_min_x) if cur_min_x < 40.0 else 0.0
        shift_y = max(0.0, 60.0 - cur_min_y) if cur_min_y < 40.0 else 0.0

        geometry_map: dict[str, tuple[float, float]] = {}
        for idx, item in enumerate(raw_items):
            final_x = scaled_coords[idx][0] + shift_x
            final_y = scaled_coords[idx][1] + shift_y
            subject = item["subject"]
            name = item["name"]

            if subject:
                geometry_map[subject] = (final_x, final_y)
                norm_key = f"NORM_{self._normalize_id(subject)}"
                geometry_map[norm_key] = (final_x, final_y)

            if name:
                name_key = f"NAME_{name.lower()}"
                geometry_map[name_key] = (final_x, final_y)

        return geometry_map

    def _extract_classes(
        self, root: ET.Element, geometry_map: dict[str, tuple[float, float]]
    ) -> tuple[list[XMIClassDefinition], set[str]]:
        """Extrae las definiciones de clases y sus atributos secundarios."""
        classes: list[XMIClassDefinition] = []
        class_id_set: set[str] = set()

        class_elements: list[tuple[ET.Element, str, str]] = []

        for elem in root.iter():
            tag = self._clean_tag(elem.tag)
            xmi_type = self._clean_attr(
                elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}type")
                or elem.attrib.get("xmi:type")
                or elem.attrib.get("xmi.type")
                or ""
            )

            is_class = False
            if tag in ("Class", "AssociationClass") or xmi_type in ("Class", "uml:Class", "AssociationClass", "uml:AssociationClass"):
                is_class = True
            elif tag == "packagedElement" and xmi_type in ("Class", "uml:Class", "AssociationClass", "uml:AssociationClass"):
                is_class = True

            if is_class:
                ea_id = (
                    elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id")
                    or elem.attrib.get("xmi:id")
                    or elem.attrib.get("xmi.id")
                    or elem.attrib.get("id")
                    or ""
                )
                name = elem.attrib.get("name", "").strip()
                # Descartar clases internas técnicas de Enterprise Architect como EARootClass
                if name in ("EARootClass", "EA_RootClass", "EA Root Class"):
                    continue

                if ea_id and name and ea_id not in class_id_set:
                    class_id_set.add(ea_id)
                    class_elements.append((elem, ea_id, name))

        # Calcular posición máxima para ubicar elementos huérfanos sin geometría sin encimarlos
        max_placed_y = 60.0
        for elem, ea_id, name in class_elements:
            coords = self._find_geometry(ea_id, name, geometry_map)
            if coords is not None:
                max_placed_y = max(max_placed_y, coords[1])

        unplaced_idx = 0
        for elem, ea_id, name in class_elements:
            coords = self._find_geometry(ea_id, name, geometry_map)
            if coords is not None:
                pos_x = max(40.0, coords[0])
                pos_y = max(40.0, coords[1])
            else:
                col = unplaced_idx % 3
                row = unplaced_idx // 3
                base_y = (max_placed_y + 240.0) if max_placed_y > 60.0 else 60.0
                pos_x = 60.0 + (col * 280.0)
                pos_y = base_y + (row * 240.0)
                unplaced_idx += 1

            attributes = self._extract_class_attributes(elem, name)

            classes.append(
                XMIClassDefinition(
                    ea_id=ea_id,
                    name=name,
                    position_x=pos_x,
                    position_y=pos_y,
                    attributes=attributes,
                )
            )

        return classes, class_id_set

    def _extract_class_attributes(
        self, class_elem: ET.Element, class_name: str
    ) -> list[XMIAttributeDefinition]:
        """Extrae los atributos de una clase filtrando la clave primaria y normalizando nombres."""
        attributes: list[XMIAttributeDefinition] = []

        for child in class_elem.iter():
            if child is class_elem:
                continue
            tag = self._clean_tag(child.tag)
            xmi_type = self._clean_attr(
                child.attrib.get("{http://schema.omg.org/spec/XMI/2.1}type")
                or child.attrib.get("xmi:type")
                or child.attrib.get("xmi.type")
                or ""
            )

            is_attr = tag in ("ownedAttribute", "Attribute") or (
                tag == "Property" and xmi_type in ("Property", "uml:Property", "")
            )

            if not is_attr:
                continue

            raw_name = child.attrib.get("name", "").strip()
            if not raw_name:
                continue

            # Regla 3: Parsear convención nombre: tipo
            if ":" in raw_name:
                parts = raw_name.split(":", 1)
                parsed_name = parts[0].strip()
                raw_type = parts[1].strip().lower()
            else:
                parsed_name = raw_name
                raw_type = ""
                # Intentar leer desde tag <type> o href
                type_child = child.find("type")
                if type_child is not None:
                    raw_type = (
                        type_child.attrib.get("name")
                        or type_child.attrib.get("href", "").split("#")[-1]
                    ).lower()

            if not parsed_name:
                parsed_name = raw_name

            # Regla 2: Descartar atributos que representen la llave primaria id
            lower_name = parsed_name.lower()
            if lower_name in ("id", "pk", f"{class_name.lower()}_id", f"id_{class_name.lower()}"):
                continue

            attr_ea_id = (
                child.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id")
                or child.attrib.get("xmi:id")
                or child.attrib.get("xmi.id")
                or child.attrib.get("id")
                or f"attr_{len(attributes)}"
            )

            # Normalizar tipo
            data_type = TYPE_MAPPING.get(raw_type, DiagramAttributeDataType.TEXT)

            # Detectar si es potencialmente foránea
            is_fk = bool(
                re.search(r"(_id|Id|ID)$", parsed_name)
            )

            attributes.append(
                XMIAttributeDefinition(
                    ea_id=attr_ea_id,
                    raw_name=raw_name,
                    parsed_name=parsed_name,
                    data_type=data_type,
                    is_potential_foreign_key=is_fk,
                    is_nullable=True,
                )
            )

        return attributes

    def _extract_tagged_values(self, elem: ET.Element) -> dict[str, str]:
        """Extrae pares clave-valor de etiquetas <TaggedValue> dentro de un elemento."""
        tagged: dict[str, str] = {}
        for child in elem.iter():
            if self._clean_tag(child.tag) == "TaggedValue":
                tag_name = child.attrib.get("tag", "").strip()
                val = child.attrib.get("value", "").strip()
                if tag_name:
                    tagged[tag_name] = val
        return tagged

    def _match_class_id(self, ref: str, class_ids: set[str]) -> str | None:
        """Encuentra la coincidencia exacta o normalizada de un ID de clase."""
        if not ref:
            return None
        if ref in class_ids:
            return ref
        norm_ref = self._normalize_id(ref)
        for cid in class_ids:
            if self._normalize_id(cid) == norm_ref:
                return cid
        return None

    def _parse_multiplicity_str(self, mult: str | None) -> DiagramCardinality | None:
        """Convierte una cadena de multiplicidad (ej: '1', '0..*', '0..1') a DiagramCardinality."""
        if not mult:
            return None
        clean = mult.strip()
        if clean in ("*", "0..*", "0..-1"):
            return DiagramCardinality.ZERO_OR_MORE
        if clean == "1..*":
            return DiagramCardinality.ONE_OR_MORE
        if clean in ("0..1",):
            return DiagramCardinality.ZERO_OR_ONE
        if clean in ("1", "1..1"):
            return DiagramCardinality.EXACTLY_ONE
        return None

    def _extract_connector_metadata(self, root: ET.Element) -> dict[str, dict]:
        """Extrae metadatos de los conectores de Enterprise Architect desde xmi:Extension."""
        connector_meta: dict[str, dict] = {}
        for conn in root.iter():
            tag = self._clean_tag(conn.tag)
            if tag != "connector":
                continue

            conn_id = (
                conn.attrib.get("{http://schema.omg.org/spec/XMI/2.1}idref")
                or conn.attrib.get("xmi:idref")
                or conn.attrib.get("idref")
                or ""
            )
            if not conn_id:
                continue

            source_elem = conn.find("source")
            target_elem = conn.find("target")
            if source_elem is None or target_elem is None:
                continue

            src_id = (
                source_elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}idref")
                or source_elem.attrib.get("xmi:idref")
                or source_elem.attrib.get("idref")
                or ""
            )
            tgt_id = (
                target_elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}idref")
                or target_elem.attrib.get("xmi:idref")
                or target_elem.attrib.get("idref")
                or ""
            )

            src_mult = ""
            src_agg = ""
            src_type = source_elem.find("type")
            if src_type is not None:
                src_mult = src_type.attrib.get("multiplicity", "")
                src_agg = src_type.attrib.get("aggregation", "")

            tgt_mult = ""
            tgt_agg = ""
            tgt_type = target_elem.find("type")
            if tgt_type is not None:
                tgt_mult = tgt_type.attrib.get("multiplicity", "")
                tgt_agg = tgt_type.attrib.get("aggregation", "")

            labels_elem = conn.find("labels")
            name = ""
            if labels_elem is not None:
                lb = labels_elem.attrib.get("lb", "").strip()
                rb = labels_elem.attrib.get("rb", "").strip()
                mt = labels_elem.attrib.get("mt", "").strip()
                if lb:
                    src_mult = lb
                if rb:
                    tgt_mult = rb
                if mt:
                    name = mt

            props_elem = conn.find("properties")
            ea_type = ""
            if props_elem is not None:
                ea_type = props_elem.attrib.get("ea_type", "")

            connector_meta[conn_id] = {
                "source_id": src_id,
                "target_id": tgt_id,
                "source_cardinality": self._parse_multiplicity_str(src_mult),
                "target_cardinality": self._parse_multiplicity_str(tgt_mult),
                "source_aggregation": src_agg,
                "target_aggregation": tgt_agg,
                "ea_type": ea_type,
                "name": name,
            }
        return connector_meta

    def _extract_relations(
        self, root: ET.Element, class_ids: set[str]
    ) -> list[XMIRelationDefinition]:
        """Extrae asociaciones, herencias, agregaciones y composiciones entre clases existentes."""
        relations: list[XMIRelationDefinition] = []
        rel_id_set: set[str] = set()
        connector_meta = self._extract_connector_metadata(root)

        for elem in root.iter():
            tag = self._clean_tag(elem.tag)
            xmi_type = self._clean_attr(
                elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}type")
                or elem.attrib.get("xmi:type")
                or elem.attrib.get("xmi.type")
                or ""
            )

            # Herencias declaradas en UML 2.x o UML 1.x
            if tag in ("generalization", "Generalization"):
                child_ref = elem.attrib.get("subtype") or elem.attrib.get("child") or ""
                parent_ref = elem.attrib.get("general") or elem.attrib.get("supertype") or elem.attrib.get("parent") or ""
                if not child_ref:
                    parent_ref = elem.attrib.get("general") or ""
                    parent = self._find_parent_class_id(root, elem)
                    child_ref = parent or ""

                matched_child = self._match_class_id(child_ref, class_ids)
                matched_parent = self._match_class_id(parent_ref, class_ids)
                if matched_child and matched_parent and matched_child != matched_parent:
                    rel_id = (
                        elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id")
                        or elem.attrib.get("xmi:id")
                        or elem.attrib.get("xmi.id")
                        or elem.attrib.get("id")
                        or f"gen_{matched_child}_{matched_parent}"
                    )
                    if rel_id not in rel_id_set:
                        rel_id_set.add(rel_id)
                        relations.append(
                            XMIRelationDefinition(
                                ea_id=rel_id,
                                source_ea_id=matched_child,
                                target_ea_id=matched_parent,
                                relation_type=DiagramRelationType.GENERALIZATION,
                                name="",
                                source_cardinality=None,
                                target_cardinality=None,
                                source_handle=DiagramRelationHandle.TOP_CENTER,
                                target_handle=DiagramRelationHandle.BOTTOM_CENTER,
                            )
                        )
                continue

            # Asociaciones, composiciones, agregaciones y AssociationClass
            is_assoc_class = tag == "AssociationClass" or xmi_type in ("AssociationClass", "uml:AssociationClass")
            is_assoc = (
                tag in ("Association", "packagedElement")
                and (tag == "Association" or xmi_type in ("Association", "uml:Association"))
            ) or is_assoc_class

            if is_assoc:
                ea_id = (
                    elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id")
                    or elem.attrib.get("xmi:id")
                    or elem.attrib.get("xmi.id")
                    or elem.attrib.get("id")
                    or f"rel_{len(relations)}"
                )
                if ea_id in rel_id_set:
                    continue

                tagged_vals = self._extract_tagged_values(elem)
                conn_info = connector_meta.get(ea_id)
                rel_name = (
                    elem.attrib.get("name")
                    or tagged_vals.get("mt")
                    or (conn_info.get("name") if conn_info else None)
                    or "Asociación"
                )

                # Priorizar conector si existe metadatos en xmi:Extension (XMI 2.1)
                if conn_info and conn_info["source_id"] in class_ids and conn_info["target_id"] in class_ids:
                    source_id = conn_info["source_id"]
                    target_id = conn_info["target_id"]

                    rel_type = DiagramRelationType.ASSOCIATION
                    src_agg = conn_info.get("source_aggregation", "")
                    tgt_agg = conn_info.get("target_aggregation", "")
                    ea_type = conn_info.get("ea_type", "")
                    if ea_type == "Composition" or src_agg == "composite" or tgt_agg == "composite":
                        rel_type = DiagramRelationType.COMPOSITION
                    elif ea_type == "Aggregation" or src_agg == "shared" or tgt_agg == "shared":
                        rel_type = DiagramRelationType.AGGREGATION
                    elif ea_type == "Generalization":
                        rel_type = DiagramRelationType.GENERALIZATION
                    elif ea_type == "Realization":
                        rel_type = DiagramRelationType.REALIZATION
                    elif ea_type == "Dependency":
                        rel_type = DiagramRelationType.DEPENDENCY

                    if source_id == target_id and rel_type != DiagramRelationType.ASSOCIATION:
                        continue

                    if rel_type != DiagramRelationType.ASSOCIATION:
                        rel_name = ""
                        src_card = None
                        tgt_card = None
                    else:
                        src_card = conn_info.get("source_cardinality") or DiagramCardinality.EXACTLY_ONE
                        tgt_card = conn_info.get("target_cardinality") or DiagramCardinality.ZERO_OR_MORE

                    is_bridge_rel = is_assoc_class or ea_type == "AssociationClass"

                    # Validación de cardinalidad para asociaciones
                    if rel_type == DiagramRelationType.ASSOCIATION and (src_card is None or tgt_card is None):
                        raise InvalidProjectFileException(
                            f"La asociación '{rel_name}' no tiene cardinalidades definidas. "
                            "En Enterprise Architect, debe especificar la multiplicidad de origen y destino para garantizar la compatibilidad."
                        )

                    rel_id_set.add(ea_id)
                    relations.append(
                        XMIRelationDefinition(
                            ea_id=ea_id,
                            source_ea_id=source_id,
                            target_ea_id=target_id,
                            relation_type=rel_type,
                            name=rel_name,
                            source_cardinality=src_card,
                            target_cardinality=tgt_card,
                            bridge_ea_id=ea_id if is_bridge_rel else None,
                        )
                    )
                else:
                    ends = self._extract_association_ends(elem, class_ids)
                    if len(ends) >= 2:
                        source_end = next((e for e in ends if e.get("ea_end") == "source"), None)
                        target_end = next((e for e in ends if e.get("ea_end") == "target"), None)
                        if source_end and target_end and source_end["class_id"] != target_end["class_id"]:
                            end1, end2 = source_end, target_end
                        else:
                            end1, end2 = ends[0], ends[1]

                        source_id = end1["class_id"]
                        target_id = end2["class_id"]

                        ea_type = tagged_vals.get("ea_type", "")
                        rel_type = DiagramRelationType.ASSOCIATION
                        if ea_type == "Composition" or end1.get("aggregation") == "composite" or end2.get("aggregation") == "composite":
                            rel_type = DiagramRelationType.COMPOSITION
                        elif ea_type == "Aggregation" or end1.get("aggregation") == "shared" or end2.get("aggregation") == "shared":
                            rel_type = DiagramRelationType.AGGREGATION
                        elif ea_type == "Generalization":
                            rel_type = DiagramRelationType.GENERALIZATION
                        elif ea_type == "Realization":
                            rel_type = DiagramRelationType.REALIZATION
                        elif ea_type == "Dependency":
                            rel_type = DiagramRelationType.DEPENDENCY

                        if source_id == target_id and rel_type != DiagramRelationType.ASSOCIATION:
                            continue

                        if rel_type != DiagramRelationType.ASSOCIATION:
                            rel_name = ""
                            src_card = None
                            tgt_card = None
                        else:
                            src_card = self._parse_multiplicity_str(tagged_vals.get("lb")) or end1["cardinality"]
                            tgt_card = self._parse_multiplicity_str(tagged_vals.get("rb")) or end2["cardinality"]

                        # Si es una asociación y no tiene cardinalidad en algún extremo, validar:
                        if rel_type == DiagramRelationType.ASSOCIATION and (src_card is None or tgt_card is None):
                            raise InvalidProjectFileException(
                                f"La asociación '{rel_name}' no tiene cardinalidades definidas. "
                                "En Enterprise Architect, debe especificar la multiplicidad de origen y destino para garantizar la compatibilidad."
                            )

                        bridge_ea_id = None
                        if is_assoc_class:
                            bridge_ea_id = ea_id
                        elif "associationclass" in tagged_vals:
                            bridge_ea_id = self._match_class_id(tagged_vals["associationclass"], class_ids)

                        rel_id_set.add(ea_id)
                        relations.append(
                            XMIRelationDefinition(
                                ea_id=ea_id,
                                source_ea_id=source_id,
                                target_ea_id=target_id,
                                relation_type=rel_type,
                                name=rel_name,
                                source_cardinality=src_card,
                                target_cardinality=tgt_card,
                                bridge_ea_id=bridge_ea_id,
                            )
                        )

        # Extraer conectores remanentes de connector_meta que no hayan sido procesados en packagedElement
        existing_pairs = {(r.source_ea_id, r.target_ea_id, r.relation_type) for r in relations}
        for conn_id, conn_info in connector_meta.items():
            if conn_id in rel_id_set:
                continue
            src_id = conn_info.get("source_id")
            tgt_id = conn_info.get("target_id")
            if not src_id or not tgt_id or src_id not in class_ids or tgt_id not in class_ids:
                continue

            ea_type = conn_info.get("ea_type", "")
            src_agg = conn_info.get("source_aggregation", "")
            tgt_agg = conn_info.get("target_aggregation", "")

            rel_type = DiagramRelationType.ASSOCIATION
            if ea_type == "Generalization":
                rel_type = DiagramRelationType.GENERALIZATION
            elif ea_type == "Realization":
                rel_type = DiagramRelationType.REALIZATION
            elif ea_type == "Dependency":
                rel_type = DiagramRelationType.DEPENDENCY
            elif ea_type == "Composition" or src_agg == "composite" or tgt_agg == "composite":
                rel_type = DiagramRelationType.COMPOSITION
            elif ea_type == "Aggregation" or src_agg == "shared" or tgt_agg == "shared":
                rel_type = DiagramRelationType.AGGREGATION

            if (src_id, tgt_id, rel_type) in existing_pairs:
                continue

            if src_id == tgt_id and rel_type != DiagramRelationType.ASSOCIATION:
                continue

            if rel_type != DiagramRelationType.ASSOCIATION:
                rel_name = ""
                src_card = None
                tgt_card = None
            else:
                rel_name = conn_info.get("name") or "Asociación"
                src_card = conn_info.get("source_cardinality") or DiagramCardinality.EXACTLY_ONE
                tgt_card = conn_info.get("target_cardinality") or DiagramCardinality.ZERO_OR_MORE

            rel_id_set.add(conn_id)
            relations.append(
                XMIRelationDefinition(
                    ea_id=conn_id,
                    source_ea_id=src_id,
                    target_ea_id=tgt_id,
                    relation_type=rel_type,
                    name=rel_name,
                    source_cardinality=src_card,
                    target_cardinality=tgt_card,
                    bridge_ea_id=conn_id if ea_type == "AssociationClass" else None,
                )
            )

        return relations

    def _find_parent_class_id(self, root: ET.Element, target: ET.Element) -> str | None:
        """Encuentra el identificador de la clase que contiene un elemento hijo dado."""
        for parent in root.iter():
            for child in parent:
                if child is target:
                    tag = self._clean_tag(parent.tag)
                    xmi_type = self._clean_attr(
                        parent.attrib.get("{http://schema.omg.org/spec/XMI/2.1}type")
                        or parent.attrib.get("xmi:type")
                        or parent.attrib.get("xmi.type")
                        or ""
                    )
                    if tag == "Class" or xmi_type in ("Class", "uml:Class") or (tag == "packagedElement" and xmi_type in ("Class", "uml:Class")):
                        return (
                            parent.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id")
                            or parent.attrib.get("xmi:id")
                            or parent.attrib.get("xmi.id")
                            or parent.attrib.get("id")
                        )
        return None

    def _extract_association_ends(
        self, assoc_elem: ET.Element, class_ids: set[str]
    ) -> list[dict]:
        """Extrae los dos extremos de una asociación con sus multiplicidades y clases asociadas."""
        ends: list[dict] = []

        for child in assoc_elem.iter():
            if child is assoc_elem:
                continue
            tag = self._clean_tag(child.tag)
            if tag in ("ownedEnd", "memberEnd", "AssociationEnd"):
                class_ref = (
                    child.attrib.get("type")
                    or child.attrib.get("{http://schema.omg.org/spec/XMI/2.1}idref")
                    or child.attrib.get("xmi:idref")
                    or child.attrib.get("xmi.idref")
                    or child.attrib.get("idref")
                    or ""
                )
                if not class_ref:
                    type_elem = child.find("type")
                    if type_elem is not None:
                        class_ref = (
                            type_elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}idref")
                            or type_elem.attrib.get("xmi:idref")
                            or type_elem.attrib.get("xmi.idref")
                            or type_elem.attrib.get("idref")
                            or ""
                        )

                matched_class_id = self._match_class_id(class_ref, class_ids)
                if not matched_class_id:
                    continue

                cardinality = None
                mult_attr = child.attrib.get("multiplicity")
                if mult_attr:
                    cardinality = self._parse_multiplicity_str(mult_attr)

                if cardinality is None:
                    lower = "1"
                    upper = "1"
                    lower_elem = child.find("lowerValue")
                    upper_elem = child.find("upperValue")
                    has_explicit_values = False
                    if lower_elem is not None and "value" in lower_elem.attrib:
                        lower = lower_elem.attrib["value"]
                        has_explicit_values = True
                    if upper_elem is not None and "value" in upper_elem.attrib:
                        upper = upper_elem.attrib["value"]
                        has_explicit_values = True
                    if has_explicit_values:
                        cardinality = self._map_cardinality(lower, upper)

                ea_end = None
                for sub in child.iter():
                    if self._clean_tag(sub.tag) == "TaggedValue" and sub.attrib.get("tag") == "ea_end":
                        ea_end = sub.attrib.get("value", "").lower()
                        break

                aggregation = child.attrib.get("aggregation")

                ends.append({
                    "class_id": matched_class_id,
                    "cardinality": cardinality,
                    "aggregation": aggregation,
                    "ea_end": ea_end,
                })

        return ends

    def _map_cardinality(self, lower: str, upper: str) -> DiagramCardinality:
        """Convierte límites lower/upper a DiagramCardinality del dominio."""
        if upper in ("*", "-1", "unlimited"):
            if lower == "0":
                return DiagramCardinality.ZERO_OR_MORE
            return DiagramCardinality.ONE_OR_MORE
        if lower == "0" and upper == "1":
            return DiagramCardinality.ZERO_OR_ONE
        return DiagramCardinality.EXACTLY_ONE

    def _filter_redundant_foreign_keys(
        self, classes: list[XMIClassDefinition], relations: list[XMIRelationDefinition]
    ) -> None:
        """Filtra atributos con nombre característico de FK si corresponden a una relación explícita."""
        class_name_map = {c.ea_id: c.name.lower() for c in classes}

        class_related_names: dict[str, set[str]] = {c.ea_id: set() for c in classes}
        for rel in relations:
            src_name = class_name_map.get(rel.source_ea_id, "")
            tgt_name = class_name_map.get(rel.target_ea_id, "")
            if src_name and rel.target_ea_id in class_related_names:
                class_related_names[rel.target_ea_id].add(src_name)
            if tgt_name and rel.source_ea_id in class_related_names:
                class_related_names[rel.source_ea_id].add(tgt_name)
            if rel.bridge_ea_id and rel.bridge_ea_id in class_related_names:
                if src_name:
                    class_related_names[rel.bridge_ea_id].add(src_name)
                if tgt_name:
                    class_related_names[rel.bridge_ea_id].add(tgt_name)
            elif src_name and tgt_name:
                bridge_candidates = {
                    f"{src_name}_{tgt_name}",
                    f"{tgt_name}_{src_name}",
                    f"{src_name}{tgt_name}",
                    f"{tgt_name}{src_name}",
                    f"{src_name}relation",
                    f"{src_name}_relation",
                }
                for candidate_c in classes:
                    if candidate_c.name.lower() in bridge_candidates:
                        class_related_names[candidate_c.ea_id].add(src_name)
                        class_related_names[candidate_c.ea_id].add(tgt_name)

        for c in classes:
            related_names = class_related_names.get(c.ea_id, set())
            filtered_attrs: list[XMIAttributeDefinition] = []
            for attr in c.attributes:
                attr_lower = attr.parsed_name.lower()
                is_redundant = False
                for rel_name in related_names:
                    clean_name = rel_name[:-3] if rel_name.endswith("_id") else rel_name
                    if attr_lower in (
                        f"{rel_name}_id",
                        f"id_{rel_name}",
                        f"{rel_name}id",
                        f"parent_{rel_name}_id",
                        f"parent_{rel_name}id",
                        f"parent_{rel_name}",
                        f"{rel_name}_id_2",
                        f"{clean_name}_a_id",
                        f"{clean_name}_b_id",
                        f"id_{clean_name}_a",
                        f"id_{clean_name}_b",
                    ):
                        is_redundant = True
                        break

                if not is_redundant:
                    filtered_attrs.append(attr)

            c.attributes = filtered_attrs

    def _extract_diagram_connector_styles(self, root: ET.Element) -> dict[str, dict[str, str]]:
        """Extrae los atributos gráficos (style, geometry, EDGE, SX, SY) de conectores en diagramas de EA."""
        styles: dict[str, dict[str, str]] = {}
        for elem in root.iter():
            tag = self._clean_tag(elem.tag).lower()
            if tag in ("connector", "diagramlink"):
                conn_id = (
                    elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}idref")
                    or elem.attrib.get("xmi:idref")
                    or elem.attrib.get("xmi.idref")
                    or elem.attrib.get("idref")
                    or elem.attrib.get("subject")
                    or ""
                )
                raw_style = elem.attrib.get("style") or elem.attrib.get("geometry") or ""
                style_child = elem.find("style")
                if style_child is not None and not raw_style:
                    raw_style = style_child.attrib.get("value", "")
                if conn_id and raw_style:
                    parsed: dict[str, str] = {}
                    for part in raw_style.split(";"):
                        if "=" in part:
                            k, v = part.split("=", 1)
                            parsed[k.strip().upper()] = v.strip()
                    if parsed:
                        styles[conn_id] = parsed
                        norm_id = self._normalize_id(conn_id)
                        if norm_id:
                            styles[norm_id] = parsed
        return styles

    def _resolve_optimal_handles(
        self,
        relations: list[XMIRelationDefinition],
        classes: list[XMIClassDefinition],
        connector_styles: dict[str, dict[str, str]] | None = None,
    ) -> None:
        """Asigna handles direccionales e inteligentes evitando colisiones y sobrecarga en un mismo punto."""
        if not relations or not classes:
            return

        styles = connector_styles or {}

        # Mapeo de IDs (exacto y normalizado) a clases y posiciones
        class_map: dict[str, XMIClassDefinition] = {}
        for c in classes:
            class_map[c.ea_id] = c
            norm = self._normalize_id(c.ea_id)
            if norm:
                class_map[norm] = c

        # Contador de uso de handles por clase: (class_ea_id, handle) -> count
        handle_usage: dict[tuple[str, DiagramRelationHandle], int] = defaultdict(int)

        for rel in relations:
            src_class = class_map.get(rel.source_ea_id) or class_map.get(self._normalize_id(rel.source_ea_id))
            tgt_class = class_map.get(rel.target_ea_id) or class_map.get(self._normalize_id(rel.target_ea_id))

            if not src_class or not tgt_class:
                continue

            # 1. Verificar si EA especificó un estilo/geometría explícito para este conector
            ea_style = styles.get(rel.ea_id) or styles.get(self._normalize_id(rel.ea_id))
            if ea_style and "EDGE" in ea_style:
                src_h = self._map_ea_edge_to_handle(ea_style.get("EDGE"), ea_style.get("SX"), ea_style.get("SY"))
                tgt_h = self._map_ea_edge_to_handle(ea_style.get("EDGE"), ea_style.get("EX"), ea_style.get("EY"), is_target=True)
                if src_h and tgt_h and src_h != tgt_h:
                    rel.source_handle = src_h
                    rel.target_handle = tgt_h
                    handle_usage[(src_class.ea_id, src_h)] += 1
                    handle_usage[(tgt_class.ea_id, tgt_h)] += 1
                    continue

            # 2. Caso auto-referenciado / recursivo: asignar par no colisionante en la misma clase
            if rel.source_ea_id == rel.target_ea_id:
                pair_candidates = [
                    (DiagramRelationHandle.RIGHT_TOP, DiagramRelationHandle.RIGHT_BOTTOM),
                    (DiagramRelationHandle.TOP_LEFT, DiagramRelationHandle.TOP_RIGHT),
                    (DiagramRelationHandle.LEFT_TOP, DiagramRelationHandle.LEFT_BOTTOM),
                    (DiagramRelationHandle.BOTTOM_LEFT, DiagramRelationHandle.BOTTOM_RIGHT),
                    (DiagramRelationHandle.TOP_RIGHT, DiagramRelationHandle.RIGHT_TOP),
                    (DiagramRelationHandle.RIGHT_BOTTOM, DiagramRelationHandle.BOTTOM_RIGHT),
                    (DiagramRelationHandle.BOTTOM_LEFT, DiagramRelationHandle.LEFT_BOTTOM),
                    (DiagramRelationHandle.LEFT_TOP, DiagramRelationHandle.TOP_LEFT),
                ]
                best_pair = pair_candidates[0]
                min_usage = float("inf")
                for h1, h2 in pair_candidates:
                    u = handle_usage[(src_class.ea_id, h1)] + handle_usage[(src_class.ea_id, h2)]
                    if u == 0:
                        best_pair = (h1, h2)
                        break
                    if u < min_usage:
                        min_usage = u
                        best_pair = (h1, h2)
                rel.source_handle = best_pair[0]
                rel.target_handle = best_pair[1]
                handle_usage[(src_class.ea_id, best_pair[0])] += 1
                handle_usage[(src_class.ea_id, best_pair[1])] += 1
                continue

            # 2. Cálculo de posiciones relativas y centros (tarjetas de ~220x120px)
            src_cx = src_class.position_x + 110.0
            src_cy = src_class.position_y + 60.0
            tgt_cx = tgt_class.position_x + 110.0
            tgt_cy = tgt_class.position_y + 60.0

            dx = tgt_cx - src_cx
            dy = tgt_cy - src_cy

            # Para el origen (mira hacia el destino con vector dx, dy)
            src_h = self._pick_best_handle(
                src_class.ea_id,
                dx,
                dy,
                handle_usage,
            )
            rel.source_handle = src_h
            handle_usage[(src_class.ea_id, src_h)] += 1

            # Para el destino (mira hacia el origen con vector -dx, -dy)
            tgt_h = self._pick_best_handle(
                tgt_class.ea_id,
                -dx,
                -dy,
                handle_usage,
            )
            rel.target_handle = tgt_h
            handle_usage[(tgt_class.ea_id, tgt_h)] += 1

            # Resolver handle para la clase puente si existe
            if rel.bridge_ea_id:
                bridge_class = class_map.get(rel.bridge_ea_id) or class_map.get(self._normalize_id(rel.bridge_ea_id))
                if bridge_class:
                    mid_x = (src_cx + tgt_cx) / 2.0
                    mid_y = (src_cy + tgt_cy) / 2.0
                    bridge_cx = bridge_class.position_x + 110.0
                    bridge_cy = bridge_class.position_y + 60.0
                    bdx = mid_x - bridge_cx
                    bdy = mid_y - bridge_cy

                    bridge_h = self._pick_best_handle(
                        bridge_class.ea_id,
                        bdx,
                        bdy,
                        handle_usage,
                    )
                    rel.bridge_handle = bridge_h
                    handle_usage[(bridge_class.ea_id, bridge_h)] += 1

    def _pick_best_handle(
        self,
        class_id: str,
        dx: float,
        dy: float,
        usage: dict[tuple[str, DiagramRelationHandle], int],
    ) -> DiagramRelationHandle:
        """Determina el handle direccional óptimo de una clase hacia un objetivo (dx, dy),
        distribuyendo las conexiones y evitando colisiones en el mismo punto."""
        if abs(dy) > abs(dx):
            if dy > 0:
                # El objetivo está ABAJO de esta clase -> Salir por BOTTOM
                if dx > 40.0:
                    primary_candidates = [
                        DiagramRelationHandle.BOTTOM_RIGHT,
                        DiagramRelationHandle.BOTTOM_CENTER,
                        DiagramRelationHandle.BOTTOM_LEFT,
                    ]
                    adjacent_candidate = DiagramRelationHandle.RIGHT_BOTTOM
                elif dx < -40.0:
                    primary_candidates = [
                        DiagramRelationHandle.BOTTOM_LEFT,
                        DiagramRelationHandle.BOTTOM_CENTER,
                        DiagramRelationHandle.BOTTOM_RIGHT,
                    ]
                    adjacent_candidate = DiagramRelationHandle.LEFT_BOTTOM
                else:
                    primary_candidates = [
                        DiagramRelationHandle.BOTTOM_CENTER,
                        DiagramRelationHandle.BOTTOM_RIGHT,
                        DiagramRelationHandle.BOTTOM_LEFT,
                    ]
                    adjacent_candidate = DiagramRelationHandle.RIGHT_BOTTOM
            else:
                # El objetivo está ARRIBA de esta clase -> Salir por TOP
                if dx > 40.0:
                    primary_candidates = [
                        DiagramRelationHandle.TOP_RIGHT,
                        DiagramRelationHandle.TOP_CENTER,
                        DiagramRelationHandle.TOP_LEFT,
                    ]
                    adjacent_candidate = DiagramRelationHandle.RIGHT_TOP
                elif dx < -40.0:
                    primary_candidates = [
                        DiagramRelationHandle.TOP_LEFT,
                        DiagramRelationHandle.TOP_CENTER,
                        DiagramRelationHandle.TOP_RIGHT,
                    ]
                    adjacent_candidate = DiagramRelationHandle.LEFT_TOP
                else:
                    primary_candidates = [
                        DiagramRelationHandle.TOP_CENTER,
                        DiagramRelationHandle.TOP_RIGHT,
                        DiagramRelationHandle.TOP_LEFT,
                    ]
                    adjacent_candidate = DiagramRelationHandle.RIGHT_TOP
        else:
            if dx > 0:
                # El objetivo está a la DERECHA -> Salir por RIGHT
                if dy > 30.0:
                    primary_candidates = [
                        DiagramRelationHandle.RIGHT_BOTTOM,
                        DiagramRelationHandle.RIGHT_CENTER,
                        DiagramRelationHandle.RIGHT_TOP,
                    ]
                    adjacent_candidate = DiagramRelationHandle.BOTTOM_RIGHT
                elif dy < -30.0:
                    primary_candidates = [
                        DiagramRelationHandle.RIGHT_TOP,
                        DiagramRelationHandle.RIGHT_CENTER,
                        DiagramRelationHandle.RIGHT_BOTTOM,
                    ]
                    adjacent_candidate = DiagramRelationHandle.TOP_RIGHT
                else:
                    primary_candidates = [
                        DiagramRelationHandle.RIGHT_CENTER,
                        DiagramRelationHandle.RIGHT_BOTTOM,
                        DiagramRelationHandle.RIGHT_TOP,
                    ]
                    adjacent_candidate = DiagramRelationHandle.BOTTOM_RIGHT
            else:
                # El objetivo está a la IZQUIERDA -> Salir por LEFT
                if dy > 30.0:
                    primary_candidates = [
                        DiagramRelationHandle.LEFT_BOTTOM,
                        DiagramRelationHandle.LEFT_CENTER,
                        DiagramRelationHandle.LEFT_TOP,
                    ]
                    adjacent_candidate = DiagramRelationHandle.BOTTOM_LEFT
                elif dy < -30.0:
                    primary_candidates = [
                        DiagramRelationHandle.LEFT_TOP,
                        DiagramRelationHandle.LEFT_CENTER,
                        DiagramRelationHandle.LEFT_BOTTOM,
                    ]
                    adjacent_candidate = DiagramRelationHandle.TOP_LEFT
                else:
                    primary_candidates = [
                        DiagramRelationHandle.LEFT_CENTER,
                        DiagramRelationHandle.LEFT_BOTTOM,
                        DiagramRelationHandle.LEFT_TOP,
                    ]
                    adjacent_candidate = DiagramRelationHandle.BOTTOM_LEFT

        # Buscar primer candidato desocupado (usage == 0) en el lado primario
        for cand in primary_candidates:
            if usage.get((class_id, cand), 0) == 0:
                return cand

        # Si todos los del lado primario están ocupados, intentar con la esquina adyacente desocupada
        if adjacent_candidate and usage.get((class_id, adjacent_candidate), 0) == 0:
            return adjacent_candidate

        # Si todo está ocupado, seleccionar el candidato del lado primario con menor ocupación
        return min(primary_candidates, key=lambda c: usage.get((class_id, c), 0))

    def _map_ea_edge_to_handle(
        self,
        edge_str: str | None,
        x_offset_str: str | None,
        y_offset_str: str | None,
        is_target: bool = False,
    ) -> DiagramRelationHandle | None:
        """Mapea los parámetros de Enterprise Architect EDGE (1=Bottom, 2=Left, 3=Top, 4=Right) y offsets a DiagramRelationHandle."""
        if not edge_str:
            return None
        try:
            edge = int(edge_str)
            ox = float(x_offset_str) if x_offset_str else 0.0
            oy = float(y_offset_str) if y_offset_str else 0.0
        except ValueError:
            return None

        if edge == 1:  # Bottom
            if ox > 15.0:
                return DiagramRelationHandle.BOTTOM_RIGHT
            elif ox < -15.0:
                return DiagramRelationHandle.BOTTOM_LEFT
            return DiagramRelationHandle.BOTTOM_CENTER
        elif edge == 2:  # Left
            if oy > 15.0:
                return DiagramRelationHandle.LEFT_BOTTOM
            elif oy < -15.0:
                return DiagramRelationHandle.LEFT_TOP
            return DiagramRelationHandle.LEFT_CENTER
        elif edge == 3:  # Top
            if ox > 15.0:
                return DiagramRelationHandle.TOP_RIGHT
            elif ox < -15.0:
                return DiagramRelationHandle.TOP_LEFT
            return DiagramRelationHandle.TOP_CENTER
        elif edge == 4:  # Right
            if oy > 15.0:
                return DiagramRelationHandle.RIGHT_BOTTOM
            elif oy < -15.0:
                return DiagramRelationHandle.RIGHT_TOP
            return DiagramRelationHandle.RIGHT_CENTER

        return None

    @staticmethod
    def _clean_tag(tag: str) -> str:

        """Remueve prefijos XML de namespace en etiquetas."""
        return tag.split("}")[-1] if "}" in tag else tag

    @staticmethod
    def _clean_attr(val: str) -> str:
        """Remueve prefijos de tipo UML."""
        return val.split(":")[-1] if ":" in val else val
