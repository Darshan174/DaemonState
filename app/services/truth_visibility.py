from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, or_

from app.models.knowledge import Component


def is_component_visible_in_current_truth(component: Component) -> bool:
    """Python-side check: component is current truth.

    Excludes historical (valid_to set), rejected, and superseded components.
    """
    if component.valid_to is not None:
        return False
    return component.review_status not in {"rejected", "superseded"}


def is_component_visible_as_of(component: Component, *, as_of: datetime) -> bool:
    """Python-side check: component was visible at a point in time.

    Excludes components that were not yet valid, already expired, or
    explicitly rejected.  ``superseded`` status is NOT excluded here —
    a component that was superseded later was still the current truth
    at the time.  Temporal exclusion (``valid_to``) already handles the
    supersession boundary.
    """
    if component.valid_from > as_of:
        return False
    if component.valid_to is not None and component.valid_to <= as_of:
        return False
    return component.review_status != "rejected"


def is_component_visible_in_history(component: Component) -> bool:
    """Python-side check for historical/broad views.

    Excludes only rejected components.  Historical and superseded
    components are included (they represent the evolution of truth).
    """
    return component.review_status != "rejected"


def is_component_rejected(component: Component) -> bool:
    """True when a component has been explicitly rejected.

    Rejected components must not appear in any default graph view.
    """
    return component.review_status == "rejected"


# ---------------------------------------------------------------------------
# SQL-level filter helpers — usable as .where() clauses so that all
# services apply the same truth rules without a Python-side second pass.
# ---------------------------------------------------------------------------


def current_truth_where(
    stmt: Select[tuple[Component]],
    *,
    component_table: type[Component] | None = None,
    review_item_table=None,
) -> Select[tuple[Component]]:
    """Apply current-truth filters to a SQLAlchemy SELECT statement.

    Adds:
      - ``Component.valid_to IS NULL``  (not superseded/historical)
      - excludes components whose review status is ``rejected`` or ``superseded``

    The caller is responsible for joining ``ReviewItem`` if review-status
    filtering is needed via SQL (via ``component_table.review_item`` or an
    explicit join).  When no ReviewItem join exists, the rejected/superseded
    exclusion is skipped at SQL level and will be handled by
    :func:`is_component_visible_in_current_truth` on the Python side.

    Returns the augmented statement.
    """
    stmt = stmt.where(Component.valid_to.is_(None))
    # If the statement already joins ReviewItem, exclude rejected/superseded.
    # We detect this by checking if review_status can be used in a where clause.
    try:
        stmt = stmt.where(
            or_(
                ~Component.review_item.has(),
                ~Component.review_item.has(
                    Component.review_item.property.argument.class_.status.in_(
                        ("rejected", "superseded")
                    )
                ),
            )
        )
    except Exception:
        # No ReviewItem relationship available — skip SQL-level review filter.
        pass
    return stmt


def history_where(
    stmt: Select[tuple[Component]],
    *,
    include_rejected: bool = False,
) -> Select[tuple[Component]]:
    """Apply historical-view filters to a SQLAlchemy SELECT statement.

    When ``include_rejected=False`` (the default), excludes components
    whose review status is ``rejected`` via a NOT EXISTS subquery.
    """
    if not include_rejected:
        from app.models.review import ReviewItem

        stmt = stmt.where(
            ~Component.review_item.has(ReviewItem.status == "rejected")
        )
    return stmt

