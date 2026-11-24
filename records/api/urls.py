from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from . import views

app_name = 'api'

router = DefaultRouter()
router.register('transactions', views.TransactionViewSet, basename='transaction')
router.register('receipts', views.ReceiptViewSet, basename='receipt')
router.register('clients', views.ClientViewSet, basename='client')
router.register('banks', views.BankViewSet, basename='bank')
router.register('sellers', views.SellerViewSet, basename='seller')
router.register('transaction-types', views.TransactionTypeViewSet, basename='transaction-type')
router.register('origins', views.OrigenTransaccionViewSet, basename='origin')
router.register('payment-documents', views.PaymentDocumentViewSet, basename='payment-document')

urlpatterns = [
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='api:schema'), name='docs'),
    path('', include(router.urls)),
]
