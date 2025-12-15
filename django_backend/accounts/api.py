from typing import List
from ninja import Router, Schema
import uuid
from .models import Partner
from .schemas import PartnerListSchema, PartnerDetailSchema
from django.shortcuts import get_object_or_404
router = Router()

class UserSchema(Schema):
    username: str
    is_authenticated: bool
    # is not requst.user.is_authenticated
    email: str = None

@router.get("", response=List[PartnerListSchema])
def list_partners(request):
    qs = Partner.objects.all()
    return qs

@router.get("{partner_id}", response=PartnerDetailSchema)
def get_partners(request, partner_id:uuid.UUID):
    return get_object_or_404(Partner, partnerid=partner_id)