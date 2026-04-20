from rest_framework import viewsets, status, views, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db.models import Sum
from .models import GlobalConfig, Location, Movement, CashReconciliation, Profile, Event
from .serializers import (
    GlobalConfigSerializer, LocationSerializer, MovementSerializer, 
    CashReconciliationSerializer, UserSerializer, EventSerializer
)

class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all().order_by('-created_at')
    serializer_class = EventSerializer

    def get_permissions(self):
        # Allow listing events for everyone authenticated (needed for initial load)
        if self.action == 'list':
            return [permissions.IsAuthenticated()]
        
        # Only Admins can create/activate/deactivate events
        user = self.request.user
        if hasattr(user, 'profile') and user.profile.role == 'admin':
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()] # Effective deny for non-staff cajeros

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        event = self.get_object()
        event.is_active = True
        event.save()
        return Response({'status': 'Evento activado'})

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        event = self.get_object()
        event.is_active = False
        event.save()
        return Response({'status': 'Evento desactivado'})

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('username')
    serializer_class = UserSerializer

    def get_permissions(self):
        # Only Admins can manage users
        user = self.request.user
        if hasattr(user, 'profile') and user.profile.role == 'admin':
            return [permissions.IsAuthenticated()]
        # Deny all others
        self.permission_denied(self.request, message="Solo el administrador puede gestionar personal.")
        return [permissions.IsAdminUser()]

    def create(self, request, *args, **kwargs):
        data = request.data
        username = data.get('username')
        password = data.get('password')
        role = data.get('role', 'cajero')
        assigned_location_id = data.get('assigned_location')

        if not username or not password:
            return Response({'error': 'Username and password required'}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(username=username).exists():
            return Response({'error': 'User already exists'}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.create_user(username=username, password=password)
        
        profile = Profile.objects.create(user=user, role=role)
        if role == 'cajero' and assigned_location_id:
            loc = Location.objects.filter(id=assigned_location_id).first()
            if loc:
                profile.assigned_location = loc
                profile.save()
        
        serializer = self.get_serializer(user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        user = self.get_object()
        data = request.data
        
        # Profile only update logic
        if hasattr(user, 'profile'):
            profile = user.profile
            if 'role' in data:
                profile.role = data['role']
            if 'assigned_location' in data:
                loc_id = data['assigned_location']
                if loc_id:
                    loc = Location.objects.filter(id=loc_id).first()
                    profile.assigned_location = loc
                else:
                    profile.assigned_location = None
            profile.save()
        
        if 'username' in data:
            user.username = data['username']
        if 'password' in data and data['password']:
            user.set_password(data['password'])
        user.save()
        
        serializer = self.get_serializer(user)
        return Response(serializer.data)

class GlobalConfigView(views.APIView):
    # Backward compatibility, but redirects to active event config
    def get(self, request):
        event = Event.objects.filter(is_active=True).first()
        if not event:
            return Response({'error': 'No active event'}, status=404)
        return Response({
            'initial_stock': event.initial_stock,
            'price_per_unit': event.price_per_unit
        })

class MeView(views.APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)

class LoginView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        name = request.data.get('name')
        password = request.data.get('password')
        
        if not name or not password:
            return Response({'error': 'Nombre y contraseña son requeridos'}, status=status.HTTP_400_BAD_REQUEST)
        
        user = authenticate(username=name, password=password)
        
        if not user:
            return Response({'error': 'Credenciales inválidas'}, status=status.HTTP_401_UNAUTHORIZED)
        
        token, t_created = Token.objects.get_or_create(user=user)
        
        return Response({
            'token': token.key,
            'user': UserSerializer(user).data
        })

class DashboardView(views.APIView):
    def get(self, request):
        event_id = request.query_params.get('event_id')
        if event_id:
            event = Event.objects.filter(id=event_id).first()
        else:
            event = Event.objects.filter(is_active=True).first()

        if not event:
            return Response({'error': 'No hay evento activo'}, status=status.HTTP_404_NOT_FOUND)

        initial_stock = event.initial_stock
        
        total_sold = Movement.objects.filter(event=event, movement_type='SALE').aggregate(Sum('quantity'))['quantity__sum'] or 0
        total_revenue = Movement.objects.filter(event=event, movement_type='SALE').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_third_party = Movement.objects.filter(event=event, movement_type='THIRD_PARTY_EXIT').aggregate(Sum('quantity'))['quantity__sum'] or 0
        
        cava_stock = Location.objects.filter(event=event, location_type='CAVA').aggregate(Sum('current_stock'))['current_stock__sum'] or 0
        pos_stock = Location.objects.filter(event=event, location_type='POS').aggregate(Sum('current_stock'))['current_stock__sum'] or 0
        
        total_accounted = cava_stock + pos_stock + total_sold + total_third_party
        difference = initial_stock - total_accounted
        
        # Admin restricted check
        is_admin = hasattr(request.user, 'profile') and request.user.profile.role in ['admin', 'supervisor']

        if not is_admin:
             return Response({
                'initial_stock': initial_stock,
                'cava_stock': 0, 
                'total_sold': Movement.objects.filter(event=event, movement_type='SALE', performed_by=request.user).aggregate(Sum('quantity'))['quantity__sum'] or 0,
                'total_revenue': Movement.objects.filter(event=event, movement_type='SALE', performed_by=request.user).aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
                'inventory_difference': 0
            })

        # Detailed POS breakdown for admins
        pos_details = []
        all_pos = Location.objects.filter(event=event, location_type='POS')
        for pos in all_pos:
            pos_sold = Movement.objects.filter(event=event, from_location=pos, movement_type='SALE').aggregate(Sum('quantity'))['quantity__sum'] or 0
            pos_revenue = Movement.objects.filter(event=event, from_location=pos, movement_type='SALE').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            pos_details.append({
                'id': pos.id,
                'name': pos.name,
                'current_stock': pos.current_stock,
                'sold_units': pos_sold,
                'expected_revenue': pos_revenue
            })

        return Response({
            'event_id': event.id,
            'event_name': event.name,
            'initial_stock': initial_stock,
            'cava_stock': cava_stock,
            'pos_stock': pos_stock,
            'total_sold': total_sold,
            'total_revenue': total_revenue,
            'total_third_party': total_third_party,
            'inventory_difference': difference,
            'pos_details': pos_details
        })

class LocationViewSet(viewsets.ModelViewSet):
    serializer_class = LocationSerializer

    def get_queryset(self):
        user = self.request.user
        event_id = self.request.query_params.get('event_id')
        
        if event_id:
            queryset = Location.objects.filter(event_id=event_id)
        else:
            queryset = Location.objects.filter(event__is_active=True)

        if not hasattr(user, 'profile') or user.profile.role in ['admin', 'supervisor']:
            return queryset
        
        if user.profile.assigned_location:
            return queryset.filter(id=user.profile.assigned_location.id)
        
        return Location.objects.none()

    def create(self, request, *args, **kwargs):
        # Only Admins can create
        user = request.user
        if not hasattr(user, 'profile') or user.profile.role != 'admin':
            return Response({'error': 'Solo el administrador puede crear puntos'}, status=status.HTTP_403_FORBIDDEN)
            
        data = request.data
        username = data.get('username')
        password = data.get('password')
        location_name = data.get('name')
        
        event_id = data.get('event')
        if event_id:
            event = Event.objects.get(id=event_id)
        else:
            event = Event.objects.filter(is_active=True).first()

        if not event:
             return Response({'error': 'No active event'}, status=status.HTTP_400_BAD_REQUEST)

        location = Location.objects.create(
            name=location_name,
            location_type=data.get('location_type', 'POS'),
            event=event
        )

        if username and password:
            user = User.objects.create_user(username=username, password=password)
            Profile.objects.create(
                user=user,
                role='cajero',
                assigned_location=location
            )
        
        serializer = self.get_serializer(location)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        user = request.user
        if not hasattr(user, 'profile') or user.profile.role != 'admin':
            return Response({'error': 'Solo el administrador puede editar puntos'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        user = request.user
        if not hasattr(user, 'profile') or user.profile.role != 'admin':
            return Response({'error': 'Solo el administrador puede eliminar puntos'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

class MovementViewSet(viewsets.ModelViewSet):
    serializer_class = MovementSerializer

    def get_queryset(self):
        user = self.request.user
        event_id = self.request.query_params.get('event_id')
        
        if event_id:
            queryset = Movement.objects.filter(event_id=event_id)
        else:
            queryset = Movement.objects.filter(event__is_active=True)

        if not hasattr(user, 'profile') or user.profile.role in ['admin', 'supervisor']:
            return queryset.order_by('-timestamp')
        
        return queryset.filter(performed_by=user).order_by('-timestamp')

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        user = request.user
        
        # Only Admins/Supervisors can edit
        if not hasattr(user, 'profile') or user.profile.role not in ['admin', 'supervisor']:
            return Response({'error': 'No tienes permisos para editar movimientos'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        new_qty = data.get('quantity')
        
        if new_qty is not None:
            new_qty = int(new_qty)
            diff = instance.quantity - new_qty
            
            # Revert old stock impact and apply new one
            if instance.from_location:
                instance.from_location.current_stock += diff
                instance.from_location.save()
            if instance.to_location:
                instance.to_location.current_stock -= diff
                instance.to_location.save()
            
            instance.quantity = new_qty
            
            # Recalculate totals for sales
            if instance.movement_type == 'SALE':
                instance.total_amount = instance.unit_price * new_qty

        if 'note' in data:
            instance.note = data['note']
            
        instance.save()
        return Response(self.get_serializer(instance).data)

    @action(detail=False, methods=['post'])
    def transfer(self, request):
        data = request.data
        try:
            from_id = data.get('from_location')
            to_id = data.get('to_location')
            qty = int(data.get('quantity'))
            m_type = data.get('movement_type', 'TRANSFER')
            
            from_loc = Location.objects.filter(id=from_id).first()
            if not from_loc:
                return Response({'error': f'Ubicación de origen (ID {from_id}) no encontrada'}, status=status.HTTP_400_BAD_REQUEST)
            
            to_loc = None
            if to_id:
                to_loc = Location.objects.filter(id=to_id).first()
                if not to_loc and m_type != 'THIRD_PARTY_EXIT':
                    return Response({'error': f'Ubicación de destino (ID {to_id}) no encontrada'}, status=status.HTTP_400_BAD_REQUEST)

            # Force type if destination is missing and it's not a sale
            if not to_loc and m_type == 'TRANSFER':
                m_type = 'THIRD_PARTY_EXIT'

            movement = Movement.objects.create(
                movement_type=m_type,
                from_location=from_loc,
                to_location=to_loc,
                quantity=qty,
                event=from_loc.event,
                note=data.get('note', ''),
                performed_by=request.user
            )
            return Response(MovementSerializer(movement).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def sale(self, request):
        data = request.data
        try:
            pos_id = data.get('location')
            pos = Location.objects.filter(id=pos_id).first()
            if not pos:
                 return Response({'error': f'Punto de venta (ID {pos_id}) no encontrado'}, status=status.HTTP_400_BAD_REQUEST)
            
            qty = int(data.get('quantity'))
            
            movement = Movement.objects.create(
                movement_type='SALE',
                from_location=pos,
                quantity=qty,
                event=pos.event,
                note=data.get('note', ''),
                performed_by=request.user
            )
            return Response(MovementSerializer(movement).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class CashReconciliationViewSet(viewsets.ModelViewSet):
    serializer_class = CashReconciliationSerializer

    def get_queryset(self):
        event_id = self.request.query_params.get('event_id')
        user = self.request.user
        
        queryset = CashReconciliation.objects.all()
        if event_id:
            queryset = queryset.filter(event_id=event_id)
        else:
            queryset = queryset.filter(event__is_active=True)
            
        if hasattr(user, 'profile') and user.profile.role not in ['admin', 'supervisor']:
            # Cashiers only see their own local reconciliations
            if user.profile.assigned_location:
                 queryset = queryset.filter(location=user.profile.assigned_location)
            else:
                 queryset = queryset.none()
                 
        return queryset.order_by('-timestamp')

    def create(self, request, *args, **kwargs):
        data = request.data
        location_id = data.get('location')
        location = Location.objects.filter(id=location_id).first()
        
        if not location:
            return Response({'error': 'Location not found'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Auto-calculate difference
        expected = float(data.get('expected_amount', 0))
        actual = float(data.get('actual_amount', 0))
        diff = actual - expected
        
        reconciliation = CashReconciliation.objects.create(
            location=location,
            expected_amount=expected,
            actual_amount=actual,
            difference=diff,
            user_name=request.user.username,
            event=location.event
        )
        
        return Response(self.get_serializer(reconciliation).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def status(self, request):
        location_id = request.query_params.get('location_id')
        if not location_id:
            return Response({'error': 'location_id required'}, status=status.HTTP_400_BAD_REQUEST)
            
        location = Location.objects.filter(id=location_id).first()
        if not location:
            return Response({'error': 'Location not found'}, status=status.HTTP_404_NOT_FOUND)
            
        # Calculate expected based on SALES only
        sales = Movement.objects.filter(
            from_location=location,
            movement_type='SALE',
            event=location.event
        )
        
        total_units = sales.aggregate(Sum('quantity'))['quantity__sum'] or 0
        total_expected = sales.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        
        return Response({
            'location_name': location.name,
            'expected_units': total_units,
            'expected_amount': total_expected,
            'unit_price': location.event.price_per_unit if location.event else 0
        })
