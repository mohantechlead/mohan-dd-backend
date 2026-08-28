from django.contrib import admin

# Register your models here.
from .models import GRN, GrnItems
from .models import DN, DNItems
from .models import Items, Stock
from .models import (
    WarehouseStorageNote,
    WarehouseStorageItem,
    ExpirationFeeTier,
    WarehouseStorageTopUp,
    WarehouseReleaseNote,
    WarehouseReleaseItem,
)

admin.site.register(GRN)
admin.site.register(GrnItems)
admin.site.register(DN)
admin.site.register(DNItems)
admin.site.register(Items)
admin.site.register(Stock)
admin.site.register(WarehouseStorageNote)
admin.site.register(WarehouseStorageItem)
admin.site.register(ExpirationFeeTier)
admin.site.register(WarehouseStorageTopUp)
admin.site.register(WarehouseReleaseNote)
admin.site.register(WarehouseReleaseItem)