# records/urls.py


from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.FinancialRecordListView.as_view(), name='record_list'), # Ruta raíz para la lista de registros
    path('new/', views.RecordCreateView.as_view(), name='record_create'),
    path('<int:pk>/edit/', views.RecordUpdateView.as_view(), name='record_update'),
    path('<int:pk>/delete/', views.RecordDeleteView.as_view(), name='record_delete'),
    path('upload_csv/', views.csv_upload_view, name='csv_upload'),
    path('registro/<int:pk>/historial/', views.history_record_view, name='historial_registro'),
    path('registro/restaurar/<int:history_id>/', views.restore_delete_record_view, name='restaurar_registro'),
    path('eliminados/', views.deleted_records_view, name='deleted_records_list'),
    path('bank/new/', views.BankCreateView.as_view(), name='bank_create'),
    path('export_csv/', views.export_csv, name='export_csv'),
    path('duplicates/', views.DuplicateAttemptsListView.as_view(), name='duplicate_attempts_list'),
    path('duplicates/<int:pk>/resolve/', views.resolve_duplicate_attempt, name='resolve_duplicate_attempt'),
]