# records/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.record_list_view, name='record_list'), # Ruta raíz para la lista de registros
    path('new/', views.record_create_view, name='record_create'),
    path('<int:pk>/edit/', views.record_update_view, name='record_update'),
    path('<int:pk>/delete/', views.record_delete_view, name='record_delete'),
    path('upload_csv/', views.csv_upload_view, name='csv_upload'),
    path('registro/<int:pk>/historial/', views.history_record_view, name='historial_registro'),
    path('registro/restaurar/<int:history_id>/', views.restore_delete_record_view, name='restaurar_registro'),
    path('eliminados/', views.deleted_records_view, name='deleted_records_list'),
]