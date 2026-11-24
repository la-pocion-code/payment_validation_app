"""
El marco de La Poción para los correos de esta aplicación.

Es el mismo diseño de la intranet (`common/correo_marco.py`, 2026-10-21): franja rosa →
púrpura, logo, tarjeta blanca y pie. Portado aquí porque son proyectos separados; si el
marco de la intranet cambia, este se actualiza a mano.

Reglas que se conservan del original:

- El texto plano es la fuente: el HTML se DERIVA de él y va como alternativa. Quien lee
  en texto plano recibe lo mismo, con la URL completa.
- `Etiqueta: https://…` (etiqueta de hasta 60 caracteres) se pinta como botón rosa con la
  etiqueta; una URL sola en su línea, como botón «Haz clic aquí».
- Todo el texto se ESCAPA: lo escribe un administrador y lleva datos digitados.
- El logo va adjunto en línea (PNG, nunca SVG: Outlook no lo pinta).
"""
import html
import re
from email.mime.image import MIMEImage
from pathlib import Path

from django.core.mail import EmailMultiAlternatives

LOGO = Path(__file__).resolve().parent / 'static' / 'correo' / 'logo-pocion.png'
CID_LOGO = 'logo-pocion'
PIE = 'Te escribimos desde Validación de Pagos de La Poción.'

# Identidad de marca (intranet → identidad_de_marca)
ROSA = '#E50076'
PURPURA = '#5C0F8B'
TEXTO = '#54565A'
TEXTO_SUAVE = '#6b6d71'
FONDO = '#F4F4F6'
BORDE = '#E7E7EC'
BLANCO = '#FFFFFF'
FUENTE = "'TTZ', system-ui, 'Segoe UI', Roboto, sans-serif"

_URL = re.compile(r'https?://[^\s<>"]+', re.IGNORECASE)
_PUNTUACION_FINAL = '.,;:!?)]}»"\''
ETIQUETA_MAX = 60
TEXTO_BOTON = 'Haz clic aquí'
TEXTO_ENLACE = 'haz clic aquí'


def crear_mensaje(asunto, texto, para, cc=None, remitente=None):
    """Un correo listo para enviar: texto plano + alternativa HTML con el marco y el logo."""
    mensaje = EmailMultiAlternatives(
        subject=asunto, body=texto, from_email=remitente, to=list(para), cc=list(cc or []))
    logo = _leer_logo()
    mensaje.attach_alternative(
        a_html(texto, asunto=asunto, logo_src=f'cid:{CID_LOGO}' if logo else ''), 'text/html')
    if logo:
        imagen = MIMEImage(logo, _subtype='png')
        # Content-ID entre <> en la cabecera y sin ellos en el src; `inline` para que Gmail
        # no lo liste como adjunto; `related` para que el cliente resuelva el cid.
        imagen.add_header('Content-ID', f'<{CID_LOGO}>')
        imagen.add_header('Content-Disposition', 'inline', filename='logo-pocion.png')
        mensaje.attach(imagen)
        mensaje.mixed_subtype = 'related'
    return mensaje


def _leer_logo():
    try:
        return LOGO.read_bytes()
    except OSError:
        return None


def a_html(texto, *, asunto='', logo_src=''):
    """El correo completo en HTML a partir de su texto plano (tablas y estilos en línea)."""
    limpio = ' '.join(_URL.sub('', texto or '').split())
    return marco_html(_cuerpo_html(texto), asunto=asunto, logo_src=logo_src, preencabezado=limpio[:140])


def marco_html(cuerpo, *, asunto='', logo_src='', preencabezado=''):
    """El marco alrededor de un `cuerpo` que YA viene en HTML y escapado."""
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light only">'
        f'<title>{html.escape(asunto or "La Poción")}</title></head>'
        f'<body style="margin:0;padding:0;background:{FONDO};">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;">'
        f'{html.escape(preencabezado[:140])}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'bgcolor="{FONDO}" style="background:{FONDO};">'
        '<tr><td align="center" style="padding:24px 12px;">'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;max-width:600px;background:{BLANCO};border:1px solid {BORDE};'
        'border-radius:12px;overflow:hidden;">'
        # `bgcolor` rosa de respaldo: Outlook de escritorio ignora los degradados.
        f'<tr><td height="6" bgcolor="{ROSA}" style="height:6px;line-height:6px;font-size:0;'
        f'background:{ROSA};background-image:linear-gradient(90deg,{ROSA},{PURPURA});">&nbsp;</td></tr>'
        f'<tr><td style="padding:28px 32px 4px;">{_logo_html(logo_src)}</td></tr>'
        f'<tr><td style="padding:16px 32px 28px;font-family:{FUENTE};font-size:15px;'
        f'line-height:1.6;color:{TEXTO};">{cuerpo}</td></tr>'
        '</table>'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;max-width:600px;">'
        f'<tr><td align="center" style="padding:16px 32px;font-family:{FUENTE};font-size:12px;'
        f'line-height:1.5;color:{TEXTO_SUAVE};">{html.escape(PIE)}</td></tr>'
        '</table>'
        '</td></tr></table></body></html>'
    )


def _logo_html(logo_src):
    if not logo_src:
        return (f'<span style="font-family:{FUENTE};font-size:24px;font-weight:800;'
                f'color:{ROSA};">La Poción</span>')
    return (f'<img src="{html.escape(logo_src)}" width="160" height="40" alt="La Poción" '
            f'style="display:block;border:0;outline:none;text-decoration:none;width:160px;'
            f'height:40px;font-family:{FUENTE};font-size:22px;font-weight:800;color:{ROSA};">')


def _cuerpo_html(texto):
    texto = (texto or '').replace('\r\n', '\n').replace('\r', '\n').strip('\n')
    partes = []
    for bloque in re.split(r'\n[ \t]*\n', texto):
        if not bloque.strip():
            continue
        lineas = []
        for linea in bloque.split('\n'):
            boton = _boton_de_linea(linea)
            if boton is None:
                lineas.append(_linea_html(linea))
                continue
            previo, etiqueta, url = boton
            if previo:
                lineas.append(_linea_html(previo))
            if lineas:
                partes.append(_parrafo(lineas))
                lineas = []
            partes.append(_boton(url, etiqueta))
        if lineas:
            partes.append(_parrafo(lineas))
    return ''.join(partes)


def _parrafo(lineas):
    return '<p style="margin:0 0 16px;">' + '<br>'.join(lineas) + '</p>'


def _separar_url(crudo):
    url = crudo
    while url and url[-1] in _PUNTUACION_FINAL:
        url = url[:-1]
    return url, crudo[len(url):]


def _boton_de_linea(linea):
    """`(texto_previo, etiqueta, url)` si la línea termina en una única URL y va como botón."""
    contenido = linea.strip()
    encontradas = list(_URL.finditer(contenido))
    if len(encontradas) != 1:
        return None
    coincidencia = encontradas[0]
    url, _ = _separar_url(coincidencia.group(0))
    if contenido[coincidencia.end():].strip() or not url:
        return None
    previo = contenido[:coincidencia.start()].strip()
    if not previo:
        return None if linea[:1] in (' ', '\t') else ('', TEXTO_BOTON, url)
    if not previo.endswith(':') or re.match(r'^([-*•·]|\d+[.)])\s', previo) or linea[:1] in (' ', '\t'):
        return None
    etiqueta = previo[:-1].strip()
    if etiqueta and len(etiqueta) <= ETIQUETA_MAX:
        return '', etiqueta, url
    return previo, TEXTO_BOTON, url


def _linea_html(linea):
    """Una línea escapada; «Etiqueta: valor» resalta la etiqueta y las URLs van como enlace."""
    sin_sangria = linea.lstrip(' \t')
    salida = ['&nbsp;' * min(len(linea) - len(sin_sangria), 8)]
    posicion = 0
    for coincidencia in _URL.finditer(sin_sangria):
        url, sobra = _separar_url(coincidencia.group(0))
        salida.append(html.escape(sin_sangria[posicion:coincidencia.start()]))
        if url:
            salida.append(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener" '
                          f'style="color:{ROSA};font-weight:700;text-decoration:underline;">{TEXTO_ENLACE}</a>')
        salida.append(html.escape(sobra))
        posicion = coincidencia.end()
    salida.append(html.escape(sin_sangria[posicion:]))
    return ''.join(salida)


def _boton(url, etiqueta):
    # Celda con `bgcolor` y el enlace dentro: un <a> suelto pierde el fondo en Outlook.
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:4px 0 20px;">'
        f'<tr><td bgcolor="{ROSA}" style="border-radius:8px;background:{ROSA};">'
        f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener" '
        f'style="display:inline-block;padding:12px 24px;font-family:{FUENTE};font-size:15px;'
        f'font-weight:700;line-height:1.2;color:{BLANCO};text-decoration:none;border-radius:8px;">'
        f'{html.escape(etiqueta)}</a></td></tr></table>'
    )
