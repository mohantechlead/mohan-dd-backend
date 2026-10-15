"""Permission helpers for the AI layer.

Mirrors the app convention: admins see status detail, everyone else gets the
same masking as the existing list endpoints. Sensitive fields are excluded
upstream in context.py and never reach this point.
"""


def is_admin(request) -> bool:
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return getattr(user, "role", "logistics") == "admin" or bool(
        getattr(user, "is_superuser", False)
    )


def mask_row_for_role(row: dict, admin: bool) -> dict:
    """Apply the same status masking as inventory list views for non-admins."""
    if admin:
        return row
    masked = dict(row)
    if "status" in masked:
        masked["status"] = None
    for key in ("approved_by", "approval_date", "completed_by", "completed_date",
                "cancelled_by", "cancelled_date", "status_remark"):
        if key in masked:
            masked[key] = None
    return masked
