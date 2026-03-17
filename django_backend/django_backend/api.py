import logging

from ninja import NinjaAPI, Schema

from ninja_extra import NinjaExtraAPI
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.controller import NinjaJWTDefaultController
from django.http import JsonResponse
from accounts.api import router as accounts_router
from inventory.api import router as inventory_router

logger = logging.getLogger(__name__)

api = NinjaExtraAPI()


@api.exception_handler(Exception)
def global_exception_handler(request, exc):
    """Return JSON for unhandled exceptions instead of HTML 500 page."""
    logger.exception("Unhandled API exception: %s", exc)
    return JsonResponse(
        {"detail": str(exc), "message": "An error occurred."},
        status=500,
    )
api.register_controllers(NinjaJWTDefaultController)
api.add_router("/partners/", accounts_router)
api.add_router("/inventory/", inventory_router)


class UserSchema(Schema):
    id: int
    username: str
    role: str

@api.get("/hello")
def hello(request):
    return {"message": "Hello, World!"}

@api.get("/me", response=UserSchema, auth=JWTAuth())
def me(request):
    user = request.user
    return {
        "id": user.id,
        "username": user.username,
        "role": getattr(user, "role", "logistics"),
    }

