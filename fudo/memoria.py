"""Memoria persistente (SQLite): proveedores, señales de huella, comprobantes y pendientes."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .huella import Senales
from .precios import (
    ItemHistorico,
    ResumenProducto,
    calcular_resumen_producto,
    inferir_precio_unitario,
    normalizar_producto,
)
from .validaciones import cuit_valido, normalizar_texto, solo_digitos


class Memoria:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._init()

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def _init(self):
        with self._conn() as c:
            # Tabla original (v1): se conserva tal cual para no perder datos
            c.execute("""
                CREATE TABLE IF NOT EXISTS proveedores_memoria (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cuit TEXT UNIQUE,
                    razon_social TEXT,
                    proveedor_fudo TEXT,
                    categoria_habitual TEXT,
                    caja_habitual TEXT,
                    medio_pago_habitual TEXT,
                    ultima_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
            columnas = {r["name"] for r in c.execute("PRAGMA table_info(proveedores_memoria)")}
            if "confirmado" not in columnas:
                c.execute("ALTER TABLE proveedores_memoria ADD COLUMN confirmado INTEGER DEFAULT 0")
            c.execute("""
                CREATE TABLE IF NOT EXISTS senales_proveedor (
                    proveedor_id INTEGER NOT NULL,
                    tipo TEXT NOT NULL,
                    valor TEXT NOT NULL,
                    veces INTEGER DEFAULT 1,
                    ultima TIMESTAMP,
                    UNIQUE(proveedor_id, tipo, valor)
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS comprobantes (
                    hash TEXT PRIMARY KEY,
                    cuit TEXT,
                    tipo TEXT,
                    numero_norm TEXT,
                    fecha TEXT,
                    monto REAL,
                    archivo TEXT,
                    lote TEXT,
                    proveedor_id INTEGER,
                    creado TIMESTAMP
                )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_comp_fiscal ON comprobantes(cuit, tipo, numero_norm)")
            c.execute("""
                CREATE TABLE IF NOT EXISTS pendientes (
                    hash TEXT PRIMARY KEY,
                    archivo TEXT,
                    intentos INTEGER DEFAULT 0,
                    ultimo_error TEXT,
                    actualizado TIMESTAMP
                )""")
            c.execute("""
                CREATE TABLE IF NOT EXISTS articulos_historico (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    comprobante_hash TEXT NOT NULL,
                    fecha TEXT NOT NULL,
                    proveedor_id INTEGER,
                    proveedor_nombre TEXT NOT NULL,
                    producto_original TEXT NOT NULL,
                    producto_normalizado TEXT NOT NULL,
                    cantidad_texto TEXT,
                    cantidad_numerica REAL,
                    unidad_medida TEXT,
                    precio_unitario REAL,
                    importe_total REAL,
                    tipo_comprobante TEXT,
                    numero_comprobante TEXT,
                    archivo TEXT,
                    creado TIMESTAMP
                )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_art_prod_norm ON articulos_historico(producto_normalizado)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_art_prov ON articulos_historico(proveedor_nombre)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_art_fecha ON articulos_historico(fecha)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_art_hash ON articulos_historico(comprobante_hash)")

    # ------------------------------------------------------------------ proveedores
    def obtener(self, pid: int) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM proveedores_memoria WHERE id = ?", (pid,)).fetchone()
            return dict(r) if r else None

    def buscar_por_cuit(self, cuit: Optional[str]) -> Optional[Dict[str, Any]]:
        d = solo_digitos(cuit)
        if len(d) != 11:
            return None
        with self._conn() as c:
            r = c.execute("SELECT * FROM proveedores_memoria WHERE cuit = ?", (d,)).fetchone()
            return dict(r) if r else None

    def buscar_por_nombre(self, nombre: Optional[str]) -> Optional[Dict[str, Any]]:
        objetivo = normalizar_texto(nombre)
        if len(objetivo) < 3:
            return None
        with self._conn() as c:
            for r in c.execute("SELECT * FROM proveedores_memoria ORDER BY confirmado DESC, id"):
                if objetivo in (normalizar_texto(r["proveedor_fudo"]), normalizar_texto(r["razon_social"])):
                    return dict(r)
        return None

    def guardar_proveedor(self, *, cuit: Optional[str], razon_social: Optional[str], proveedor_fudo: Optional[str],
                          categoria: Optional[str], caja: Optional[str], medio_pago: Optional[str],
                          confirmado: bool = False, pid: Optional[int] = None) -> Optional[int]:
        """Crea o actualiza un proveedor. Si confirmado=True (viene de --aprender) pisa los habituales."""
        d = solo_digitos(cuit)
        d = d if cuit_valido(d) else None
        ahora = datetime.now().isoformat(timespec="seconds")
        existente = (self.obtener(pid) if pid else None) or (self.buscar_por_cuit(d) if d else None) \
            or self.buscar_por_nombre(proveedor_fudo) or self.buscar_por_nombre(razon_social)
        with self._conn() as c:
            if existente:
                if confirmado:
                    c.execute("""UPDATE proveedores_memoria SET
                        cuit = COALESCE(?, cuit), razon_social = COALESCE(?, razon_social),
                        proveedor_fudo = COALESCE(?, proveedor_fudo), categoria_habitual = COALESCE(?, categoria_habitual),
                        caja_habitual = COALESCE(?, caja_habitual), medio_pago_habitual = COALESCE(?, medio_pago_habitual),
                        confirmado = 1, ultima_actualizacion = ? WHERE id = ?""",
                              (d, razon_social, proveedor_fudo, categoria, caja, medio_pago, ahora, existente["id"]))
                else:
                    c.execute("""UPDATE proveedores_memoria SET
                        cuit = COALESCE(cuit, ?), razon_social = COALESCE(razon_social, ?),
                        proveedor_fudo = COALESCE(proveedor_fudo, ?), categoria_habitual = COALESCE(categoria_habitual, ?),
                        caja_habitual = COALESCE(caja_habitual, ?), medio_pago_habitual = COALESCE(medio_pago_habitual, ?),
                        ultima_actualizacion = ? WHERE id = ?""",
                              (d, razon_social, proveedor_fudo, categoria, caja, medio_pago, ahora, existente["id"]))
                return existente["id"]
            if not (d or proveedor_fudo or razon_social):
                return None
            cur = c.execute("""INSERT INTO proveedores_memoria
                (cuit, razon_social, proveedor_fudo, categoria_habitual, caja_habitual, medio_pago_habitual, confirmado, ultima_actualizacion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (d, razon_social, proveedor_fudo, categoria, caja, medio_pago, int(confirmado), ahora))
            return cur.lastrowid

    # ------------------------------------------------------------------ señales
    def agregar_senales(self, pid: int, senales: Senales):
        if not pid or not senales:
            return
        ahora = datetime.now().isoformat(timespec="seconds")
        with self._conn() as c:
            for tipo, valores in senales.items():
                for v in valores:
                    c.execute("""INSERT INTO senales_proveedor (proveedor_id, tipo, valor, veces, ultima)
                                 VALUES (?, ?, ?, 1, ?)
                                 ON CONFLICT(proveedor_id, tipo, valor) DO UPDATE SET veces = veces + 1, ultima = excluded.ultima""",
                              (pid, tipo, v, ahora))

    def todas_las_senales(self) -> Dict[int, Tuple[str, Senales]]:
        res: Dict[int, Tuple[str, Senales]] = {}
        with self._conn() as c:
            nombres = {r["id"]: (r["proveedor_fudo"] or r["razon_social"] or f"Proveedor #{r['id']}", r["cuit"])
                       for r in c.execute("SELECT id, proveedor_fudo, razon_social, cuit FROM proveedores_memoria")}
            for pid, (nombre, cuit) in nombres.items():
                res[pid] = (nombre, {"cuit": {cuit}} if cuit else {})
            for r in c.execute("SELECT proveedor_id, tipo, valor FROM senales_proveedor"):
                if r["proveedor_id"] in res:
                    res[r["proveedor_id"]][1].setdefault(r["tipo"], set()).add(r["valor"])
        return {pid: v for pid, v in res.items() if v[1]}

    # ------------------------------------------------------------------ comprobantes / duplicados
    def hash_procesado(self, h: str) -> Optional[str]:
        with self._conn() as c:
            r = c.execute("SELECT archivo FROM comprobantes WHERE hash = ?", (h,)).fetchone()
            return r["archivo"] if r else None

    def duplicado_fiscal(self, cuit: Optional[str], tipo: Optional[str], numero_norm: str) -> Optional[str]:
        d = solo_digitos(cuit)
        if len(d) != 11 or not numero_norm or "-" not in numero_norm:
            return None
        with self._conn() as c:
            r = c.execute("SELECT archivo FROM comprobantes WHERE cuit = ? AND tipo = ? AND numero_norm = ?",
                          (d, tipo, numero_norm)).fetchone()
            return r["archivo"] if r else None

    def registrar_comprobante(self, *, h: str, cuit: Optional[str], tipo: Optional[str], numero_norm: str,
                              fecha: Optional[str], monto: Optional[float], archivo: str, lote: str,
                              proveedor_id: Optional[int]):
        d = solo_digitos(cuit)
        with self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO comprobantes
                (hash, cuit, tipo, numero_norm, fecha, monto, archivo, lote, proveedor_id, creado)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                      (h, d if len(d) == 11 else None, tipo, numero_norm, fecha, monto, archivo, lote,
                       proveedor_id, datetime.now().isoformat(timespec="seconds")))
            c.execute("DELETE FROM pendientes WHERE hash = ?", (h,))

    # ------------------------------------------------------------------ cola de pendientes
    def marcar_pendiente(self, h: str, archivo: str, error: str) -> int:
        with self._conn() as c:
            c.execute("""INSERT INTO pendientes (hash, archivo, intentos, ultimo_error, actualizado)
                         VALUES (?, ?, 1, ?, ?)
                         ON CONFLICT(hash) DO UPDATE SET intentos = intentos + 1, ultimo_error = excluded.ultimo_error,
                         archivo = excluded.archivo, actualizado = excluded.actualizado""",
                      (h, archivo, error[:300], datetime.now().isoformat(timespec="seconds")))
            return c.execute("SELECT intentos FROM pendientes WHERE hash = ?", (h,)).fetchone()["intentos"]

    def es_pendiente(self, h: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM pendientes WHERE hash = ?", (h,)).fetchone() is not None

    # ------------------------------------------------------------------ articulos y precios
    def guardar_articulos(self, *, comprobante_hash: str, fecha: str, proveedor_id: Optional[int],
                          proveedor_nombre: str, articulos: List[Any],
                          tipo_comprobante: Optional[str] = None,
                          numero_comprobante: Optional[str] = None,
                          archivo: Optional[str] = None) -> int:
        if not articulos or not comprobante_hash:
            return 0
        with self._conn() as c:
            c.execute("DELETE FROM articulos_historico WHERE comprobante_hash = ?", (comprobante_hash,))
            guardados = 0
            ahora = datetime.now().isoformat(timespec="seconds")
            for art in articulos:
                desc = getattr(art, "descripcion", "") or ""
                if not desc.strip():
                    continue
                prod_norm = normalizar_producto(desc)
                cant_txt = getattr(art, "cantidad", None)
                cant_num = getattr(art, "cantidad_numerica", None)
                unidad = getattr(art, "unidad_medida", None)
                p_unit = getattr(art, "precio_unitario", None)
                imp = getattr(art, "importe", None)

                p_unit_final = inferir_precio_unitario(imp, cant_num, p_unit)

                c.execute("""
                    INSERT INTO articulos_historico (
                        comprobante_hash, fecha, proveedor_id, proveedor_nombre,
                        producto_original, producto_normalizado, cantidad_texto,
                        cantidad_numerica, unidad_medida, precio_unitario,
                        importe_total, tipo_comprobante, numero_comprobante,
                        archivo, creado
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    comprobante_hash, fecha, proveedor_id, proveedor_nombre or "Sin identificar",
                    desc.strip(), prod_norm, cant_txt, cant_num, unidad,
                    p_unit_final, imp, tipo_comprobante, numero_comprobante,
                    archivo, ahora
                ))
                guardados += 1
            return guardados

    def consultar_todos_los_articulos(self, filtro_texto: Optional[str] = None,
                                      filtro_proveedor: Optional[str] = None,
                                      limite: int = 5000) -> List[ItemHistorico]:
        query = "SELECT * FROM articulos_historico WHERE 1=1"
        params = []
        if filtro_texto and filtro_texto.strip():
            query += " AND (producto_normalizado LIKE ? OR producto_original LIKE ?)"
            patron = f"%{normalizar_producto(filtro_texto)}%"
            params.extend([patron, f"%{filtro_texto.strip()}%"])
        if filtro_proveedor and filtro_proveedor.strip() and filtro_proveedor != "Todos":
            query += " AND proveedor_nombre = ?"
            params.append(filtro_proveedor.strip())
        query += " ORDER BY fecha DESC, id DESC LIMIT ?"
        params.append(limite)

        with self._conn() as c:
            rows = c.execute(query, params).fetchall()
            return [
                ItemHistorico(
                    id=r["id"],
                    comprobante_hash=r["comprobante_hash"],
                    fecha=r["fecha"],
                    proveedor_id=r["proveedor_id"],
                    proveedor_nombre=r["proveedor_nombre"],
                    producto_original=r["producto_original"],
                    producto_normalizado=r["producto_normalizado"],
                    cantidad_texto=r["cantidad_texto"],
                    cantidad_numerica=r["cantidad_numerica"],
                    unidad_medida=r["unidad_medida"],
                    precio_unitario=r["precio_unitario"],
                    importe_total=r["importe_total"],
                    tipo_comprobante=r["tipo_comprobante"],
                    numero_comprobante=r["numero_comprobante"],
                    archivo=r["archivo"]
                ) for r in rows
            ]

    def consultar_resumen_productos(self, filtro_texto: Optional[str] = None,
                                    filtro_proveedor: Optional[str] = None) -> List[ResumenProducto]:
        items = self.consultar_todos_los_articulos(filtro_texto=filtro_texto,
                                                   filtro_proveedor=filtro_proveedor,
                                                   limite=10000)
        grupos: Dict[str, List[ItemHistorico]] = {}
        for it in items:
            grupos.setdefault(it.producto_normalizado, []).append(it)

        resumenes: List[ResumenProducto] = []
        for prod_norm, lista in grupos.items():
            res = calcular_resumen_producto(lista)
            if res:
                resumenes.append(res)

        resumenes.sort(key=lambda x: x.nombre_mostrar.lower())
        return resumenes

    def consultar_historico_producto(self, producto_normalizado: str) -> List[ItemHistorico]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT * FROM articulos_historico
                WHERE producto_normalizado = ?
                ORDER BY fecha DESC, id DESC
            """, (producto_normalizado,)).fetchall()
            return [
                ItemHistorico(
                    id=r["id"],
                    comprobante_hash=r["comprobante_hash"],
                    fecha=r["fecha"],
                    proveedor_id=r["proveedor_id"],
                    proveedor_nombre=r["proveedor_nombre"],
                    producto_original=r["producto_original"],
                    producto_normalizado=r["producto_normalizado"],
                    cantidad_texto=r["cantidad_texto"],
                    cantidad_numerica=r["cantidad_numerica"],
                    unidad_medida=r["unidad_medida"],
                    precio_unitario=r["precio_unitario"],
                    importe_total=r["importe_total"],
                    tipo_comprobante=r["tipo_comprobante"],
                    numero_comprobante=r["numero_comprobante"],
                    archivo=r["archivo"]
                ) for r in rows
            ]

    def consultar_alertas_aumento(self, umbral_pct: float = 10.0) -> List[ResumenProducto]:
        resumenes = self.consultar_resumen_productos()
        return [r for r in resumenes if r.variacion_pct >= umbral_pct and r.precio_anterior is not None]

    def listar_proveedores_con_articulos(self) -> List[str]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT DISTINCT proveedor_nombre FROM articulos_historico
                WHERE proveedor_nombre IS NOT NULL AND proveedor_nombre != ''
                ORDER BY proveedor_nombre ASC
            """).fetchall()
            return [r["proveedor_nombre"] for r in rows]
