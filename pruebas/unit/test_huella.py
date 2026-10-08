"""Pruebas unitarias para huella de proveedor y reconocimiento por señales."""
from fudo.esquema import Articulo, ExtraccionComprobante, Huella, TipoDocumento
from fudo.huella import normalizar_alias, normalizar_telefono, puntuar, rankear, senales_de


def test_normalizadores_huella():
    assert normalizar_telefono("11-4567-8901") == "45678901"
    assert normalizar_telefono("+54 9 11 4567-8901") == "45678901"
    assert normalizar_telefono("123") is None

    assert normalizar_alias("Alias: verduleria.juan.mp") == "verduleria.juan.mp"
    assert normalizar_alias("CBU: 0170099220000012345678") == "0170099220000012345678"


def test_puntuar_huella_por_telefono():
    ticket = {"telefono": {"45678901"}, "items": {"tomate", "lechuga"}}
    guardadas = {"telefono": {"45678901"}, "items": {"papa", "cebolla"}}

    puntaje, razones = puntuar(ticket, guardadas)
    assert puntaje >= 0.90
    assert any("telefono" in r for r in razones)


def test_puntuar_huella_conflicto_cuit():
    # Si tienen CUITs distintos y válidos, el puntaje debe ser 0.0 aunque tengan teléfonos parecidos
    ticket = {"cuit": {"30709497401"}, "telefono": {"45678901"}}
    guardadas = {"cuit": {"30123456789"}, "telefono": {"45678901"}}

    puntaje, razones = puntuar(ticket, guardadas)
    assert puntaje == 0.0
    assert "CUIT distinto" in razones


def test_rankear_huella():
    ticket_ext = ExtraccionComprobante(
        tipo_documento=TipoDocumento.remito,
        tiene_nombre_emisor=False,
        articulos=[Articulo(descripcion="5 cajones Tomate perita"), Articulo(descripcion="2 bolsas Papa negra")],
        huella=Huella(
            telefonos=["11-5555-4321"],
            direccion="Mercado Central Nave 4 Puesto 12"
        )
    )
    senales_ticket = senales_de(ticket_ext)

    # Base de memoria simulada
    memoria_senales = {
        1: ("Verdulería Don Pepe", {
            "telefono": {"55554321"},
            "direccion": {"mercado central nave 4 puesto 12"},
            "items": {"tomate", "papa", "cebolla"}
        }),
        2: ("Carnicería El Trébol", {
            "telefono": {"11112222"},
            "items": {"lomo", "asado", "vacio"}
        })
    }

    candidatos = rankear(senales_ticket, memoria_senales, top=2)
    assert len(candidatos) > 0
    assert candidatos[0].nombre == "Verdulería Don Pepe"
    assert candidatos[0].puntaje >= 0.95
