from ninja import NinjaAPI, Schema

from ninja_extra import NinjaExtraAPI
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.controller import NinjaJWTDefaultController
from accounts.api import router as accounts_router
from inventory.api import router as inventory_router

api = NinjaExtraAPI()
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
        "role": getattr(user, "role", "viewer"),
    }

