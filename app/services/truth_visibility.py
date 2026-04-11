from __future__ import annotations

from datetime import datetime

from app.models.knowledge import Component


def is_component_visible_in_current_truth(component: Component) -> bool:
    if component.valid_to is not None:
        return False
    return component.review_status not in {"rejected", "superseded"}


def is_component_visible_as_of(component: Component, *, as_of: datetime) -> bool:
    if component.valid_from > as_of:
        return False
    if component.valid_to is not None and component.valid_to <= as_of:
        return False
    return component.review_status != "rejected"


def is_component_visible_in_history(component: Component) -> bool:
    return component.review_status != "rejected"


def is_component_rejected(component: Component) -> bool:
    """True when a component has been explicitly rejected.

    Rejected components must not appear in any default graph view.
    """
    return component.review_status == "rejected"
