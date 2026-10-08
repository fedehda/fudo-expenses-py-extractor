"""Memoria persistente (SQLite): proveedores, señales de huella, comprobantes y pendientes."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .huella import Senales
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
