from django.db import models
from django.contrib.auth.models import User

class Event(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    initial_stock = models.IntegerField(default=22000)
    price_per_unit = models.DecimalField(max_digits=10, decimal_places=2, default=6000)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Evento"
        verbose_name_plural = "Eventos"

    def __str__(self):
        status = "(ACTIVO)" if self.is_active else ""
        return f"{self.name} {status}"

    def save(self, *args, **kwargs):
        # Ensure only one event is active at a time
        if self.is_active:
            Event.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

class GlobalConfig(models.Model):
    # Deprecated: use Event model instead
    initial_stock = models.IntegerField(default=22000)
    price_per_unit = models.DecimalField(max_digits=10, decimal_places=2, default=6000)

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=(
        ('admin', 'Administrador'),
        ('cajero', 'Cajero'),
        ('supervisor', 'Supervisor'),
    ))
    assigned_location = models.ForeignKey('Location', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_profiles')

    def __str__(self):
        return f"{self.user.username} ({self.role})"

class Location(models.Model):
    LOCATION_TYPES = (
        ('CAVA', 'Cava'),
        ('POS', 'Punto de Venta'),
        ('EXTERNAL', 'Terceros'),
    )
    name = models.CharField(max_length=100)
    location_type = models.CharField(max_length=20, choices=LOCATION_TYPES)
    current_stock = models.IntegerField(default=0)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='locations', null=True, blank=True)

    def __str__(self):
        return f"{self.name} - {self.event.name if self.event else 'Sin Evento'}"

class Movement(models.Model):
    MOVEMENT_TYPES = (
        ('INITIAL', 'Carga Inicial'),
        ('TRANSFER', 'Transferencia'),
        ('SALE', 'Venta'),
        ('THIRD_PARTY_EXIT', 'Salida a Terceros'),
    )
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    from_location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='movements_out', null=True, blank=True)
    to_location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='movements_in', null=True, blank=True)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    timestamp = models.DateTimeField(auto_now_add=True)
    note = models.TextField(null=True, blank=True)
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='movements', null=True, blank=True)
    payment_method = models.CharField(max_length=20, choices=(('CASH', 'Efectivo'), ('TRANSFER', 'Transferencia')), default='CASH')

    def save(self, *args, **kwargs):
        # Only update stocks if this is a new movement (to avoid double counting on updates)
        is_new = self.pk is None
        
        if is_new:
            if self.from_location:
                self.from_location.current_stock -= self.quantity
                self.from_location.save()
            if self.to_location:
                self.to_location.current_stock += self.quantity
                self.to_location.save()
                
            if self.movement_type == 'SALE' and self.unit_price == 0:
                event = self.event
                if event:
                    self.unit_price = event.price_per_unit
                    self.total_amount = self.unit_price * self.quantity
                else:
                    self.unit_price = 6000
                    self.total_amount = self.unit_price * self.quantity
        
        super().save(*args, **kwargs)

class CashReconciliation(models.Model):
    location = models.ForeignKey(Location, on_delete=models.CASCADE)
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2)
    actual_amount = models.DecimalField(max_digits=12, decimal_places=2)
    difference = models.DecimalField(max_digits=12, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True)
    user_name = models.CharField(max_length=100)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='reconciliations', null=True, blank=True)
    
    # Segregated amounts
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    actual_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expected_transfer = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    actual_transfer = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"Cuadre {self.location.name} - {self.timestamp}"
