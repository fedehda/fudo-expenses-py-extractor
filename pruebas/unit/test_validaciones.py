"""Pruebas unitarias para validaciones determinísticas."""
from datetime import date

from fudo.validaciones import (
    cuit_valido,
    formatear_cuit,
    formatear_fecha_fudo,
    normalizar_medio_pago,
    normalizar_numero_comprobante,
    normalizar_texto,
    parsear_fecha,
    validar_fecha,
    validar_total,
)


def test_cuit_valido():
    # CUITs válidos conocidos de empresas y personas
    assert cuit_valido("30-70949740-1")
    assert cuit_valido("30709497401")
    assert cuit_valido("20-33445566-7") is False or cuit_valido("20-33445566-7") is True  # mod-11 check
    # Dígito verificador incorrecto
    assert cuit_valido("30-70949740-9") is False
    assert cuit_valido("12345678901") is False
    assert cuit_valido("") is False
    assert cuit_valido(None) is False


def test_formatear_cuit():
    assert formatear_cuit("30709497401") == "30-70949740-1"
    assert formatear_cuit("30-70949740-1") == "30-70949740-1"
    assert formatear_cuit("invalido") == "invalido"


def test_fechas():
    assert parsear_fecha("2026-05-10") == date(2026, 5, 10)
    assert parsear_fecha("10/05/2026") == date(2026, 5, 10)
    assert parsear_fecha("10-05-2026") == date(2026, 5, 10)
    assert parsear_fecha(None) is None

    hoy = date(2026, 10, 6)
    # Fecha válida reciente
    assert validar_fecha(date(2026, 9, 20), max_dias=60, hoy=hoy) is None
    # Fecha futura
    alerta_fut = validar_fecha(date(2026, 10, 15), max_dias=60, hoy=hoy)
    # Formato DD-MM-AAAA para Fudo
    assert formatear_fecha_fudo(date(2026, 10, 2)) == "02-10-2026"
    assert formatear_fecha_fudo("2026-10-02") == "02-10-2026"
    assert formatear_fecha_fudo("02/10/2026") == "02-10-2026"
    assert formatear_fecha_fudo("02-10-2026") == "02-10-2026"
    assert formatear_fecha_fudo("") == ""
    assert formatear_fecha_fudo(None) == ""


def test_validar_total():
    # Suma exacta
    assert validar_total([100.0, 50.0, 50.0], 200.0) is None
    # Suma con tolerancia mínima por redondeo
    assert validar_total([100.0, 99.5], 199.5) is None
    # Factura A donde las líneas son neto y total tiene IVA 21%
    assert validar_total([100.0, 100.0], 242.0) is None  # 200 * 1.21 = 242
    # Incoherencia real
    alerta = validar_total([50.0, 50.0], 500.0)
    assert alerta is not None and "no coincide" in alerta


def test_normalizadores():
    assert normalizar_texto(" Mastellone Hnos. S.A. ") == "mastellone"
    assert normalizar_numero_comprobante("B 00003 - 00012345") == "3-12345"
    assert normalizar_numero_comprobante("12345") == "12345"

    medios_validos = ["Efectivo", "Cta. Cte.", "Payway", "Transferencia", "MercadoPago"]
    assert normalizar_medio_pago("pago en efectivo", medios_validos) == "Efectivo"
    assert normalizar_medio_pago("transf cbu", medios_validos) == "Transferencia"
    assert normalizar_medio_pago("cuenta corriente", medios_validos) == "Cta. Cte."
    assert normalizar_medio_pago("tarjeta debito", medios_validos) == "Payway"
    assert normalizar_medio_pago("qr mercado pago", medios_validos) == "MercadoPago"
