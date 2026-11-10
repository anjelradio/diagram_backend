from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.modules.assistant.application.services.visual.visual_clarification import (
    create_visual_clarification,
    is_explicit_deletion_confirmation,
    is_valid_visual_clarification,
)
from app.modules.assistant.application.services.visual.visual_contracts import VisualIntent


def test_visual_clarification_is_scoped_to_actor_and_expires_after_24_hours():
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    project_id = uuid4()
    intent = VisualIntent(
        mode="clarify",
        needs_image=True,
        visual_request="Producto",
        scope={"classes": ["Producto"], "attributes": "all", "relations": "none"},
        clarification="¿Quieres incluir atributos?",
        requested_mode="mutate",
    )
    marker = create_visual_clarification(
        message_id=uuid4(),
        project_id=project_id,
        user_id="user-1",
        prompt="Recrea Producto desde el diagrama",
        image_url="https://res.cloudinary.com/demo/image/upload/product.png",
        intent=intent,
        now=now,
    )

    assert is_valid_visual_clarification(
        marker, user_id="user-1", project_id=project_id, now=now + timedelta(hours=23)
    )
    assert not is_valid_visual_clarification(
        marker, user_id="user-2", project_id=project_id, now=now
    )
    assert not is_valid_visual_clarification(
        marker, user_id="user-1", project_id=uuid4(), now=now
    )
    assert not is_valid_visual_clarification(
        marker, user_id="user-1", project_id=project_id, now=now + timedelta(hours=24)
    )


def test_deletion_confirmation_requires_an_unambiguous_affirmative():
    assert is_explicit_deletion_confirmation("Sí, confirmo")
    assert is_explicit_deletion_confirmation("confirmar")
    assert not is_explicit_deletion_confirmation("no")
    assert not is_explicit_deletion_confirmation("no quiero confirmar")
    assert not is_explicit_deletion_confirmation("tal vez")


def test_adapt_visual_clarification_preserves_image_exclusions_selection_and_deletion():
    """La adaptación conserva imagen, exclusiones, selección y confirmación de borrado."""
    from app.modules.assistant.application.services.visual.visual_clarification import (
        adapt_visual_clarification_to_continuation,
    )
    from app.modules.assistant.domain.entities.agent_continuation import (
        ContinuationState,
    )

    project_id = uuid4()
    msg_id = uuid4()
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
    marker = {
        "kind": "visual_clarification",
        "version": 1,
        "message_id": str(msg_id),
        "project_id": str(project_id),
        "user_id": "user-vis",
        "original_prompt": "Extraer clases de la foto",
        "image_url": "https://res.cloudinary.com/demo/image/upload/diag.png",
        "question": "¿Deseas eliminar las clases no detectadas?",
        "intent": {"mode": "clarify"},
        "requested_mode": "mutate",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=24)).isoformat(),
        "claimed_by": None,
        "exclusions": ["ClaseObsoleta", "ClaseTemporal"],
        "class_ambiguity": {
            "class_name": "Usuario",
            "candidate_ids": [str(uuid4()), str(uuid4())],
        },
        "selected_class_ids": {"admin": str(uuid4())},
        "requires_deletion_confirmation": True,
    }

    continuation = adapt_visual_clarification_to_continuation(marker)

    assert continuation.project_id == project_id
    assert continuation.user_id == "user-vis"
    assert continuation.root_message_id == msg_id
    assert continuation.state == ContinuationState.AWAITING_INPUT
    assert continuation.version == 1
    assert continuation.effective_request == "Extraer clases de la foto"

    # Preservación de atributos en image_context
    img_ctx = continuation.image_context
    assert img_ctx is not None
    assert img_ctx["image_url"] == "https://res.cloudinary.com/demo/image/upload/diag.png"
    assert img_ctx["exclusions"] == ["ClaseObsoleta", "ClaseTemporal"]
    assert img_ctx["selected_class_ids"] == marker["selected_class_ids"]
    assert img_ctx["requires_deletion_confirmation"] is True
    assert img_ctx["class_ambiguity"]["class_name"] == "Usuario"


def test_adapt_already_claimed_visual_clarification_marks_state_claimed():
    """Un marcador ya reclamado genera una continuación en estado CLAIMED para evitar doble claim."""
    from app.modules.assistant.application.services.visual.visual_clarification import (
        adapt_visual_clarification_to_continuation,
    )
    from app.modules.assistant.domain.entities.agent_continuation import (
        ContinuationState,
    )

    claimer_id = uuid4()
    marker = {
        "kind": "visual_clarification",
        "version": 1,
        "message_id": str(uuid4()),
        "project_id": str(uuid4()),
        "user_id": "user-vis",
        "original_prompt": "Extraer",
        "image_url": "https://res.cloudinary.com/demo/image/upload/diag.png",
        "question": "¿Proceder?",
        "intent": {},
        "requested_mode": "mutate",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "claimed_by": str(claimer_id),
    }

    continuation = adapt_visual_clarification_to_continuation(marker)
    assert continuation.state == ContinuationState.CLAIMED
    assert continuation.claimed_by_message_id == claimer_id
