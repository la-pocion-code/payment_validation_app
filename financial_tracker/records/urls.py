# records/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.record_list_view, name='record_list'), # Ruta raíz para la lista de registros
    path('new/', views.record_create_view, name='record_create'),
    path('upload_csv/', views.csv_upload_view, name='csv_upload')
    
]