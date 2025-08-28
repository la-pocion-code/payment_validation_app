# records/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('', views.record_list_view, name='record_list'), # Ruta raíz para la lista de registros
    path('new/', views.record_create_view, name='record_create'),
    
]