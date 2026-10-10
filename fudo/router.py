"""Router de procesamiento: decide la estrategia por tipo de ticket,
resuelve la identidad del proveedor (por CUIT, catálogo o huella),
ejecuta validaciones determinísticas y prepara las filas para Fudo.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .catalogo import CatalogoFudo
from .config import Config
from .esquema import ExtraccionComprobante, TipoDocumento
from .extractores import IANoDisponible, MotorIA, construir_prompt
from .huella import Candidato, rankear, senales_de
from .imagen import abrir_imagen, hash_archivo, optimizar_para_ia
from .memoria import Memoria
from .ocr_offline import easyocr_disponible, extraer_con_ocr_offline
from .qr_arca import DatosQR, leer_qr_arca
from .validaciones import (
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


@dataclass
class ResultadoProcesamiento:
    archivo: Path
    hash_sha256: str
    estado: str  # "OK", "REVISAR", "DUPLICADO", "PENDIENTE", "ERROR"
    estrategia: str  # "QR_ARCA + IA", "QR_ARCA (OFFLINE)", "IA", "OCR_OFFLINE", etc.
    fila_gastos: Optional[Dict[str, Any]] = None  # Las 11 columnas oficiales de Fudo
    fila_revisar: Optional[Dict[str, Any]] = None  # Entrada para la hoja 'Revisar' si requiere atención
    motivos: List[str] = field(default_factory=list)
    extraccion: Optional[ExtraccionComprobante] = None
    candidatos_huella: List[Candidato] = field(default_factory=list)
    proveedor_id_asociado: Optional[int] = None


class RouterTickets:
    def __init__(self, catalogo: CatalogoFudo, memoria: Memoria, motor_ia: MotorIA, cfg: type[Config] = Config):
        self.catalogo = catalogo
        self.memoria = memoria
        self.ia = motor_ia
        self.cfg = cfg

    def procesar(self, ruta: Path, lote_id: str) -> ResultadoProcesamiento:
        h = hash_archivo(ruta)

        # 1. Detección de duplicado por contenido exacto (hash SHA-256)
        archivo_previo = self.memoria.hash_procesado(h)
        if archivo_previo:
            return ResultadoProcesamiento(
                archivo=ruta,
                hash_sha256=h,
                estado="DUPLICADO",
                estrategia="HASH_DUPLICADO",
                motivos=[f"Este archivo ya fue procesado anteriormente (original: {archivo_previo})"]
            )

        img_completa = abrir_imagen(ruta)
        datos_qr: Optional[DatosQR] = None

        # 2. Intento de lectura de QR ARCA
        if img_completa:
            try:
                datos_qr = leer_qr_arca(img_completa)
            except Exception as e:
                print(f"    [!] Error al buscar QR en {ruta.name}: {e}")

        # 3. Extracción de datos (IA o contingencia OCR)
        extraccion: Optional[ExtraccionComprobante] = None
        estrategia_usada = ""

        bytes_ia, mime_ia = optimizar_para_ia(ruta, img_completa)

        if datos_qr:
            contexto_qr = (
                f"CUIT Emisor: {datos_qr.cuit}, Tipo: {datos_qr.tipo_fudo} ({datos_qr.tipo_descripcion}), "
                f"Número: {datos_qr.numero}, Total: ${datos_qr.importe_pesos:,.2f}, Fecha: {datos_qr.fecha}"
            )
            if self.ia.disponible:
                try:
                    prompt = construir_prompt(self.catalogo, contexto_qr=contexto_qr)
                    res_ia = self.ia.extraer(bytes_ia, mime_ia, prompt)
                    extraccion = res_ia.extraccion
                    estrategia_usada = f"QR_ARCA + {res_ia.motor}"
                except IANoDisponible:
                    # IA no disponible pero tenemos el QR: podemos procesar la cabecera exacta offline
                    extraccion = ExtraccionComprobante(
                        tipo_documento=TipoDocumento.factura_electronica,
                        evidencia_tipo="QR ARCA verificado offline",
                        tiene_nombre_emisor=True,
                        cuit_emisor=datos_qr.cuit,
                        fecha_emision=datos_qr.fecha,
                        tipo_comprobante=datos_qr.tipo_fudo,
                        numero_comprobante=datos_qr.numero,
                        monto_total=datos_qr.importe_pesos,
                        articulos=[],
                        categoria_fudo_sugerida=None,
                        medio_pago_impreso=None
                    )
                    estrategia_usada = "QR_ARCA (OFFLINE)"
            else:
                extraccion = ExtraccionComprobante(
                    tipo_documento=TipoDocumento.factura_electronica,
                    evidencia_tipo="QR ARCA verificado offline (sin IA)",
                    tiene_nombre_emisor=True,
                    cuit_emisor=datos_qr.cuit,
                    fecha_emision=datos_qr.fecha,
                    tipo_comprobante=datos_qr.tipo_fudo,
                    numero_comprobante=datos_qr.numero,
                    monto_total=datos_qr.importe_pesos,
                    articulos=[],
                    categoria_fudo_sugerida=None,
                    medio_pago_impreso=None
                )
                estrategia_usada = "QR_ARCA (OFFLINE)"

            # Forzar los campos fiscales determinísticos del QR
            extraccion.cuit_emisor = datos_qr.cuit
            extraccion.fecha_emision = datos_qr.fecha
            extraccion.tipo_comprobante = datos_qr.tipo_fudo
            extraccion.numero_comprobante = datos_qr.numero
            extraccion.monto_total = datos_qr.importe_pesos

        else:
            # Sin QR: extracción general con IA
            if self.ia.disponible:
                try:
                    prompt = construir_prompt(self.catalogo)
                    res_ia = self.ia.extraer(bytes_ia, mime_ia, prompt)
                    extraccion = res_ia.extraccion
                    estrategia_usada = res_ia.motor
                except IANoDisponible as e:
                    # IA no respondió: probar OCR local si está disponible o mandar a pendientes
                    if (self.cfg.ocr_si_falla_ia or not self.ia.disponible) and img_completa:
                        try:
                            extraccion = extraer_con_ocr_offline(ruta, img_completa)
                            estrategia_usada = "OCR_OFFLINE"
                        except Exception:
                            extraccion = None

                    if not extraccion:
                        intentos = self.memoria.marcar_pendiente(h, ruta.name, str(e))
                        return ResultadoProcesamiento(
                            archivo=ruta,
                            hash_sha256=h,
                            estado="PENDIENTE",
                            estrategia="COLA_PENDIENTES",
                            motivos=[f"Servicio de IA saturado o sin conexión. Guardado en cola de pendientes (intento {intentos})."]
                        )
            else:
                # Sin IA configurada: probar OCR local
                if img_completa:
                    try:
                        extraccion = extraer_con_ocr_offline(ruta, img_completa)
                        estrategia_usada = "OCR_OFFLINE"
                    except Exception as err:
                        self.memoria.marcar_pendiente(h, ruta.name, str(err))
                        return ResultadoProcesamiento(
                            archivo=ruta,
                            hash_sha256=h,
                            estado="PENDIENTE",
                            estrategia="COLA_PENDIENTES",
                            motivos=["Sin conexión a IA ni OCR local disponible. Ticket encolado para reintento."]
                        )

        if not extraccion:
            return ResultadoProcesamiento(
                archivo=ruta,
                hash_sha256=h,
                estado="ERROR",
                estrategia="FALLIDA",
                motivos=["No se pudo extraer información del comprobante."]
            )

        # 4. Reconciliación del Proveedor y Memoria por Huella
        cuit_clean = extraccion.cuit_emisor if cuit_valido(extraccion.cuit_emisor) else None
        proveedor_final = ""
        categoria_final = ""
        caja_final = ""
        medio_pago_final = ""
        proveedor_id_asoc = None
        candidatos_huella: List[Candidato] = []
        motivo_proveedor = ""

        # A) Búsqueda por CUIT en memoria
        datos_mem_cuit = self.memoria.buscar_por_cuit(cuit_clean) if cuit_clean else None
        if datos_mem_cuit:
            proveedor_final = datos_mem_cuit["proveedor_fudo"] or datos_mem_cuit["razon_social"]
            categoria_final = datos_mem_cuit["categoria_habitual"] or ""
            caja_final = datos_mem_cuit["caja_habitual"] or ""
            medio_pago_final = datos_mem_cuit["medio_pago_habitual"] or ""
            proveedor_id_asoc = datos_mem_cuit["id"]
            motivo_proveedor = f"CUIT {formatear_cuit(cuit_clean)} en memoria"

        # B) Coincidencia por nombre en catálogo o memoria
        if not proveedor_final:
            nombre_cand = extraccion.proveedor_fudo_match or extraccion.razon_social
            prov_cat, puntaje_cat = self.catalogo.proveedor_catalogo(nombre_cand)
            if prov_cat and puntaje_cat >= 0.88:
                proveedor_final = prov_cat
                motivo_proveedor = f"Catálogo Fudo ({puntaje_cat:.0%})"
                # Buscar si tenemos datos habituales de este proveedor del catálogo
                mem_cat = self.memoria.buscar_por_nombre(prov_cat)
                if mem_cat:
                    categoria_final = mem_cat["categoria_habitual"] or ""
                    caja_final = mem_cat["caja_habitual"] or ""
                    medio_pago_final = mem_cat["medio_pago_habitual"] or ""
                    proveedor_id_asoc = mem_cat["id"]

        # C) Comprobantes sin nombre / remitos / presupuestos: Memoria por Huella
        es_sin_nombre = (not extraccion.tiene_nombre_emisor) or (not proveedor_final and not extraccion.razon_social)
        if not proveedor_final or es_sin_nombre:
            senales = senales_de(extraccion, cuit_clean)
            todas_senales = self.memoria.todas_las_senales()
            candidatos_huella = rankear(senales, todas_senales, top=3)

            if candidatos_huella:
                mejor = candidatos_huella[0]
                if mejor.puntaje >= self.cfg.umbral_huella_alto:
                    # Coincidencia fuerte por huella (teléfono, alias, etc.)
                    proveedor_final = mejor.nombre
                    proveedor_id_asoc = mejor.proveedor_id
                    motivo_proveedor = f"Huella {mejor.puntaje:.0%} ({'; '.join(mejor.razones[:2])})"
                    mem_huella = self.memoria.obtener(mejor.proveedor_id)
                    if mem_huella:
                        categoria_final = mem_huella["categoria_habitual"] or ""
                        caja_final = mem_huella["caja_habitual"] or ""
                        medio_pago_final = mem_huella["medio_pago_habitual"] or ""
                elif mejor.puntaje >= self.cfg.umbral_huella_gris:
                    # Zona gris: se sugiere el mejor pero se envía a revisión
                    proveedor_final = mejor.nombre
                    proveedor_id_asoc = mejor.proveedor_id
                    motivo_proveedor = f"Sugerido por huella ({mejor.puntaje:.0%})"
                else:
                    proveedor_final = self.cfg.proveedor_desconocido
                    motivo_proveedor = "Proveedor sin nombre ni huella conocida"
            else:
                proveedor_final = extraccion.razon_social or self.cfg.proveedor_desconocido
                motivo_proveedor = "Nuevo proveedor sin señales previas"

        # Categoría fallback
        if not categoria_final:
            cat_sug, _ = self.catalogo.categoria_valida(extraccion.categoria_fudo_sugerida)
            categoria_final = cat_sug or "Compras y proveedores"

        # Medio de pago fallback
        medio_ticket = normalizar_medio_pago(extraccion.medio_pago_impreso, self.catalogo.medios_pago)
        if medio_ticket:
            medio_pago_final = medio_ticket
        elif not medio_pago_final:
            medio_pago_final = "Efectivo"

        # Comentario (Artículos detallados)
        partes_articulos = []
        for art in extraccion.articulos:
            txt = art.descripcion.strip()
            if art.cantidad:
                txt = f"{art.cantidad} {txt}"
            if art.importe:
                txt = f"{txt} (${art.importe:,.2f})"
            partes_articulos.append(txt)

        detalle_str = ", ".join(partes_articulos)
        if not detalle_str:
            detalle_str = extraccion.razon_social or "Comprobante de compra"

        prefijo_comentario = ""
        if estrategia_usada == "OCR_OFFLINE":
            prefijo_comentario = "[REVISAR - OCR LOCAL] "
        elif "OPENAI" in estrategia_usada:
            prefijo_comentario = "[FALLBACK OPENAI] "
        elif "Huella" in motivo_proveedor:
            prefijo_comentario = f"[{motivo_proveedor}] "

        comentario_final = f"{prefijo_comentario}{detalle_str}"

        # 5. Validaciones determinísticas
        alertas: List[str] = []

        # A) CUIT
        if cuit_clean:
            if not cuit_valido(cuit_clean):
                alertas.append(f"CUIT inválido ({cuit_clean})")
        elif extraccion.tipo_documento in (TipoDocumento.factura_electronica, TipoDocumento.tique_fiscal):
            alertas.append("Comprobante fiscal sin CUIT de emisor legible")

        # B) Fecha
        fecha_obj = parsear_fecha(extraccion.fecha_emision)
        alerta_fecha = validar_fecha(fecha_obj, self.cfg.max_dias_antiguedad)
        if alerta_fecha:
            alertas.append(alerta_fecha)
        fecha_str = formatear_fecha_fudo(fecha_obj) if fecha_obj else date.today().strftime("%d-%m-%Y")

        # C) Monto y coherencia de ítems
        monto_float = round(float(extraccion.monto_total or 0.0), 2)
        if monto_float <= 0:
            alertas.append("Monto total es cero o ilegible")
        else:
            importes_lineas = [a.importe for a in extraccion.articulos if a.importe is not None]
            alerta_tot = validar_total(importes_lineas, monto_float)
            if alerta_tot:
                alertas.append(alerta_tot)

        # D) Tipo de comprobante
        tipo_comp = extraccion.tipo_comprobante or "Factura B"
        if tipo_comp not in self.catalogo.tipos_comprobante:
            tipo_comp = "Factura B"

        num_comp = extraccion.numero_comprobante or ""
        num_norm = normalizar_numero_comprobante(num_comp)

        # E) Duplicado fiscal (mismo CUIT + tipo + número)
        dup_fiscal = self.memoria.duplicado_fiscal(cuit_clean, tipo_comp, num_norm)
        if dup_fiscal:
            alertas.append(f"Duplicado fiscal de {dup_fiscal} (CUIT {cuit_clean} {tipo_comp} {num_comp})")

        # F) Proveedor sin identificar o con huella de baja confianza
        if proveedor_final == self.cfg.proveedor_desconocido:
            alertas.append("Proveedor no identificado (requiere asignación manual)")
        elif candidatos_huella and candidatos_huella[0].puntaje < self.cfg.umbral_huella_alto:
            cand_str = ", ".join(f"{c.nombre} ({c.puntaje:.0%})" for c in candidatos_huella[:2])
            alertas.append(f"Huella en zona de duda: {cand_str}")

        # Si había advertencias en el QR (ej: es Nota de Crédito)
        if datos_qr and datos_qr.advertencias:
            alertas.extend(datos_qr.advertencias)

        # 6. Construir las 11 columnas de Fudo
        fila_gastos = {
            "fecha": fecha_str,
            "monto": monto_float,
            "proveedor": proveedor_final,
            "categoria": categoria_final,
            "comentario": comentario_final,
            "tipo_comprobante": tipo_comp,
            "numero_comprobante": num_comp,
            "medio_pago": medio_pago_final,
            "caja": caja_final,
            "fecha_pago": fecha_str,
            "fecha_vencimiento": None,
        }

        # 7. Determinar estado y fila de Revisión
        fila_revisar = None
        estado_final = "OK"

        if alertas:
            estado_final = "REVISAR"
            cand_texto = ""
            if candidatos_huella:
                cand_texto = " / ".join(f"{c.nombre} ({c.puntaje:.0%})" for c in candidatos_huella[:3])
            fila_revisar = {
                "archivo": ruta.name,
                "motivos": " | ".join(alertas),
                "tipo_detectado": extraccion.tipo_documento.value if hasattr(extraccion.tipo_documento, "value") else str(extraccion.tipo_documento),
                "cuit": formatear_cuit(cuit_clean) or "",
                "proveedor_asignado": proveedor_final,
                "candidatos_sugeridos": cand_texto,
                "monto": monto_float,
                "estrategia": estrategia_usada,
            }

        # Guardar automáticamente en memoria si el proveedor es conocido y válido
        if cuit_clean or (proveedor_final and proveedor_final != self.cfg.proveedor_desconocido):
            pid_guardado = self.memoria.guardar_proveedor(
                cuit=cuit_clean,
                razon_social=extraccion.razon_social,
                proveedor_fudo=proveedor_final,
                categoria=categoria_final,
                caja=caja_final,
                medio_pago=medio_pago_final,
                confirmado=False,
                pid=proveedor_id_asoc
            )
            # Guardar señales de huella si se asoció un id
            if pid_guardado:
                senales = senales_de(extraccion, cuit_clean)
                self.memoria.agregar_senales(pid_guardado, senales)
                proveedor_id_asoc = pid_guardado

        # Guardar artículos en el histórico de precios
        if extraccion.articulos:
            self.memoria.guardar_articulos(
                comprobante_hash=h,
                fecha=fecha_str,
                proveedor_id=proveedor_id_asoc,
                proveedor_nombre=proveedor_final or extraccion.razon_social or "Sin identificar",
                articulos=extraccion.articulos,
                tipo_comprobante=tipo_comp,
                numero_comprobante=num_comp,
                archivo=ruta.name
            )

        return ResultadoProcesamiento(
            archivo=ruta,
            hash_sha256=h,
            estado=estado_final,
            estrategia=estrategia_usada,
            fila_gastos=fila_gastos,
            fila_revisar=fila_revisar,
            motivos=alertas,
            extraccion=extraccion,
            candidatos_huella=candidatos_huella,
            proveedor_id_asociado=proveedor_id_asoc
        )
