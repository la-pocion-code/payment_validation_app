# API REST — Validación de Pagos

Para integrar la aplicación con Odoo, la intranet u otro sistema.

| | |
|---|---|
| Base (producción) | `https://web-production-b0638.up.railway.app/api/v1/` |
| Base (staging) | `https://web-staging-d62c.up.railway.app/api/v1/` |
| Documentación interactiva | `/api/v1/docs/` (Swagger; requiere sesión iniciada o llave) |
| Esquema OpenAPI | `/api/v1/schema/` |
| Formato | JSON, UTF-8. Montos como texto decimal (`"150000.00"`). Fechas ISO 8601. |

## 1. Autenticación

Cada integración tiene su propia llave. Se envía en todas las peticiones:

```
Authorization: Api-Key pv_1a2b3c4d_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

Crear una llave (se muestra **una sola vez**; en la base solo queda su hash):

```bash
python manage.py create_api_key "Odoo" --write     # lectura y escritura
python manage.py create_api_key "Intranet"         # solo lectura
```

También desde el admin: **Llaves de API → Añadir**. Para revocar una llave, desmarque
«Activa». Cada llave tiene un usuario de servicio (`api-odoo`, `api-intranet`…), de modo
que el historial de cambios muestra qué integración hizo cada escritura.

| Respuesta | Significado |
|---|---|
| `401` | Falta la llave, no existe o está desactivada |
| `403` | La llave es de solo lectura e intentó escribir |
| `429` | Demasiadas peticiones (límite ~600 por minuto) |

## 2. Recursos

| Recurso | GET | POST | PATCH |
|---|---|---|---|
| `/transactions/` | lista y detalle, con recibos | crea la venta con sus recibos | estado, factura, `odoo_id` |
| `/receipts/` | lista y detalle | abono a cliente o pago de una transacción | estado de pago, documento, nota |
| `/clients/` | lista y detalle | crea | nombre, `odoo_id` |
| `/clients/upsert/` | | crea o actualiza por DNI | |
| `/clients/{id}/balance/` | saldo a favor | | |
| `/banks/` `/sellers/` `/transaction-types/` `/origins/` `/payment-documents/` | catálogos | | |

No hay `DELETE` ni `PUT`: los borrados se hacen en la aplicación, donde quedan auditados.

Las listas vienen paginadas: `{"count", "next", "previous", "results"}`; `?page=2`,
`?page_size=200` (máximo 500). Los catálogos no se paginan.

## 3. Filtros útiles

**Transacciones** — `status`, `date_from`, `date_to`, `cliente` (id), `cliente_dni`,
`vendedor`, `transaction_type`, `numero_factura`, `unique_transaction_id`, `odoo_id`,
`sin_factura=true`, `receipt_status`, `ordering=updated_at`, y dos pensados para sincronizar:

- `listas_para_facturar=true` — pendientes con todos sus pagos **aprobados**.
- `updated_since=2026-11-24T08:00:00-05:00` — lo que cambió desde esa fecha, sea la
  transacción o cualquiera de sus recibos (por ejemplo, el validador aprobó un pago).

**Recibos** — `payment_status`, `fecha_from`, `fecha_to`, `comprobante`, `banco_llegada`,
`cliente`, `transaction`, `sin_transaccion=true` (abonos / saldos a favor), `revisado`,
`updated_since`.

**Clientes** — `dni`, `name`, `odoo_id`, `sin_odoo_id=true`.

## 4. Escribir

### Crear una transacción con sus recibos

```http
POST /api/v1/transactions/
Idempotency-Key: 6f1c1c1e-6d0b-4a55-9b1e-3f0f3a2d9c11

{
  "date": "2026-11-24",
  "cliente_dni": "900123456",
  "vendedor": 3,
  "transaction_type": 1,
  "expected_amount": "150000.00",
  "description": "Pedido web 4821",
  "receipts": [
    {"fecha": "2026-11-24", "hora": "09:15:00", "comprobante": "M03202298",
     "banco_llegada": 2, "origen_transaccion": 1, "valor": "150000.00"}
  ]
}
```

Responde `201` con la transacción completa (incluye `id` y `unique_transaction_id`).
Se puede enviar `cliente` (id) en lugar de `cliente_dni`.

### Marcar como facturada (lo que Odoo devuelve)

```http
PATCH /api/v1/transactions/1532/

{"status": "Facturado", "numero_factura": "FV-10231", "odoo_id": 88412}
```

Campos modificables: `status`, `numero_factura`, `facturador`, `description`, `odoo_id`.
`Facturado` exige número de factura.

### Validar un pago

```http
PATCH /api/v1/receipts/9911/

{"payment_status": "Aprobado"}
```

### Sincronizar un tercero desde Odoo

```http
POST /api/v1/clients/upsert/

{"dni": "900123456", "name": "DROGUERIA CENTRAL SAS", "odoo_id": 4410}
```

`201` si lo creó, `200` si ya existía y lo actualizó.

## 5. Duplicados (`409`)

Son las mismas reglas de la aplicación:

| `code` | Cuándo | Qué hacer |
|---|---|---|
| `duplicate` | Ya existe un recibo con la misma fecha, hora, comprobante, banco y valor | Nada: ya está registrado. `existing_id` trae su id. |
| `similar_duplicate` | Misma fecha, hora, banco y valor, con otro comprobante | Revisar. Si de verdad es otro pago, reenviar el recibo con `"confirm_duplicate": true`. |

## 6. Reintentos seguros (`Idempotency-Key`)

Envíe en cada `POST` un UUID propio de ese envío. Si la respuesta no llega (timeout, red
caída) y reintenta **con la misma llave**, no se crea nada nuevo: recibe `200`, la cabecera
`Idempotent-Replayed: true` y el mismo recurso que se creó la primera vez. Un envío
rechazado por validación (`400`/`409`) no consume la llave.

## 7. Flujo sugerido con Odoo

1. Odoo consulta cada pocos minutos
   `GET /transactions/?listas_para_facturar=true&sin_factura=true`.
2. Crea la factura en Odoo con los datos de la transacción y sus recibos.
3. Devuelve el resultado: `PATCH /transactions/{id}/` con `status`, `numero_factura` y `odoo_id`.
4. Para mantener copias al día, usa `?updated_since=` con la fecha de su última sincronización.
