"""Política de diálogo: decide el siguiente acto del asistente y gestiona propuestas."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from string import ascii_uppercase
from typing import Any
from uuid import uuid4

from app.modules.assistant.application.services.dialog.turn_interpreter import InterpretedTurn
from app.modules.assistant.domain.dialog.dialog_frame import (
    DialogFrame,
    DialogState,
    Proposal,
    SlotProvenance,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Decisión generada por la política de diálogo."""

    assistant_act: str  # "elicit_slots" | "consult_with_proposal" | "fulfill" | "decline" | "disambiguate"
    assistant_message: str
    resolved_request: str | None = None
    updated_state: DialogState | None = None
    proposal: Proposal | None = None


class DialogPolicy:
    """Implementa la lógica conversacional para guiar al usuario hasta completar slots."""

    def decide(
        self,
        *,
        turn: InterpretedTurn,
        state: DialogState,
    ) -> PolicyDecision:
        # 1. Cancelación / Rechazo / Abandono
        if turn.user_act in ("decline", "abandon") or turn.thread_effect == "abandon":
            state.last_assistant_act = "decline"
            return PolicyDecision(
                assistant_act="decline",
                assistant_message="Entendido, he cancelado la solicitud pendiente. ¿En qué más puedo ayudarte?",
                updated_state=state,
            )

        # 1.5. Guía pedagógica para Llaves Foráneas y Primarias aisladas
        if turn.user_act == "request_foreign_key_guidance":
            return self._handle_foreign_key_guidance(turn, state)
        if turn.user_act == "request_primary_key_guidance":
            return self._handle_primary_key_guidance(turn, state)

        # 2. Consulta / Recomendación
        if turn.user_act == "consult":
            return self._handle_consult(state, raw_prompt=turn.raw_message)

        # 3. Aceptación de propuesta
        if turn.user_act == "select_option":
            selected = next((proposal for proposal in state.proposals if proposal.label == turn.option_label), None)
            if selected is not None:
                return self._handle_accept_proposal(state, turn.additional_request, selected)
            return self._disambiguate(state, "¿Puedes indicar qué opción quieres aplicar y en qué clases?")
        if turn.user_act == "ambiguous_target":
            return self._disambiguate(state, "¿A qué par de clases corresponde esa aclaración?")
        if turn.user_act == "accept_proposal":
            return self._handle_accept_proposal(state, turn.additional_request)

        # 4. Confirmación sin propuesta ni solicitud lista
        if turn.user_act == "confirm":
            if not state.proposals and (not state.active_frame or not state.active_frame.is_ready):
                pending_question = (
                    self._format_state_question(state)
                    if state.active_frame is not None
                    else "¿Podrías especificar qué acción deseas realizar? No encontré una propuesta o solicitud pendiente para confirmar."
                )
                return PolicyDecision(
                    assistant_act="disambiguate",
                    assistant_message=pending_question,
                    updated_state=state,
                )

        # 5. Ingesta de slots, correcciones o confirmaciones
        return self._handle_slots_update(turn, state)

    def _handle_foreign_key_guidance(self, turn: InterpretedTurn, state: DialogState) -> PolicyDecision:
        source_cls = turn.slots.get("relation.source_class")
        target_cls = turn.slots.get("relation.target_class")

        frame = DialogFrame(id=str(uuid4())[:8], action="CREATE_RELATION")
        if source_cls:
            frame.set_slot("relation.source_class", source_cls)
        if target_cls:
            frame.set_slot("relation.target_class", target_cls)
        frame.evaluate_readiness()
        state.add_frame(frame)

        if source_cls and target_cls:
            msg = (
                f"Las llaves foráneas no se crean como atributos manuales; se generan automáticamente al relacionar clases entre sí.\n\n"
                f"¿Deseas que relacione la clase **{source_cls}** con **{target_cls}**? "
                f"Por favor indícame qué tipo de relación deseas (ej. Asociación, Composición) y sus cardinalidades."
            )
        elif source_cls:
            msg = (
                f"Las llaves foráneas no se crean como atributos manuales; se generan automáticamente al crear relaciones entre clases.\n\n"
                f"¿Con qué otra clase deseas relacionar **{source_cls}** para generar la llave foránea? "
                f"(Indica el nombre de la otra clase y el tipo de relación)."
            )
        else:
            msg = (
                "Las llaves foráneas no se crean como atributos manuales; se generan automáticamente al crear relaciones entre clases en el diagrama.\n\n"
                "¿Entre cuáles clases deseas crear la relación para generar la llave foránea?"
            )

        state.last_assistant_act = "elicit_slots"
        return PolicyDecision(
            assistant_act="elicit_slots",
            assistant_message=msg,
            updated_state=state,
        )

    def _handle_primary_key_guidance(self, turn: InterpretedTurn, state: DialogState) -> PolicyDecision:
        cls_name = turn.slots.get("class.name")
        if cls_name:
            frame = DialogFrame(id=str(uuid4())[:8], action="CREATE_ATTRIBUTE")
            frame.set_slot("attribute.target_class", cls_name)
            frame.evaluate_readiness()
            state.frames = [frame]
            state.active_frame_id = frame.id
            msg = (
                f"La clase **{cls_name}** ya cuenta automáticamente con su llave primaria (`id`) generada por el sistema. "
                f"En este entorno, cada clase nace con su identificador único por defecto, por lo que no es necesario crear llaves primarias manuales.\n\n"
                f"¿Deseas agregar algún otro atributo ordinario (como nombre, descripción, etc.) a **{cls_name}**?"
            )
            state.last_assistant_act = "disambiguate"
            return PolicyDecision(
                assistant_act="disambiguate",
                assistant_message=msg,
                updated_state=state,
            )
        else:
            msg = (
                "En este sistema, todas las clases del diagrama nacen automáticamente con su llave primaria (`id: UUID`) por defecto. "
                "No es necesario ni posible crear llaves primarias como atributos manuales.\n\n"
                "¿Deseas crear una nueva clase o agregar atributos ordinarios a alguna clase existente?"
            )
            state.last_assistant_act = "disambiguate"
            return PolicyDecision(
                assistant_act="disambiguate",
                assistant_message=msg,
                updated_state=state,
            )


    def _handle_consult(self, state: DialogState, raw_prompt: str = "") -> PolicyDecision:
        if len(state.frames) > 1:
            return self._disambiguate(state, "¿Para qué par de clases quieres una recomendación?")
        frame = state.active_frame
        prompt_lower = raw_prompt.casefold() if raw_prompt else ""

        # Check if attribute consultation
        is_attr_consult = "atribut" in prompt_lower or (frame and frame.action in {"CREATE_ATTRIBUTE", "CONSULT_ATTRIBUTE"})
        if is_attr_consult or (frame and "attribute.target_class" in frame.slots):
            target_class = None
            if frame and "attribute.target_class" in frame.slots:
                target_class = frame.slots["attribute.target_class"].value
            elif raw_prompt:
                m = re.search(
                    r"\b(?:para|de|en)\s+(?:la\s+clase\s+)?([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)",
                    raw_prompt,
                    re.IGNORECASE,
                )
                if m:
                    target_class = m.group(1).strip()
            if not target_class:
                if frame is None or frame.action != "CONSULT_ATTRIBUTE":
                    frame = DialogFrame(id=str(uuid4())[:8], action="CONSULT_ATTRIBUTE")
                    frame.evaluate_readiness()
                    state.add_frame(frame)
                state.last_assistant_act = "elicit_slots"
                return PolicyDecision(
                    assistant_act="elicit_slots",
                    assistant_message="¿Sobre qué clase quieres que te sugiera atributos?",
                    updated_state=state,
                )

            if frame is not None and frame.action == "CONSULT_ATTRIBUTE":
                state.frames.remove(frame)
                state.active_frame_id = None
                frame = None

            proposal = Proposal(
                action="CREATE_ATTRIBUTE",
                slots={
                    "attribute.target_class": target_class,
                    "attribute.name": "codigo, nombre, precio, stock",
                },
                rationale=f"Atributos estándar para la clase {target_class}.",
                frame_id=frame.id if frame else None,
            )
            state.proposals.append(proposal)
            msg = (
                f"Para la clase {target_class} te recomiendo los siguientes atributos: "
                f"`codigo` (string), `nombre` (string), `precio` (decimal) y `stock` (entero).\n\n"
                f"¿Deseas que agregue estos atributos a {target_class}?"
            )
            state.last_assistant_act = "consult_with_proposal"
            return PolicyDecision(
                assistant_act="consult_with_proposal",
                assistant_message=msg,
                updated_state=state,
                proposal=proposal,
            )

        s_cls = frame.slots.get("relation.source_class") if frame else None
        t_cls = frame.slots.get("relation.target_class") if frame else None

        s_val = s_cls.value if s_cls else None
        t_val = t_cls.value if t_cls else None

        if (not s_val or not t_val) and raw_prompt:
            m_rel = re.search(
                r"\b(?:entre|de)\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)\s+y\s+([A-Za-z0-9_áéíóúÁÉÍÓÚñÑ]+)",
                raw_prompt,
                re.IGNORECASE,
            )
            if m_rel:
                s_val = s_val or m_rel.group(1).strip()
                t_val = t_val or m_rel.group(2).strip()

        if not s_val or not t_val:
            if frame is None or frame.action != "CONSULT_RELATION":
                frame = DialogFrame(id=str(uuid4())[:8], action="CONSULT_RELATION")
                state.add_frame(frame)
            if s_val:
                frame.set_slot("relation.source_class", s_val)
            if t_val:
                frame.set_slot("relation.target_class", t_val)
            frame.evaluate_readiness()
            state.last_assistant_act = "elicit_slots"
            return PolicyDecision(
                assistant_act="elicit_slots",
                assistant_message="¿Entre qué clases quieres una recomendación de relación?",
                updated_state=state,
            )
        if frame is not None and frame.action == "CONSULT_RELATION":
            state.frames.remove(frame)
            state.active_frame_id = None
            frame = None
        combined = f"{s_val} {t_val}".casefold()

        # Si ya había una propuesta previa y el usuario pide más opciones ("sugiéreme más", "otra"):
        is_asking_more = bool(re.search(r"\b(?:m[aá]s|otra|alternativ\w*)\b", prompt_lower))
        prev_type = state.proposals[-1].slots.get("relation.type") if state.proposals else None

        if is_asking_more and prev_type == "COMPOSITION":
            proposal = Proposal(
                action="CREATE_RELATION",
                slots={
                    "relation.type": "AGGREGATION",
                    "relation.whole": s_val,
                    "relation.part": t_val,
                    "relation.source_class": s_val,
                    "relation.target_class": t_val,
                },
                rationale=f"Agregación como alternativa débil para {s_val} y {t_val}.",
                frame_id=frame.id if frame else None,
            )
            state.proposals.append(proposal)
            msg = (
                f"Como alternativa para {s_val} y {t_val}, puedes usar una **Agregación** "
                f"si {t_val} puede existir de forma independiente sin {s_val}.\n\n"
                f"¿Deseas que la cree como agregación?"
            )
        elif "detalle" in combined or "item" in combined:
            whole = s_val if "detalle" not in s_val.casefold() else t_val
            part = t_val if whole == s_val else s_val
            proposal = Proposal(
                action="CREATE_RELATION",
                slots={
                    "relation.type": "COMPOSITION",
                    "relation.whole": whole,
                    "relation.part": part,
                    "relation.source_class": whole,
                    "relation.target_class": part,
                },
                rationale=f"{part} depende del ciclo de vida de {whole}.",
                frame_id=frame.id if frame else None,
            )
            state.proposals.append(proposal)
            msg = (
                f"Para {s_val} y {t_val} te recomiendo una relación de **Composición**, "
                f"ya que {part} depende del ciclo de vida de {whole} y no tiene sentido por sí sola sin ella.\n\n"
                f"¿Deseas que la cree como composición ({whole} como el todo y {part} como la parte)?"
            )
        else:
            t_lower = t_val.casefold()
            s_lower = s_val.casefold()
            is_target_parent = any(w in t_lower for w in ("categoria", "categoría", "tipo", "rol", "grupo", "departamento", "padre"))
            is_source_parent = any(w in s_lower for w in ("categoria", "categoría", "tipo", "rol", "grupo", "departamento", "padre"))
            if is_target_parent and not is_source_parent:
                s_card, t_card, rel_verb = "0..*", "1", "pertenece"
            elif is_source_parent and not is_target_parent:
                s_card, t_card, rel_verb = "1", "0..*", "contiene"
            else:
                s_card, t_card, rel_verb = "0..*", "1", "pertenece"

            proposal = Proposal(
                action="CREATE_RELATION",
                slots={
                    "relation.type": "ASSOCIATION",
                    "relation.source_class": s_val,
                    "relation.target_class": t_val,
                    "relation.source_cardinality": s_card,
                    "relation.target_cardinality": t_card,
                    "relation.name": rel_verb,
                },
                rationale=f"Asociación estándar entre {s_val} y {t_val}.",
                frame_id=frame.id if frame else None,
            )
            state.proposals.append(proposal)
            msg = (
                f"Te recomiendo una **Asociación** (etiqueta: «{rel_verb}») entre {s_val} ({s_card}) y {t_val} ({t_card}).\n\n"
                f"¿Deseas que proceda con esta relación?"
            )

        index = len(state.proposals) - 1
        label = ascii_uppercase[index] if index < len(ascii_uppercase) else str(index + 1)
        proposal = replace(proposal, label=label.casefold())
        state.proposals[-1] = proposal
        state.last_assistant_act = "consult_with_proposal"
        return PolicyDecision(
            assistant_act="consult_with_proposal",
            assistant_message=f"**Opción {label}**\n\n{msg}",
            updated_state=state,
            proposal=proposal,
        )

    @staticmethod
    def _disambiguate(state: DialogState, message: str) -> PolicyDecision:
        return PolicyDecision(
            assistant_act="disambiguate", assistant_message=message, updated_state=state
        )

    def _handle_accept_proposal(
        self, state: DialogState, additional_request: str | None, proposal: Proposal | None = None
    ) -> PolicyDecision:
        if not state.proposals:
            return PolicyDecision(
                assistant_act="disambiguate",
                assistant_message="¿Podrías especificar qué acción deseas realizar? No encontré una propuesta o solicitud pendiente para confirmar.",
                updated_state=state,
            )

        proposal = proposal or state.proposals[-1]
        frame = next((frame for frame in state.frames if frame.id == proposal.frame_id), state.active_frame)
        if frame is None or frame.action != proposal.action:
            frame = DialogFrame(id=str(uuid4())[:8], action=proposal.action)
            state.add_frame(frame)

        for k, v in proposal.slots.items():
            frame.set_slot(k, v, provenance=SlotProvenance.ASSISTANT_PROPOSAL)

        state.proposals.clear()
        if additional_request:
            state.additional_requests.append(additional_request)
        frame.evaluate_readiness()
        if state.is_all_ready:
            canonical_request = self._build_effective_request(state)
            state.last_assistant_act = "fulfill"
            return PolicyDecision(
                assistant_act="fulfill",
                assistant_message="Perfecto, procederé a aplicar los cambios acordados.",
                resolved_request=canonical_request,
                updated_state=state,
                proposal=proposal,
            )

        # Si aún faltara algo
        msg = self._format_state_question(state)
        state.last_assistant_act = "elicit_slots"
        return PolicyDecision(
            assistant_act="elicit_slots",
            assistant_message=msg,
            updated_state=state,
        )

    def _handle_slots_update(self, turn: InterpretedTurn, state: DialogState) -> PolicyDecision:
        frame = state.active_frame
        if turn.new_relation_slots:
            for slots in turn.new_relation_slots:
                frame = DialogFrame(id=str(uuid4())[:8], action="CREATE_RELATION")
                for key, value in slots.items():
                    frame.set_slot(key, value)
                state.add_frame(frame)
        elif frame is None or turn.user_act == "new_request":
            action = turn.proposed_action or "CREATE_RELATION"
            frame = DialogFrame(id=str(uuid4())[:8], action=action)
            state.add_frame(frame)

        for k, v in turn.slots.items():
            frame.set_slot(k, v, provenance=SlotProvenance.USER_INPUT)
        for item in state.frames:
            for key, value in turn.frame_updates.get(item.id, {}).items():
                item.set_slot(key, value, provenance=SlotProvenance.USER_INPUT)

        if turn.slots or turn.frame_updates:
            state.proposals.clear()
        if turn.additional_request:
            state.additional_requests.append(turn.additional_request)
        frame.evaluate_readiness()

        if state.is_all_ready:
            if frame.action in {"CONSULT_ATTRIBUTE", "CONSULT_RELATION"}:
                return self._handle_consult(state, raw_prompt=turn.raw_message)
            canonical_request = self._build_effective_request(state)
            state.last_assistant_act = "fulfill"
            return PolicyDecision(
                assistant_act="fulfill",
                assistant_message="Excelente, los datos están completos. Procedo a aplicar los cambios.",
                resolved_request=canonical_request,
                updated_state=state,
            )

        # Faltan slots
        question = self._format_state_question(state)
        state.last_assistant_act = "elicit_slots"
        return PolicyDecision(
            assistant_act="elicit_slots",
            assistant_message=question,
            updated_state=state,
        )

    def _build_effective_request(self, state: DialogState) -> str:
        requests = [self._build_canonical_request(frame) for frame in state.frames]
        return "\n".join([*requests, *state.additional_requests])

    def _format_state_question(self, state: DialogState) -> str:
        questions = [self._format_grouped_question(frame) for frame in state.frames if not frame.is_ready]
        return "\n\n".join(questions)

    def _build_canonical_request(self, frame: DialogFrame) -> str:
        facts = {k: v.value for k, v in frame.slots.items()}
        if frame.action == "CREATE_CLASS":
            return f"Crea una clase llamada {facts['class.name']}{facts.get('class.details', '')}."
        if frame.action == "CREATE_RELATION":
            s_cls = facts.get("relation.source_class", "ClaseA")
            t_cls = facts.get("relation.target_class", "ClaseB")
            r_type = facts.get("relation.type", "ASSOCIATION")
            rel_name = facts.get("relation.name")
            name_clause = f" con nombre \"{rel_name}\"" if rel_name else ""

            if r_type == "GENERALIZATION":
                super_cls = facts.get("relation.superclass", s_cls)
                sub_cls = facts.get("relation.subclass", t_cls)
                return f"Crea una relación de herencia (generalización){name_clause} donde la clase padre es {super_cls} y la clase hija es {sub_cls}."
            if r_type in ("COMPOSITION", "AGGREGATION"):
                tipo = "composición" if r_type == "COMPOSITION" else "agregación"
                whole_cls = facts.get("relation.whole", s_cls)
                part_cls = facts.get("relation.part", t_cls)
                return f"Crea una relación de {tipo}{name_clause} donde {whole_cls} es el contenedor (todo) y {part_cls} es la parte."
            if r_type == "ASSOCIATION":
                s_card = facts.get("relation.source_cardinality", "1")
                t_card = facts.get("relation.target_cardinality", "1")
                return f"Crea una relación de asociación{name_clause} entre {s_cls} con cardinalidad {s_card} y {t_cls} con cardinalidad {t_card}."
            if r_type == "REALIZATION":
                return f"Crea una relación de realización{name_clause} donde {facts.get('relation.implementer', s_cls)} implementa a {facts.get('relation.contract', t_cls)}."
            if r_type == "DEPENDENCY":
                return f"Crea una relación de dependencia{name_clause} donde {facts.get('relation.dependent', s_cls)} depende de {facts.get('relation.dependency', t_cls)}."
            return f"Crea una relación de tipo {r_type}{name_clause} entre {s_cls} y {t_cls}."

        if frame.action == "CREATE_ATTRIBUTE":
            target = facts.get("attribute.target_class", "Clase")
            name = facts.get("attribute.name", "campo")
            specs = facts.get("attribute.specs")
            if isinstance(specs, list) and specs:
                descriptions = []
                for spec in specs:
                    if not isinstance(spec, dict) or not isinstance(spec.get("name"), str):
                        continue
                    detail = f"{spec['name']}"
                    if spec.get("data_type"):
                        detail += f" de tipo {spec['data_type']}"
                    if spec.get("nullable") is False:
                        detail += " obligatorio"
                    descriptions.append(detail)
                if descriptions:
                    return f"Agrega a la clase {target} estos atributos: {', '.join(descriptions)}."
            if "," in str(name):
                return f"Agrega los atributos {name} a la clase {target}."
            return f"Agrega el atributo {name} a la clase {target}."

        return f"Ejecuta la acción {frame.action} con los parámetros: {facts}."

    def _format_grouped_question(self, frame: DialogFrame) -> str:
        if not frame.missing_slots:
            return "¿Podrías darme más detalles sobre tu solicitud?"

        # Si hay un único slot faltante, dar un trato fluido y contextual
        if len(frame.missing_slots) == 1:
            slot = frame.missing_slots[0]
            if slot.key == "relation.type":
                s_cls = frame.slots.get("relation.source_class")
                t_cls = frame.slots.get("relation.target_class")
                s_name = s_cls.value if s_cls else "la primera clase"
                t_name = t_cls.value if t_cls else "la segunda clase"
                return (
                    f"¿Qué tipo de relación deseas entre la clase {s_name} y la clase {t_name}? "
                    f"(por ejemplo: asociación, herencia, composición o agregación)"
                )
            if slot.key == "relation.direction":
                r_type = frame.slots.get("relation.type")
                type_val = r_type.value if r_type else "GENERALIZATION"
                s_cls = frame.slots.get("relation.source_class")
                t_cls = frame.slots.get("relation.target_class")
                s_name = s_cls.value if s_cls else "origen"
                t_name = t_cls.value if t_cls else "destino"
                if type_val == "GENERALIZATION":
                    return (
                        f"Entendido, será una relación de herencia. ¿Cuál es la clase padre (superclase) "
                        f"y cuál la clase hija (subclase) entre {s_name} y {t_name}?"
                    )
                tipo = "composición" if type_val == "COMPOSITION" else "agregación"
                return (
                    f"Entendido, será una relación de {tipo}. ¿Cuál es la clase contenedora (el todo) "
                    f"y cuál la clase contenida (la parte) entre {s_name} y {t_name}?"
                )
            if slot.key == "relation.endpoint_cardinalities":
                s_cls = frame.slots.get("relation.source_class")
                t_cls = frame.slots.get("relation.target_class")
                s_name = s_cls.value if s_cls else "un extremo"
                t_name = t_cls.value if t_cls else "el otro extremo"
                return (
                    f"Perfecto. ¿Cuáles son las cardinalidades en cada extremo entre {s_name} y {t_name}? "
                    f"(por ejemplo: 1 a muchos, 0..* a 1, o 1 a 1)"
                )
            if slot.key == "attribute.target_class":
                name = frame.slots.get("attribute.name")
                attr_n = name.value if name else "el atributo"
                return f"¿En qué clase deseas agregar el atributo `{attr_n}`?"
            return slot.question

        # Múltiples slots faltantes: agrupar numerado
        lines = ["Para completar la solicitud, por favor indícame:"]
        for idx, s in enumerate(frame.missing_slots, 1):
            lines.append(f"{idx}. {s.question}")
        return "\n".join(lines)
