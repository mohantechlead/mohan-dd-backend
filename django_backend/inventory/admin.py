from django.contrib import admin

# Register your models here.
from .models import GRN, GrnItems
from .models import DN, DNItems
from .models import Items, Stock

admin.site.register(GRN)
admin.site.register(GrnItems)
admin.site.register(DN)
admin.site.register(DNItems)
admin.site.register(Items)
admin.site.register(Stock)