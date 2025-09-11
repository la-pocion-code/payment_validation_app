# records/urls.py


from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('access_denied/', views.access_denied_view, name='access_denied'),
    path('request_access/', views.request_access, name='request_access'),
    path('access_requests/', views.access_request_list, name='access_request_list'),
    path('access_requests/<int:request_id>/approve/', views.approve_access_request, name='approve_access_request'),
    path('access_requests/<int:request_id>/delete/', views.delete_access_request, name='delete_access_request'),
    path('users/<int:pk>/edit/', views.UserUpdateView.as_view(), name='user_update'), # New
    path('users/<int:pk>/delete/', views.UserDeleteView.as_view(), name='user_delete'), # New
    path('', views.FinancialRecordListView.as_view(), name='record_list'), # Ruta raíz para la lista de registros
    path('new/', views.RecordCreateView.as_view(), name='record_create'),
    path('<int:pk>/edit/', views.RecordUpdateView.as_view(), name='record_update'),
    path('<int:pk>/delete/', views.RecordDeleteView.as_view(), name='record_delete'),
    path('upload_csv/', views.csv_upload_view, name='csv_upload'),
    path('registro/<int:pk>/historial/', views.history_record_view, name='historial_registro'),
    path('registro/restaurar/<int:history_id>/', views.restore_delete_record_view, name='restaurar_registro'),
    path('eliminados/', views.deleted_records_view, name='deleted_records_list'),
    path('bank/new/', views.BankCreateView.as_view(), name='bank_create'),
    path('bank/<int:pk>/edit/', views.BankUpdateView.as_view(), name='bank_update'),
    path('bank/<int:pk>/delete/', views.BankDeleteView.as_view(), name='bank_delete'),
    path('banks/', views.BankListView.as_view(), name='bank_list'),
    path('export_csv/', views.export_csv, name='export_csv'),
    path('duplicates/', views.DuplicateAttemptsListView.as_view(), name='duplicate_attempts_list'),
    path('duplicates/<int:pk>/resolve/', views.resolve_duplicate_attempt, name='resolve_duplicate_attempt'),
    path('duplicates/history/', views.DuplicateAttemptsHistoryListView.as_view(), name='duplicate_attempts_history_list'),
    path('duplicates/history/export/', views.export_duplicate_attempts_csv, name='export_duplicate_attempts_csv'),
]
