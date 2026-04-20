import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'event_pour_api.settings')
django.setup()

from core.models import GlobalConfig, Location, Movement

def seed():
    # 1. Config
    config, created = GlobalConfig.objects.get_or_create(id=1)
    config.initial_stock = 22000
    config.price_per_unit = 6000
    config.save()
    print("Configuración global creada/actualizada.")

    # 2. Cava Location
    cava, created = Location.objects.get_or_create(
        name='CAVA', 
        defaults={'location_type': 'CAVA', 'current_stock': 0}
    )
    print(f"Ubicación CAVA {'creada' if created else 'existente'}.")

    # 3. Initial Stock Movement
    if cava.current_stock == 0:
        Movement.objects.create(
            movement_type='INITIAL',
            to_location=cava,
            quantity=22000,
            note='Carga inicial automática de 22,000 unidades'
        )
        print("Carga inicial de 22,000 cervezas realizada en CAVA.")
    else:
        print(f"CAVA ya tiene stock ({cava.current_stock}), se omite carga inicial.")

    # 4. Standard POS locations
    pos1, _ = Location.objects.get_or_create(name='Punto 1', defaults={'location_type': 'POS'})
    pos2, _ = Location.objects.get_or_create(name='Punto 2', defaults={'location_type': 'POS'})
    print("Puntos de venta iniciales (1 y 2) verificados.")

if __name__ == '__main__':
    seed()
