"""Estructuras de estado de diálogo: Frames, Slots y Propuestas."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from app.modules.assistant.domain.dialog.slot_schema import (
    ActionSlotRegistry,
    SlotDefinition,
    normalize_cardinality,
    normalize_relation_type,
)


class SlotProvenance(StrEnum):
    USER_INPUT = "user_input"
    ASSISTANT_PROPOSAL = "assistant_proposal"
    DIAGRAM_LOOKUP = "diagram_lookup"
    DEFAULT = "default"


@dataclass(frozen=True, slots=True)
class SlotValue:
    key: str
    value: Any
    provenance: SlotProvenance = SlotProvenance.USER_INPUT
    turn_index: int = 0
    raw_input: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "provenance": self.provenance.value,
            "turn_index": self.turn_index,
            "raw_input": self.raw_input,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SlotValue:
        return cls(
            key=data["key"],
            value=data["value"],
            provenance=SlotProvenance(data.get("provenance", "user_input")),
            turn_index=data.get("turn_index", 0),
            raw_input=data.get("raw_input"),
        )


@dataclass(slots=True)
class DialogFrame:
    id: str
    action: str
    slots: dict[str, SlotValue] = field(default_factory=dict)
    missing_slots: list[SlotDefinition] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return len([s for s in self.missing_slots if s.critical]) == 0

    def evaluate_readiness(self) -> None:
        """Recalcula los slots faltantes en base a las reglas de dominio."""
        facts = {k: v.value for k, v in self.slots.items()}
        if self.action == "CREATE_RELATION":
            s_cls = facts.get("relation.source_class")
            t_cls = facts.get("relation.target_class")
            r_type = facts.get("relation.type")
            self.missing_slots = ActionSlotRegistry.get_relation_slots(
                source_class=s_cls,
                target_class=t_cls,
                relation_type=r_type,
                facts=facts,
            )
        elif self.action == "CREATE_ATTRIBUTE":
            t_cls = facts.get("attribute.target_class")
            name = facts.get("attribute.name")
            self.missing_slots = ActionSlotRegistry.get_attribute_slots(
                target_class=t_cls,
                name=name,
            )
        elif self.action == "CREATE_CLASS":
            self.missing_slots = ActionSlotRegistry.get_class_slots(name=facts.get("class.name"))
        elif self.action == "CONSULT_ATTRIBUTE":
            self.missing_slots = [] if facts.get("attribute.target_class") else [
                SlotDefinition("attribute.target_class", "CONSULT_ATTRIBUTE", question="¿Sobre qué clase quieres que te sugiera atributos?")
            ]
        elif self.action == "CONSULT_RELATION":
            self.missing_slots = [
                SlotDefinition(key, "CONSULT_RELATION", question=question)
                for key, question in (
                    ("relation.source_class", "¿Cuál es la primera clase?"),
                    ("relation.target_class", "¿Cuál es la segunda clase?"),
                )
                if not facts.get(key)
            ]
        else:
            self.missing_slots = []

    def set_slot(
        self,
        key: str,
        value: Any,
        provenance: SlotProvenance = SlotProvenance.USER_INPUT,
        turn_index: int = 0,
        raw_input: str | None = None,
    ) -> None:
        # Normalizaciones automáticas
        if key == "relation.type":
            norm = normalize_relation_type(str(value))
            if norm:
                value = norm
        elif key in ("relation.source_cardinality", "relation.target_cardinality"):
            norm = normalize_cardinality(str(value))
            if norm:
                value = norm

        self.slots[key] = SlotValue(
            key=key,
            value=value,
            provenance=provenance,
            turn_index=turn_index,
            raw_input=raw_input,
        )
        self.evaluate_readiness()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "slots": {k: v.to_dict() for k, v in self.slots.items()},
            "missing_slots": [
                {
                    "key": s.key,
                    "action": s.action,
                    "critical": s.critical,
                    "question": s.question,
                    "allowed_values": list(s.allowed_values) if s.allowed_values else None,
                }
                for s in self.missing_slots
            ],
            "is_ready": self.is_ready,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DialogFrame:
        frame = cls(
            id=data.get("id", str(uuid4())[:8]),
            action=data.get("action", "UNKNOWN"),
        )
        for k, v in (data.get("slots") or {}).items():
            if isinstance(v, dict):
                frame.slots[k] = SlotValue.from_dict(v)
            else:
                frame.slots[k] = SlotValue(key=k, value=v)
        frame.evaluate_readiness()
        return frame


@dataclass(frozen=True, slots=True)
class Proposal:
    action: str
    slots: dict[str, Any]
    rationale: str | None = None
    frame_id: str | None = None
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "slots": self.slots,
            "rationale": self.rationale,
            "frame_id": self.frame_id,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Proposal:
        return cls(
            action=data["action"],
            slots=data.get("slots", {}),
            rationale=data.get("rationale"),
            frame_id=data.get("frame_id"),
            label=data.get("label"),
        )


@dataclass(slots=True)
class DialogState:
    frames: list[DialogFrame] = field(default_factory=list)
    last_assistant_act: str | None = None
    proposals: list[Proposal] = field(default_factory=list)
    active_frame_id: str | None = None
    additional_requests: list[str] = field(default_factory=list)

    @property
    def is_all_ready(self) -> bool:
        return bool(self.frames) and all(f.is_ready for f in self.frames)

    @property
    def active_frame(self) -> DialogFrame | None:
        if not self.frames:
            return None
        if self.active_frame_id:
            for f in self.frames:
                if f.id == self.active_frame_id:
                    return f
        return self.frames[0]

    def add_frame(self, frame: DialogFrame) -> None:
        self.frames.append(frame)
        self.active_frame_id = frame.id

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames": [f.to_dict() for f in self.frames],
            "last_assistant_act": self.last_assistant_act,
            "proposals": [p.to_dict() for p in self.proposals],
            "active_frame_id": self.active_frame_id,
            "additional_requests": self.additional_requests,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DialogState:
        frames = [DialogFrame.from_dict(f) for f in (data.get("frames") or [])]
        proposals = [Proposal.from_dict(p) for p in (data.get("proposals") or [])]
        return cls(
            frames=frames,
            last_assistant_act=data.get("last_assistant_act"),
            proposals=proposals,
            active_frame_id=data.get("active_frame_id"),
            additional_requests=list(data.get("additional_requests") or []),
        )
