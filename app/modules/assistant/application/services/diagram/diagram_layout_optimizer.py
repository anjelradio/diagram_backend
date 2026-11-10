"""Servicio matemático para optimización de layout y anclajes en operaciones del asistente."""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence
from uuid import UUID

from sqlmodel import Session, select

from app.modules.diagram.domain.enums.diagram_relation_handle import DiagramRelationHandle
from app.modules.diagram.infrastructure.persistence.models.diagram_class_model import (
    DiagramClassModel,
)
from app.modules.diagram.infrastructure.persistence.models.diagram_relation_model import (
    DiagramRelationModel,
)

# Dimensiones y separaciones para tarjetas UML estándar en el lienzo
CLASS_WIDTH: float = 260.0
CLASS_HEIGHT: float = 160.0
STEP_X: float = 340.0
STEP_Y: float = 240.0

# Umbrales mínimos de separación anti-colisión
MIN_COLLISION_DX: float = 280.0
MIN_COLLISION_DY: float = 200.0

# Coordenadas mínimas seguras en el lienzo
MIN_CANVAS_X: float = 100.0
MIN_CANVAS_Y: float = 100.0

# Pares de anclaje periféricos para relaciones reflexivas (evitan cruzar el centro)
SELF_REFERENCE_PAIRS: tuple[tuple[DiagramRelationHandle, DiagramRelationHandle], ...] = (
    (DiagramRelationHandle.RIGHT_TOP, DiagramRelationHandle.RIGHT_BOTTOM),
    (DiagramRelationHandle.TOP_LEFT, DiagramRelationHandle.TOP_RIGHT),
    (DiagramRelationHandle.LEFT_TOP, DiagramRelationHandle.LEFT_BOTTOM),
    (DiagramRelationHandle.BOTTOM_LEFT, DiagramRelationHandle.BOTTOM_RIGHT),
    (DiagramRelationHandle.TOP_RIGHT, DiagramRelationHandle.RIGHT_TOP),
    (DiagramRelationHandle.RIGHT_BOTTOM, DiagramRelationHandle.BOTTOM_RIGHT),
    (DiagramRelationHandle.BOTTOM_LEFT, DiagramRelationHandle.LEFT_BOTTOM),
    (DiagramRelationHandle.LEFT_TOP, DiagramRelationHandle.TOP_LEFT),
)


class DiagramLayoutOptimizer:
    """Motor geométrico para ubicar nuevas clases y calcular anclajes óptimos sin colisiones."""

    def __init__(self) -> None:
        pass

    def get_project_handle_usage(
        self, session: Session, project_id: UUID
    ) -> dict[tuple[UUID, DiagramRelationHandle], int]:
        """Obtiene el conteo de uso de cada handle por clase en relaciones activas del proyecto."""
        usage: dict[tuple[UUID, DiagramRelationHandle], int] = defaultdict(int)
        relations = session.exec(
            select(DiagramRelationModel).where(
                DiagramRelationModel.project_id == project_id,
                DiagramRelationModel.deleted_date.is_(None),
            )
        ).all()
        for rel in relations:
            try:
                src_h = DiagramRelationHandle(rel.source_handle)
                usage[(rel.source_class_id, src_h)] += 1
            except (ValueError, TypeError):
                pass
            try:
                tgt_h = DiagramRelationHandle(rel.target_handle)
                usage[(rel.target_class_id, tgt_h)] += 1
            except (ValueError, TypeError):
                pass
            if rel.bridge_class_id is not None and rel.bridge_handle is not None:
                try:
                    br_h = DiagramRelationHandle(rel.bridge_handle)
                    usage[(rel.bridge_class_id, br_h)] += 1
                except (ValueError, TypeError):
                    pass
        return usage

    def calculate_relation_handles(
        self,
        session: Session,
        project_id: UUID,
        source_class_id: UUID,
        target_class_id: UUID,
        *,
        explicit_source_handle: DiagramRelationHandle | None = None,
        explicit_target_handle: DiagramRelationHandle | None = None,
        batch_handle_usage: dict[tuple[UUID, DiagramRelationHandle], int] | None = None,
    ) -> tuple[DiagramRelationHandle, DiagramRelationHandle]:
        """Calcula los anclajes de salida y entrada más limpios geométricamente entre dos clases."""
        combined_usage = self.get_project_handle_usage(session, project_id)
        if batch_handle_usage:
            for key, count in batch_handle_usage.items():
                combined_usage[key] += count

        # 1. Caso autorreferencial / reflexivo
        if source_class_id == target_class_id:
            best_pair = SELF_REFERENCE_PAIRS[0]
            min_usage = float("inf")
            for h1, h2 in SELF_REFERENCE_PAIRS:
                u = combined_usage[(source_class_id, h1)] + combined_usage[(source_class_id, h2)]
                if u == 0:
                    best_pair = (h1, h2)
                    break
                if u < min_usage:
                    min_usage = u
                    best_pair = (h1, h2)

            res_src = explicit_source_handle or best_pair[0]
            res_tgt = explicit_target_handle or best_pair[1]
            if res_src == res_tgt:
                # Si por alguna razón coinciden, forzar el segundo del par óptimo
                res_tgt = best_pair[1] if res_src != best_pair[1] else best_pair[0]

            if batch_handle_usage is not None:
                batch_handle_usage[(source_class_id, res_src)] += 1
                batch_handle_usage[(target_class_id, res_tgt)] += 1
            return res_src, res_tgt

        # 2. Caso inter-clases: consultar posiciones de clases
        classes = session.exec(
            select(DiagramClassModel).where(
                DiagramClassModel.id.in_([source_class_id, target_class_id]),  # type: ignore
                DiagramClassModel.project_id == project_id,
                DiagramClassModel.deleted_date.is_(None),
            )
        ).all()
        class_by_id = {c.id: c for c in classes}
        src_model = class_by_id.get(source_class_id)
        tgt_model = class_by_id.get(target_class_id)

        # Si faltan datos en BD, proveer defaults seguros
        src_x = src_model.position_x if src_model is not None else 100.0
        src_y = src_model.position_y if src_model is not None else 100.0
        tgt_x = tgt_model.position_x if tgt_model is not None else 440.0
        tgt_y = tgt_model.position_y if tgt_model is not None else 100.0

        # Centros aproximados de las tarjetas
        src_cx = src_x + (CLASS_WIDTH / 2.0)
        src_cy = src_y + (CLASS_HEIGHT / 2.0)
        tgt_cx = tgt_x + (CLASS_WIDTH / 2.0)
        tgt_cy = tgt_y + (CLASS_HEIGHT / 2.0)

        dx = tgt_cx - src_cx
        dy = tgt_cy - src_cy

        src_h = explicit_source_handle or self._pick_best_handle(
            source_class_id, dx, dy, combined_usage
        )
        combined_usage[(source_class_id, src_h)] += 1

        tgt_h = explicit_target_handle or self._pick_best_handle(
            target_class_id, -dx, -dy, combined_usage
        )

        if batch_handle_usage is not None:
            batch_handle_usage[(source_class_id, src_h)] += 1
            batch_handle_usage[(target_class_id, tgt_h)] += 1

        return src_h, tgt_h

    def _pick_best_handle(
        self,
        class_id: UUID,
        dx: float,
        dy: float,
        usage: dict[tuple[UUID, DiagramRelationHandle], int],
    ) -> DiagramRelationHandle:
        """Determina el handle direccional óptimo de salida/llegada según el vector (dx, dy)."""
        if abs(dy) > abs(dx):
            if dy > 0:
                # El objetivo está ABAJO -> Salir por BOTTOM
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
                # El objetivo está ARRIBA -> Salir por TOP
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

        # Buscar primer candidato desocupado en la cara primaria
        for cand in primary_candidates:
            if usage.get((class_id, cand), 0) == 0:
                return cand

        # Si todos los primarios están ocupados, intentar con la esquina adyacente
        if adjacent_candidate is not None and usage.get((class_id, adjacent_candidate), 0) == 0:
            return adjacent_candidate

        # Si todo está ocupado, seleccionar el de menor ocupación en la cara primaria
        return min(primary_candidates, key=lambda c: usage.get((class_id, c), 0))

    def calculate_class_position(
        self,
        session: Session,
        project_id: UUID,
        *,
        reference_class_id: UUID | None = None,
        batch_reserved_positions: list[tuple[float, float]] | None = None,
    ) -> tuple[float, float]:
        """Calcula la posición óptima (x, y) para una nueva clase en el diagrama."""
        # 1. Obtener todas las clases activas en el proyecto
        existing_classes = session.exec(
            select(DiagramClassModel).where(
                DiagramClassModel.project_id == project_id,
                DiagramClassModel.deleted_date.is_(None),
            )
        ).all()

        occupied_positions: list[tuple[float, float]] = [
            (c.position_x, c.position_y) for c in existing_classes
        ]
        if batch_reserved_positions:
            occupied_positions.extend(batch_reserved_positions)

        # Si el lienzo está completamente vacío
        if not occupied_positions:
            chosen = (MIN_CANVAS_X, MIN_CANVAS_Y)
            if batch_reserved_positions is not None:
                batch_reserved_positions.append(chosen)
            return chosen

        # 2. Caso con clase de referencia (relacionada)
        if reference_class_id is not None:
            ref_model = next((c for c in existing_classes if c.id == reference_class_id), None)
            if ref_model is not None:
                rx, ry = ref_model.position_x, ref_model.position_y
                candidates = self._generate_radial_candidates(rx, ry)
                for cand in candidates:
                    if not self._has_collision(cand[0], cand[1], occupied_positions):
                        if batch_reserved_positions is not None:
                            batch_reserved_positions.append(cand)
                        return cand

        # 3. Caso general o fallback: buscar en la grilla sin colisiones
        grid_cand = self._find_first_free_grid_slot(occupied_positions)
        if batch_reserved_positions is not None:
            batch_reserved_positions.append(grid_cand)
        return grid_cand

    def _has_collision(
        self,
        x: float,
        y: float,
        occupied_positions: Sequence[tuple[float, float]],
    ) -> bool:
        """Verifica si la posición propuesta (x, y) colisiona con alguna clase existente."""
        for ox, oy in occupied_positions:
            if abs(x - ox) < MIN_COLLISION_DX and abs(y - oy) < MIN_COLLISION_DY:
                return True
        return False

    def _generate_radial_candidates(
        self, rx: float, ry: float
    ) -> list[tuple[float, float]]:
        """Genera candidatos radiales concéntricos alrededor de una posición de referencia."""
        candidates: list[tuple[float, float]] = []

        # Anillo 1 (distancia normal)
        ring1 = [
            (rx + STEP_X, ry),  # Derecha
            (rx, ry + STEP_Y),  # Abajo
            (rx - STEP_X, ry),  # Izquierda
            (rx, ry - STEP_Y),  # Arriba
            (rx + STEP_X, ry + STEP_Y),  # Diagonal abajo-derecha
            (rx - STEP_X, ry + STEP_Y),  # Diagonal abajo-izquierda
            (rx + STEP_X, ry - STEP_Y),  # Diagonal arriba-derecha
            (rx - STEP_X, ry - STEP_Y),  # Diagonal arriba-izquierda
        ]
        for cx, cy in ring1:
            if cx >= MIN_CANVAS_X and cy >= MIN_CANVAS_Y:
                candidates.append((cx, cy))

        # Anillo 2 (doble distancia si el anillo 1 está completamente saturado)
        ring2 = [
            (rx + 2 * STEP_X, ry),
            (rx, ry + 2 * STEP_Y),
            (rx + 2 * STEP_X, ry + STEP_Y),
            (rx + STEP_X, ry + 2 * STEP_Y),
            (rx - 2 * STEP_X, ry),
            (rx, ry - 2 * STEP_Y),
        ]
        for cx, cy in ring2:
            if cx >= MIN_CANVAS_X and cy >= MIN_CANVAS_Y:
                candidates.append((cx, cy))

        return candidates

    def _find_first_free_grid_slot(
        self,
        occupied_positions: Sequence[tuple[float, float]],
    ) -> tuple[float, float]:
        """Busca el primer casillero disponible en una grilla compacta de 4 columnas."""
        max_rows = 50
        cols_per_row = 4
        for row in range(max_rows):
            for col in range(cols_per_row):
                cand_x = MIN_CANVAS_X + col * STEP_X
                cand_y = MIN_CANVAS_Y + row * STEP_Y
                if not self._has_collision(cand_x, cand_y, occupied_positions):
                    return (cand_x, cand_y)

        # Fallback extremo más allá de la grilla
        max_y = max((oy for _, oy in occupied_positions), default=MIN_CANVAS_Y)
        return (MIN_CANVAS_X, max_y + STEP_Y)
