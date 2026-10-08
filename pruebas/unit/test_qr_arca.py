"""Pruebas unitarias para lectura y decodificación de QR de ARCA/AFIP."""
import base64
import json

from fudo.qr_arca import TIPOS_ARCA, parsear_url_qr


def test_parsear_url_qr_valida():
    # Payload simulado de factura electrónica A de ARCA
    datos_arca = {
        "ver": 1,
        "fecha": "2026-09-15",
        "cuit": 30709497401,
        "ptoVta": 4,
        "tipoCmp": 1,  # Factura A
        "nroCmp": 1284,
        "importe": 45890.50,
        "moneda": "PES",
        "ctz": 1.0,
        "tipoDocRec": 80,
        "nroDocRec": 30712345678,
        "tipoCodAut": "E",
        "codAut": 74389201837482
    }
    json_b64 = base64.b64encode(json.dumps(datos_arca).encode()).decode()
    url = f"https://www.afip.gob.ar/fe/qr/?p={json_b64}"

    res = parsear_url_qr(url)
    assert res is not None
    assert res.cuit == "30709497401"
    assert res.fecha == "2026-09-15"
    assert res.tipo_fudo == "Factura A"
    assert res.numero == "00004-00001284"
    assert res.importe == 45890.50
    assert res.cae == "74389201837482"
    assert res.es_nota_credito is False


def test_parsear_url_qr_nota_credito_y_dolares():
    datos_arca = {
        "ver": 1,
        "fecha": "2026-09-20",
        "cuit": 30709497401,
        "ptoVta": 1,
        "tipoCmp": 3,  # Nota de Crédito A
        "nroCmp": 45,
        "importe": 100.0,
        "moneda": "DOL",
        "ctz": 1350.0,
        "tipoDocRec": 80,
        "nroDocRec": 30712345678,
        "tipoCodAut": "E",
        "codAut": 1234567890
    }
    json_b64 = base64.b64encode(json.dumps(datos_arca).encode()).decode()
    url = f"https://www.arca.gob.ar/fe/qr/?p={json_b64}"

    res = parsear_url_qr(url)
    assert res is not None
    assert res.tipo_fudo == "Factura A"
    assert res.es_nota_credito is True
    assert res.importe_pesos == 135000.0  # 100 * 1350
    assert any("Nota de Crédito" in w for w in res.advertencias)


def test_parsear_url_qr_invalida():
    assert parsear_url_qr("") is None
    assert parsear_url_qr("https://google.com") is None
    assert parsear_url_qr("https://www.afip.gob.ar/fe/qr/?p=invalido") is None
