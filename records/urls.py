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
    path('access_requests/<int:pk>/approve_deny/', views.AccessRequestApprovalView.as_view(), name='access_request_approve_deny'), # New
    path('users/<int:pk>/edit/', views.UserUpdateView.as_view(), name='user_update'), # New
    path('users/<int:pk>/delete/', views.UserDeleteView.as_view(), name='user_delete'), # New
    path('', views.TransactionListView.as_view(), name='record_list'), # Ruta raíz para la lista de registros
    path('new/', views.create_bulk_receipts, name='record_create'),
    path('transaction/<int:pk>/edit/', views.TransactionUpdateView.as_view(), name='transaction_update'),
    path('transaction/<int:pk>/delete/', views.TransactionDeleteView.as_view(), name='transaction_delete'),
    path('transaction/<int:pk>/', views.TransactionDetailView.as_view(), name='transaction_detail'),
    path('record/<int:pk>/edit/', views.RecordUpdateView.as_view(), name='record_update_financial'),
    path('record/<int:pk>/', views.FinancialRecordDetailView.as_view(), name='record_detail'),
    path('record/<int:pk>/delete/', views.RecordDeleteView.as_view(), name='record_delete_financial'),
    path('upload_csv/', views.csv_upload_view, name='csv_upload'),
    path('registro/<int:pk>/historial/', views.history_record_view, name='historial_registro'),
    path('receipts/restore/<int:history_id>/', views.restore_delete_record_view, name='restore_receipt'),
    path('receipts/deleted/', views.deleted_records_view, name='deleted_receipts_list'),
    path('transactions/deleted/', views.deleted_transactions_view, name='deleted_transactions_list'),
    path('transactions/restore/<int:history_id>/', views.restore_transaction_view, name='restore_transaction'),
    path('bank/new/', views.BankCreateView.as_view(), name='bank_create'),
    path('bank/<int:pk>/edit/', views.BankUpdateView.as_view(), name='bank_update'),
    path('bank/<int:pk>/delete/', views.BankDeleteView.as_view(), name='bank_delete'),
    path('banks/', views.BankListView.as_view(), name='bank_list'),
    path('origen_transaccion/new/', views.OrigenTransaccionCreateView.as_view(), name='origen_transaccion_create'),
    path('origen_transaccion/<int:pk>/edit/', views.OrigenTransaccionUpdateView.as_view(), name='origen_transaccion_update'),
    path('origen_transaccion/<int:pk>/delete/', views.OrigenTransaccionDeleteView.as_view(), name='origen_transaccion_delete'),
    path('origen_transacciones/', views.OrigenTransaccionListView.as_view(), name='origen_transaccion_list'),
    path('Client/new/', views.ClientCreateView.as_view(), name='Client_create'),
    path('Client/<int:pk>/edit/', views.ClientUpdateView.as_view(), name='Client_update'),
    path('Client/<int:pk>/delete/', views.ClientDeleteView.as_view(), name='Client_delete'),
    path('Clientes/', views.ClientListView.as_view(), name='Client_list'),
    path('Clientes/cargar/', views.bulk_client_upload, name='bulk_client_upload_page'),
    path('seller/new/', views.SellerCreateView.as_view(), name='seller_create'),
    path('seller/<int:pk>/edit/', views.SellerUpdateView.as_view(), name='seller_update'),
    path('seller/<int:pk>/delete/', views.SellerDeleteView.as_view(), name='seller_delete'),
    path('sellers/', views.SellerListView.as_view(), name='seller_list'),
    path('transaction-type/new/', views.TransactionTypeCreateView.as_view(), name='TransactionType_create'),
    path('transaction-type/<int:pk>/edit/', views.TransactionTypeUpdateView.as_view(), name='TransactionType_update'),
    path('transaction-type/<int:pk>/delete/', views.TransactionTypeDeleteView.as_view(), name='TransactionType_delete'),
    path('transaction-types/', views.TransactionTypeListView.as_view(), name='TransactionType_list'),
    path('export_csv/', views.export_csv, name='export_csv'),
    path('export_transactions_csv/', views.export_transactions_csv, name='export_transactions_csv'),
    path('duplicates/', views.DuplicateAttemptsListView.as_view(), name='duplicate_attempts_list'),
    path('duplicates/<int:pk>/resolve/', views.resolve_duplicate_attempt, name='resolve_duplicate_attempt'),
    path('duplicates/history/', views.DuplicateAttemptsHistoryListView.as_view(), name='duplicate_attempts_history_list'),
    path('duplicates/history/export/', views.export_duplicate_attempts_csv, name='export_duplicate_attempts_csv'),
    path('download_csv_template/', views.download_csv_template, name='download_csv_template'),
    path('ajax/get_effective_date/', views.get_effective_date_view, name='get_effective_date'),
    path('ajax/get_client_balance/', views.get_client_balance, name='get_client_balance'),
    path('credit/nuevo/', views.CreditCreateView.as_view(), name='credit_create'),
    path('credits/', views.CreditListView.as_view(), name='credit_list'),

]