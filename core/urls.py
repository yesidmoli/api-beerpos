from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    GlobalConfigView, LocationViewSet, MovementViewSet, 
    CashReconciliationViewSet, LoginView, DashboardView, MeView, EventViewSet, UserViewSet
)

router = DefaultRouter()
router.register(r'pos', LocationViewSet, basename='pos')
router.register(r'movements', MovementViewSet, basename='movements')
router.register(r'reconciliations', CashReconciliationViewSet, basename='reconciliations')
router.register(r'events', EventViewSet, basename='events')
router.register(r'users', UserViewSet, basename='users')

urlpatterns = [
    path('', include(router.urls)),
    path('config/', GlobalConfigView.as_view(), name='global-config'),
    path('login/', LoginView.as_view(), name='login'),
    path('me/', MeView.as_view(), name='me'),
    path('reports/dashboard/', DashboardView.as_view(), name='dashboard-report'),
]
