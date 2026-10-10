"""FudoExtractor GUI - Interfaz de Escritorio Nativa (Tkinter / ttk).
Integra:
1. Procesamiento de comprobantes con logs y barra de progreso en vivo.
2. Histórico de precios, comparador de mejor proveedor y análisis temporal.
3. Alertas de aumentos de precios / inflación.
4. Ficha de productos por proveedor.
5. Herramientas de aprendizaje contable (--aprender) y evaluación (--evaluar).
"""
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any, Dict, List, Optional

from .catalogo import CatalogoFudo
from .config import BASE_DIR, Config, clave_valida
from .excel import GestorExcel, aprender_de_excel
from .extractores import MotorIA
from .memoria import Memoria
from .precios import (
    ItemHistorico,
    ResumenProducto,
    exportar_historico_precios_excel,
    normalizar_producto,
)
from .router import RouterTickets


class FudoExtractorGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("FudoExtractor v2 — Centro de Control Contable & Precios")
        self.root.geometry("1120x740")
        self.root.minsize(960, 600)

        # Configuración de rutas y memoria
        self.base_dir = BASE_DIR
        self.db_path = self.base_dir / "memoria.db"
        self.memoria = Memoria(self.db_path)
        self.catalogo = CatalogoFudo()
        self.motor_ia = MotorIA()

        # Variables de estado
        self.procesando = False
        self.hilo_proceso = None
        self.ultimo_excel_generado = None

        self._configurar_estilos()
        self._construir_ui()
        self._cargar_datos_precios()

    def _configurar_estilos(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Paleta de colores sobria y moderna
        self.color_primario = "#1B4F72"
        self.color_secundario = "#2874A6"
        self.color_acento = "#27AE60"
        self.color_alerta = "#C0392B"
        self.color_fondo = "#F8F9F9"

        self.root.configure(bg=self.color_fondo)

        self.style.configure(".", background=self.color_fondo, font=("Segoe UI", 9))
        self.style.configure("TNotebook", background=self.color_fondo)
        self.style.configure("TNotebook.Tab", padding=[14, 6], font=("Segoe UI", 9, "bold"))
        self.style.map("TNotebook.Tab",
                       background=[("selected", "#FFFFFF"), ("!selected", "#EAEDED")],
                       foreground=[("selected", self.color_primario), ("!selected", "#566573")])

        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"),
                             foreground="#FFFFFF", background=self.color_primario, padding=[12, 6])
        self.style.map("Primary.TButton",
                       background=[("active", self.color_secundario), ("disabled", "#BDC3C7")])

        self.style.configure("Action.TButton", font=("Segoe UI", 9), padding=[8, 4])
        self.style.configure("Header.TLabel", font=("Segoe UI", 13, "bold"), foreground=self.color_primario)
        self.style.configure("SubHeader.TLabel", font=("Segoe UI", 10, "bold"), foreground="#2C3E50")

        self.style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                             foreground="#1A252F", background="#EAECEE", relief="flat")
        self.style.configure("Treeview", font=("Segoe UI", 9), rowheight=24)

    def _construir_ui(self):
        # 1. Header institucional superior
        header_frame = tk.Frame(self.root, bg=self.color_primario, height=52)
        header_frame.pack(fill="x", side="top")

        lbl_logo = tk.Label(header_frame, text="🧾 FudoExtractor v2", font=("Segoe UI", 14, "bold"),
                            fg="#FFFFFF", bg=self.color_primario)
        lbl_logo.pack(side="left", padx=16, pady=10)

        ia_status = f"IA: {self.motor_ia.cfg.gemini_model}" if self.motor_ia.disponible else "IA: Sin Clave"
        lbl_ia = tk.Label(header_frame, text=ia_status, font=("Segoe UI", 9),
                          fg="#D4E6F1", bg=self.color_primario)
        lbl_ia.pack(side="right", padx=16, pady=12)

        # 2. Notebook de pestañas principales
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=8)

        # Crear contenedores de pestañas
        self.tab_procesar = ttk.Frame(self.notebook)
        self.tab_precios = ttk.Frame(self.notebook)
        self.tab_alertas = ttk.Frame(self.notebook)
        self.tab_proveedor = ttk.Frame(self.notebook)
        self.tab_herramientas = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_procesar, text="📥 Procesar Comprobantes")
        self.notebook.add(self.tab_precios, text="📊 Histórico de Precios")
        self.notebook.add(self.tab_alertas, text="🚨 Alertas de Aumento")
        self.notebook.add(self.tab_proveedor, text="🏢 Ficha Proveedores")
        self.notebook.add(self.tab_herramientas, text="🧠 Aprender / Evaluar")

        # Construir cada pestaña
        self._construir_tab_procesar()
        self._construir_tab_precios()
        self._construir_tab_alertas()
        self._construir_tab_proveedor()
        self._construir_tab_herramientas()

        # 3. Barra de estado inferior
        self.status_bar = tk.Frame(self.root, bg="#EAEDED", height=24)
        self.status_bar.pack(fill="x", side="bottom")

        self.lbl_status = tk.Label(self.status_bar, text="Listo.", font=("Segoe UI", 8),
                                   bg="#EAEDED", fg="#566573")
        self.lbl_status.pack(side="left", padx=8)

        self.lbl_db_info = tk.Label(self.status_bar, text=f"BD: {self.db_path.name}", font=("Segoe UI", 8),
                                    bg="#EAEDED", fg="#7F8C8D")
        self.lbl_db_info.pack(side="right", padx=8)

    # =========================================================================
    # PESTAÑA 1: PROCESAMIENTO DE COMPROBANTES
    # =========================================================================
    def _construir_tab_procesar(self):
        frame = self.tab_procesar

        # Opciones superiores
        opts_frame = ttk.LabelFrame(frame, text=" Configuración del Lote ", padding=10)
        opts_frame.pack(fill="x", padx=10, pady=8)

        # Carpeta Entrada
        lbl_in = ttk.Label(opts_frame, text="Carpeta de Tickets:")
        lbl_in.grid(row=0, column=0, sticky="w", pady=4)
        self.var_dir_in = tk.StringVar(value=str(self.base_dir / "input_tickets"))
        ent_in = ttk.Entry(opts_frame, textvariable=self.var_dir_in, width=54)
        ent_in.grid(row=0, column=1, padx=6, pady=4, sticky="ew")
        btn_browse_in = ttk.Button(opts_frame, text="Examinar...", style="Action.TButton",
                                   command=self._examinar_dir_in)
        btn_browse_in.grid(row=0, column=2, padx=4, pady=4)

        # Carpeta Salida
        lbl_out = ttk.Label(opts_frame, text="Carpeta Destino Excel:")
        lbl_out.grid(row=1, column=0, sticky="w", pady=4)
        self.var_dir_out = tk.StringVar(value=str(self.base_dir / "output_fudo"))
        ent_out = ttk.Entry(opts_frame, textvariable=self.var_dir_out, width=54)
        ent_out.grid(row=1, column=1, padx=6, pady=4, sticky="ew")
        btn_browse_out = ttk.Button(opts_frame, text="Examinar...", style="Action.TButton",
                                    command=self._examinar_dir_out)
        btn_browse_out.grid(row=1, column=2, padx=4, pady=4)

        # Checkbox archivar
        self.var_archivar = tk.BooleanVar(value=True)
        chk_arch = ttk.Checkbutton(opts_frame, text="Archivar comprobantes procesados en 'procesados/'",
                                   variable=self.var_archivar)
        chk_arch.grid(row=2, column=1, sticky="w", pady=4)

        opts_frame.columnconfigure(1, weight=1)

        # Botonera de Acción
        actions_frame = tk.Frame(frame, bg=self.color_fondo)
        actions_frame.pack(fill="x", padx=10, pady=4)

        self.btn_iniciar = ttk.Button(actions_frame, text="▶  Iniciar Procesamiento de Comprobantes",
                                      style="Primary.TButton", command=self._iniciar_procesamiento)
        self.btn_iniciar.pack(side="left", padx=4)

        self.btn_abrir_out = ttk.Button(actions_frame, text="📁 Abrir Carpeta de Salida", style="Action.TButton",
                                        command=self._abrir_carpeta_salida)
        self.btn_abrir_out.pack(side="left", padx=6)

        self.btn_abrir_excel = ttk.Button(actions_frame, text="📄 Abrir Último Excel Generado", style="Action.TButton",
                                          command=self._abrir_ultimo_excel, state="disabled")
        self.btn_abrir_excel.pack(side="left", padx=4)

        # Barra de progreso
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.pack(fill="x", padx=10, pady=6)

        # Consola de logs en vivo
        log_frame = ttk.LabelFrame(frame, text=" Registro de Extracción en Vivo ", padding=6)
        log_frame.pack(fill="both", expand=True, padx=10, pady=6)

        self.txt_log = ScrolledText(log_frame, wrap="word", height=14, font=("Consolas", 9),
                                    bg="#1E1E1E", fg="#F8F9F9", insertbackground="#FFFFFF")
        self.txt_log.pack(fill="both", expand=True)

        self.txt_log.tag_config("ok", foreground="#2ECC71")
        self.txt_log.tag_config("revisar", foreground="#F39C12")
        self.txt_log.tag_config("error", foreground="#E74C3C")
        self.txt_log.tag_config("info", foreground="#3498DB")
        self.txt_log.tag_config("dim", foreground="#95A5A6")
        self._log("FudoExtractor listo para procesar comprobantes.\n", "info")

    def _examinar_dir_in(self):
        d = filedialog.askdirectory(initialdir=self.var_dir_in.get(), title="Seleccionar Carpeta de Tickets")
        if d:
            self.var_dir_in.set(d)

    def _examinar_dir_out(self):
        d = filedialog.askdirectory(initialdir=self.var_dir_out.get(), title="Seleccionar Carpeta Destino")
        if d:
            self.var_dir_out.set(d)

    def _log(self, texto: str, tag: str = "dim"):
        self.txt_log.insert("end", texto, tag)
        self.txt_log.see("end")

    def _iniciar_procesamiento(self):
        if self.procesando:
            return
        dir_in = Path(self.var_dir_in.get())
        if not dir_in.exists():
            messagebox.showerror("Error", f"La carpeta de entrada no existe:\n{dir_in}")
            return

        self.procesando = True
        self.btn_iniciar.configure(state="disabled")
        self.progress.start(10)
        self.lbl_status.config(text="Procesando comprobantes...")

        self.hilo_proceso = threading.Thread(target=self._worker_procesar, daemon=True)
        self.hilo_proceso.start()

    def _worker_procesar(self):
        dir_in = Path(self.var_dir_in.get())
        dir_out = Path(self.var_dir_out.get())
        dir_out.mkdir(parents=True, exist_ok=True)
        archivar = self.var_archivar.get()

        from .config import EXTENSIONES_VALIDAS
        archivos = sorted([p for p in dir_in.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONES_VALIDAS])

        self.root.after(0, self._log, f"\n[{datetime.now().strftime('%H:%M:%S')}] Iniciando lote en: {dir_in}\n", "info")
        self.root.after(0, self._log, f"[*] Comprobantes detectados: {len(archivos)}\n", "info")

        if not archivos:
            self.root.after(0, self._log, "[i] No hay comprobantes válidos para procesar en la carpeta.\n", "dim")
            self.root.after(0, self._finalizar_proceso, None)
            return

        router = RouterTickets(catalogo=self.catalogo, memoria=self.memoria, motor_ia=self.motor_ia)
        lote_id = f"gui_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        filas_gastos = []
        filas_revisar = []
        procesados_ok = 0

        for idx, arch in enumerate(archivos, start=1):
            msg_inicio = f"[{idx}/{len(archivos)}] Analizando {arch.name}..."
            self.root.after(0, self._log, msg_inicio, "dim")

            res = router.procesar(arch, lote_id=lote_id)

            if res.estado == "DUPLICADO":
                tag = "dim"
                detalle = f" -> [DUPLICADO] {res.motivos[0] if res.motivos else ''}\n"
            elif res.estado == "OK":
                tag = "ok"
                prov = res.fila_gastos.get("proveedor", "") if res.fila_gastos else ""
                monto = res.fila_gastos.get("monto", 0.0) if res.fila_gastos else 0.0
                detalle = f" -> [OK] {prov} | ${monto:,.2f}\n"
                filas_gastos.append(res.fila_gastos)
                procesados_ok += 1
            elif res.estado == "REVISAR":
                tag = "revisar"
                prov = res.fila_gastos.get("proveedor", "") if res.fila_gastos else ""
                monto = res.fila_gastos.get("monto", 0.0) if res.fila_gastos else 0.0
                alertas = "; ".join(res.motivos[:2]) if res.motivos else ""
                detalle = f" -> [REVISAR] {prov} | ${monto:,.2f} ({alertas})\n"
                if res.fila_gastos:
                    filas_gastos.append(res.fila_gastos)
                if res.fila_revisar:
                    filas_revisar.append(res.fila_revisar)
                procesados_ok += 1
            else:
                tag = "error"
                detalle = f" -> [{res.estado}] {'; '.join(res.motivos)}\n"

            self.root.after(0, self._log, detalle, tag)

            # Archivar si corresponde
            if archivar and res.estado in ("OK", "REVISAR", "DUPLICADO"):
                dir_proc = self.base_dir / "procesados"
                dir_proc.mkdir(exist_ok=True)
                try:
                    import shutil
                    dest_arch = dir_proc / arch.name
                    if dest_arch.exists():
                        dest_arch = dir_proc / f"{arch.stem}_{datetime.now().strftime('%H%M%S')}{arch.suffix}"
                    shutil.move(str(arch), str(dest_arch))
                except Exception as e:
                    self.root.after(0, self._log, f"    [!] Error al archivar {arch.name}: {e}\n", "dim")

        # Generar Excel final
        ruta_excel_salida = None
        if filas_gastos or filas_revisar:
            nom_excel = f"Gastos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            ruta_excel_salida = dir_out / nom_excel
            gestor = GestorExcel(template_path=self.base_dir / "Plantilla-Gastos.xlsx", catalogo=self.catalogo)
            wb = gestor.crear_workbook(ruta_excel_salida)
            gestor.escribir_lote(wb, filas_gastos, filas_revisar)
            wb.save(ruta_excel_salida)
            wb.close()

            msg_fin = f"\n[OK] Excel generado con éxito:\n     {ruta_excel_salida}\n"
            self.root.after(0, self._log, msg_fin, "ok")

        self.root.after(0, self._finalizar_proceso, ruta_excel_salida)

    def _finalizar_proceso(self, ruta_excel: Optional[Path]):
        self.procesando = False
        self.progress.stop()
        self.btn_iniciar.configure(state="normal")
        self.lbl_status.config(text="Proceso finalizado.")

        if ruta_excel and ruta_excel.exists():
            self.ultimo_excel_generado = ruta_excel
            self.btn_abrir_excel.configure(state="normal")
            # Refrescar catálogo de precios
            self._cargar_datos_precios()
            messagebox.showinfo("Proceso Finalizado",
                                f"Lote completado con éxito.\nExcel generado en:\n{ruta_excel.name}")

    def _abrir_carpeta_salida(self):
        d = Path(self.var_dir_out.get())
        if d.exists():
            os.startfile(d)
        else:
            messagebox.showwarning("Aviso", "La carpeta de salida aún no existe.")

    def _abrir_ultimo_excel(self):
        if self.ultimo_excel_generado and self.ultimo_excel_generado.exists():
            os.startfile(self.ultimo_excel_generado)

    # =========================================================================
    # PESTAÑA 2: HISTÓRICO DE PRECIOS & COMPARADOR
    # =========================================================================
    def _construir_tab_precios(self):
        frame = self.tab_precios

        # Barra superior de filtros
        top_frame = ttk.LabelFrame(frame, text=" Filtros de Búsqueda y Herramientas ", padding=8)
        top_frame.pack(fill="x", padx=10, pady=6)

        lbl_b = ttk.Label(top_frame, text="Buscar Producto:")
        lbl_b.grid(row=0, column=0, padx=4, sticky="w")
        self.var_buscar_prod = tk.StringVar()
        self.var_buscar_prod.trace_add("write", lambda *_: self._filtrar_precios())
        ent_b = ttk.Entry(top_frame, textvariable=self.var_buscar_prod, width=28)
        ent_b.grid(row=0, column=1, padx=4, sticky="w")

        lbl_pv = ttk.Label(top_frame, text="Proveedor:")
        lbl_pv.grid(row=0, column=2, padx=8, sticky="w")
        self.combo_prov_filtro = ttk.Combobox(top_frame, values=["Todos"], state="readonly", width=22)
        self.combo_prov_filtro.set("Todos")
        self.combo_prov_filtro.bind("<<ComboboxSelected>>", lambda _: self._filtrar_precios())
        self.combo_prov_filtro.grid(row=0, column=3, padx=4, sticky="w")

        btn_refrescar = ttk.Button(top_frame, text="🔄 Refrescar", style="Action.TButton",
                                    command=self._cargar_datos_precios)
        btn_refrescar.grid(row=0, column=4, padx=6)

        btn_exp_excel = ttk.Button(top_frame, text="📥 Exportar Excel", style="Action.TButton",
                                   command=self._exportar_precios_excel)
        btn_exp_excel.grid(row=0, column=5, padx=6)

        top_frame.columnconfigure(6, weight=1)

        # Split visual: Tabla Arriba, Detalle Abajo
        paned = ttk.PanedWindow(frame, orient="vertical")
        paned.pack(fill="both", expand=True, padx=10, pady=6)

        # 1. Tabla de Resumen
        frame_resumen = ttk.Frame(paned)
        paned.add(frame_resumen, weight=3)

        cols = ("producto", "mejor_prov", "mejor_precio", "ultimo_prov", "ultimo_precio",
                "variacion", "ultima_fecha", "compras")
        self.tree_resumen = ttk.Treeview(frame_resumen, columns=cols, show="headings", selectmode="browse")

        self.tree_resumen.heading("producto", text="Producto")
        self.tree_resumen.heading("mejor_prov", text="Mejor Proveedor")
        self.tree_resumen.heading("mejor_precio", text="Mejor Precio")
        self.tree_resumen.heading("ultimo_prov", text="Último Proveedor")
        self.tree_resumen.heading("ultimo_precio", text="Último Precio")
        self.tree_resumen.heading("variacion", text="Variación %")
        self.tree_resumen.heading("ultima_fecha", text="Última Compra")
        self.tree_resumen.heading("compras", text="Compras")

        self.tree_resumen.column("producto", width=220, anchor="w")
        self.tree_resumen.column("mejor_prov", width=160, anchor="w")
        self.tree_resumen.column("mejor_precio", width=100, anchor="e")
        self.tree_resumen.column("ultimo_prov", width=160, anchor="w")
        self.tree_resumen.column("ultimo_precio", width=100, anchor="e")
        self.tree_resumen.column("variacion", width=95, anchor="center")
        self.tree_resumen.column("ultima_fecha", width=95, anchor="center")
        self.tree_resumen.column("compras", width=65, anchor="center")

        scroll_res_y = ttk.Scrollbar(frame_resumen, orient="vertical", command=self.tree_resumen.yview)
        self.tree_resumen.configure(yscrollcommand=scroll_res_y.set)

        self.tree_resumen.pack(side="left", fill="both", expand=True)
        scroll_res_y.pack(side="right", fill="y")

        self.tree_resumen.bind("<<TreeviewSelect>>", self._on_producto_seleccionado)

        # Tags de color para variaciones
        self.tree_resumen.tag_configure("subio", foreground="#C0392B", background="#FDEDEC")
        self.tree_resumen.tag_configure("bajo", foreground="#27AE60", background="#EAFAF1")
        self.tree_resumen.tag_configure("igual", foreground="#2C3E50")

        # 2. Panel Inferior de Detalle Cronológico
        frame_detalle = ttk.LabelFrame(paned, text=" Historial Cronológico de Compras del Producto Seleccionado ", padding=6)
        paned.add(frame_detalle, weight=2)

        cols_det = ("fecha", "proveedor", "original", "cantidad", "unidad", "precio_unit", "total", "comprobante")
        self.tree_detalle = ttk.Treeview(frame_detalle, columns=cols_det, show="headings", selectmode="browse")

        self.tree_detalle.heading("fecha", text="Fecha")
        self.tree_detalle.heading("proveedor", text="Proveedor")
        self.tree_detalle.heading("original", text="Descripción Facturada")
        self.tree_detalle.heading("cantidad", text="Cant.")
        self.tree_detalle.heading("unidad", text="Unidad")
        self.tree_detalle.heading("precio_unit", text="P. Unitario")
        self.tree_detalle.heading("total", text="Total")
        self.tree_detalle.heading("comprobante", text="Comprobante")

        self.tree_detalle.column("fecha", width=85, anchor="center")
        self.tree_detalle.column("proveedor", width=180, anchor="w")
        self.tree_detalle.column("original", width=220, anchor="w")
        self.tree_detalle.column("cantidad", width=60, anchor="center")
        self.tree_detalle.column("unidad", width=60, anchor="center")
        self.tree_detalle.column("precio_unit", width=95, anchor="e")
        self.tree_detalle.column("total", width=95, anchor="e")
        self.tree_detalle.column("comprobante", width=120, anchor="w")

        scroll_det_y = ttk.Scrollbar(frame_detalle, orient="vertical", command=self.tree_detalle.yview)
        self.tree_detalle.configure(yscrollcommand=scroll_det_y.set)

        self.tree_detalle.pack(side="left", fill="both", expand=True)
        scroll_det_y.pack(side="right", fill="y")

    def _cargar_datos_precios(self):
        # Actualizar lista de proveedores en combo
        provs = ["Todos"] + self.memoria.listar_proveedores_con_articulos()
        self.combo_prov_filtro["values"] = provs

        self._filtrar_precios()

    def _filtrar_precios(self):
        txt_buscar = self.var_buscar_prod.get().strip()
        prov_sel = self.combo_prov_filtro.get()

        for item in self.tree_resumen.get_children():
            self.tree_resumen.delete(item)

        resumenes = self.memoria.consultar_resumen_productos(filtro_texto=txt_buscar,
                                                             filtro_proveedor=prov_sel)

        for r in resumenes:
            tag = "igual"
            if r.variacion_pct >= 10.0:
                tag = "subio"
            elif r.variacion_pct <= -5.0:
                tag = "bajo"

            var_txt = f"{r.variacion_pct:+.1f}%" if r.precio_anterior else "-"
            mp_txt = f"${r.mejor_precio:,.2f}" if r.mejor_precio else "-"
            up_txt = f"${r.ultimo_precio:,.2f}" if r.ultimo_precio else "-"

            self.tree_resumen.insert(
                "", "end",
                iid=r.producto_normalizado,
                values=(
                    r.nombre_mostrar,
                    r.mejor_proveedor,
                    mp_txt,
                    r.ultimo_proveedor,
                    up_txt,
                    var_txt,
                    r.ultima_fecha,
                    r.total_compras
                ),
                tags=(tag,)
            )

        # Limpiar detalle inferior
        for it in self.tree_detalle.get_children():
            self.tree_detalle.delete(it)

        self.lbl_status.config(text=f"Catálogo de Precios: {len(resumenes)} productos indexados.")

    def _on_producto_seleccionado(self, event):
        sel = self.tree_resumen.selection()
        if not sel:
            return
        prod_norm = sel[0]

        for it in self.tree_detalle.get_children():
            self.tree_detalle.delete(it)

        items = self.memoria.consultar_historico_producto(prod_norm)
        for it in items:
            pu_txt = f"${it.precio_unitario:,.2f}" if it.precio_unitario else "-"
            tot_txt = f"${it.importe_total:,.2f}" if it.importe_total else "-"
            comp_txt = f"{it.tipo_comprobante or ''} {it.numero_comprobante or ''}".strip()
            cant_txt = str(it.cantidad_numerica) if it.cantidad_numerica else (it.cantidad_texto or "-")

            self.tree_detalle.insert(
                "", "end",
                values=(
                    it.fecha,
                    it.proveedor_nombre,
                    it.producto_original,
                    cant_txt,
                    it.unidad_medida or "-",
                    pu_txt,
                    tot_txt,
                    comp_txt
                )
            )

    def _exportar_precios_excel(self):
        destino = self.base_dir / "output_fudo" / f"Historico_Precios_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        items = self.memoria.consultar_todos_los_articulos(limite=50000)
        resumenes = self.memoria.consultar_resumen_productos()

        if not items:
            messagebox.showinfo("Aviso", "No hay compras registradas en el histórico de precios para exportar.")
            return

        exportar_historico_precios_excel(items, resumenes, destino)
        res = messagebox.askyesno("Exportación Exitosa",
                                  f"Reporte generado con éxito en:\n{destino.name}\n\n¿Deseas abrir el archivo ahora?")
        if res:
            os.startfile(destino)

    # =========================================================================
    # PESTAÑA 3: ALERTAS DE AUMENTO
    # =========================================================================
    def _construir_tab_alertas(self):
        frame = self.tab_alertas

        top_f = ttk.Frame(frame, padding=8)
        top_f.pack(fill="x", padx=10, pady=4)

        lbl = ttk.Label(top_f, text="Umbral mínimo de aumento (%):", font=("Segoe UI", 9, "bold"))
        lbl.pack(side="left", padx=4)

        self.var_umbral = tk.DoubleVar(value=10.0)
        spin_umbral = ttk.Spinbox(top_f, from_=1.0, to=100.0, increment=5.0, textvariable=self.var_umbral, width=6)
        spin_umbral.pack(side="left", padx=6)

        btn_filtrar = ttk.Button(top_f, text="Filtrar Alertas", style="Action.TButton",
                                 command=self._cargar_alertas)
        btn_filtrar.pack(side="left", padx=6)

        # Tabla de Alertas
        cols = ("producto", "proveedor", "precio_ant", "precio_nuevo", "dif_pesos", "aumento_pct", "fecha")
        self.tree_alertas = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")

        self.tree_alertas.heading("producto", text="Producto")
        self.tree_alertas.heading("proveedor", text="Proveedor que Aumentó")
        self.tree_alertas.heading("precio_ant", text="Precio Anterior")
        self.tree_alertas.heading("precio_nuevo", text="Precio Nuevo")
        self.tree_alertas.heading("dif_pesos", text="Aumento ($)")
        self.tree_alertas.heading("aumento_pct", text="Aumento (%)")
        self.tree_alertas.heading("fecha", text="Fecha de Compra")

        self.tree_alertas.column("producto", width=220, anchor="w")
        self.tree_alertas.column("proveedor", width=180, anchor="w")
        self.tree_alertas.column("precio_ant", width=100, anchor="e")
        self.tree_alertas.column("precio_nuevo", width=100, anchor="e")
        self.tree_alertas.column("dif_pesos", width=100, anchor="e")
        self.tree_alertas.column("aumento_pct", width=100, anchor="center")
        self.tree_alertas.column("fecha", width=100, anchor="center")

        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.tree_alertas.yview)
        self.tree_alertas.configure(yscrollcommand=scroll_y.set)

        self.tree_alertas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=6)
        scroll_y.pack(side="right", fill="y", padx=(0, 10), pady=6)

        self.tree_alertas.tag_configure("alerta", foreground="#922B21", background="#FADBD8", font=("Segoe UI", 9, "bold"))

        self._cargar_alertas()

    def _cargar_alertas(self):
        for it in self.tree_alertas.get_children():
            self.tree_alertas.delete(it)

        umbral = self.var_umbral.get()
        alertas = self.memoria.consultar_alertas_aumento(umbral_pct=umbral)

        for r in alertas:
            p_ant = r.precio_anterior or 0.0
            dif = r.ultimo_precio - p_ant

            self.tree_alertas.insert(
                "", "end",
                values=(
                    r.nombre_mostrar,
                    r.ultimo_proveedor,
                    f"${p_ant:,.2f}",
                    f"${r.ultimo_precio:,.2f}",
                    f"+${dif:,.2f}",
                    f"+{r.variacion_pct:.1f}%",
                    r.ultima_fecha
                ),
                tags=("alerta",)
            )

    # =========================================================================
    # PESTAÑA 4: FICHA POR PROVEEDOR
    # =========================================================================
    def _construir_tab_proveedor(self):
        frame = self.tab_proveedor

        top_f = ttk.Frame(frame, padding=8)
        top_f.pack(fill="x", padx=10, pady=4)

        lbl = ttk.Label(top_f, text="Seleccionar Proveedor:", font=("Segoe UI", 9, "bold"))
        lbl.pack(side="left", padx=4)

        self.combo_ficha_prov = ttk.Combobox(top_f, state="readonly", width=28)
        self.combo_ficha_prov.pack(side="left", padx=6)
        self.combo_ficha_prov.bind("<<ComboboxSelected>>", lambda _: self._cargar_ficha_proveedor())

        # Tabla de productos del proveedor
        cols = ("producto", "ultimo_precio", "ultima_fecha", "total_compras", "comprobante")
        self.tree_prov_items = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")

        self.tree_prov_items.heading("producto", text="Producto Provisto")
        self.tree_prov_items.heading("ultimo_precio", text="Último Precio")
        self.tree_prov_items.heading("ultima_fecha", text="Última Entrega")
        self.tree_prov_items.heading("total_compras", text="Compras Registradas")
        self.tree_prov_items.heading("comprobante", text="Último Comprobante")

        self.tree_prov_items.column("producto", width=280, anchor="w")
        self.tree_prov_items.column("ultimo_precio", width=120, anchor="e")
        self.tree_prov_items.column("ultima_fecha", width=110, anchor="center")
        self.tree_prov_items.column("total_compras", width=120, anchor="center")
        self.tree_prov_items.column("comprobante", width=160, anchor="w")

        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.tree_prov_items.yview)
        self.tree_prov_items.configure(yscrollcommand=scroll_y.set)

        self.tree_prov_items.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=6)
        scroll_y.pack(side="right", fill="y", padx=(0, 10), pady=6)

        # Cargar valores iniciales
        provs = self.memoria.listar_proveedores_con_articulos()
        self.combo_ficha_prov["values"] = provs
        if provs:
            self.combo_ficha_prov.set(provs[0])
            self._cargar_ficha_proveedor()

    def _cargar_ficha_proveedor(self):
        prov = self.combo_ficha_prov.get()
        if not prov:
            return

        for it in self.tree_prov_items.get_children():
            self.tree_prov_items.delete(it)

        resumenes = self.memoria.consultar_resumen_productos(filtro_proveedor=prov)
        for r in resumenes:
            self.tree_prov_items.insert(
                "", "end",
                values=(
                    r.nombre_mostrar,
                    f"${r.ultimo_precio:,.2f}",
                    r.ultima_fecha,
                    r.total_compras,
                    r.ultimo_proveedor
                )
            )

    # =========================================================================
    # PESTAÑA 5: HERRAMIENTAS (APRENDER Y EVALUAR)
    # =========================================================================
    def _construir_tab_herramientas(self):
        frame = self.tab_herramientas

        # 1. Grupo Aprendizaje
        grp_aprender = ttk.LabelFrame(frame, text=" Aprendizaje Continuo (--aprender) ", padding=12)
        grp_aprender.pack(fill="x", padx=12, pady=10)

        lbl_desc = ttk.Label(grp_aprender, text="Selecciona un archivo Excel donde hayas corregido proveedores, categorías o medios de pago:\nEl sistema aprenderá las huellas para futuros comprobantes sin membrete.",
                             justify="left")
        lbl_desc.pack(anchor="w", pady=(0, 8))

        f_arch = ttk.Frame(grp_aprender)
        f_arch.pack(fill="x", pady=4)

        self.var_excel_aprender = tk.StringVar(value=str(self.base_dir / "output_fudo"))
        ent_ap = ttk.Entry(f_arch, textvariable=self.var_excel_aprender, width=60)
        ent_ap.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_browse_ap = ttk.Button(f_arch, text="Examinar Excel...", style="Action.TButton",
                                    command=self._examinar_excel_aprender)
        btn_browse_ap.pack(side="left")

        btn_run_ap = ttk.Button(grp_aprender, text="🧠  Aprender de las Correcciones del Excel",
                                style="Primary.TButton", command=self._ejecutar_aprendizaje)
        btn_run_ap.pack(anchor="w", pady=8)

        # 2. Grupo Evaluación
        grp_eval = ttk.LabelFrame(frame, text=" Banco de Pruebas y Benchmarking (--evaluar) ", padding=12)
        grp_eval.pack(fill="x", padx=12, pady=10)

        lbl_eval = ttk.Label(grp_eval, text="Ejecuta el evaluador de precisión sobre el banco de pruebas real sin alterar la memoria de producción.\nGenera o actualiza el gabarito de auditoría comparativa.")
        lbl_eval.pack(anchor="w", pady=(0, 8))

        btn_run_eval = ttk.Button(grp_eval, text="🔬  Ejecutar Evaluación de Precisión",
                                  style="Action.TButton", command=self._ejecutar_evaluacion_gui)
        btn_run_eval.pack(anchor="w", pady=4)

    def _examinar_excel_aprender(self):
        f = filedialog.askopenfilename(initialdir=self.base_dir / "output_fudo",
                                       title="Seleccionar Excel Corregido",
                                       filetypes=[("Archivos Excel", "*.xlsx")])
        if f:
            self.var_excel_aprender.set(f)

    def _ejecutar_aprendizaje(self):
        ruta = Path(self.var_excel_aprender.get())
        if not ruta.is_file():
            messagebox.showerror("Error", f"Archivo Excel no encontrado:\n{ruta}")
            return

        try:
            res = aprender_de_excel(ruta, self.memoria)
            conf = res.get("proveedores_confirmados", 0)
            rev = res.get("revisiones_procesadas", 0)
            messagebox.showinfo("Aprendizaje Completado",
                                f"Se procesó el archivo:\n{ruta.name}\n\n"
                                f"• Proveedores confirmados en memoria: {conf}\n"
                                f"• Revisiones y huellas asociadas: {rev}")
            self._cargar_datos_precios()
        except Exception as e:
            messagebox.showerror("Error en Aprendizaje", f"Ocurrió un error al leer el Excel:\n{e}")

    def _ejecutar_evaluacion_gui(self):
        # Abrir consola con el proceso de evaluación
        messagebox.showinfo("Evaluación",
                            "Se ejecutará el evaluador en una ventana de consola para que observes el progreso ticket por ticket.")
        cmd = f'"{sys.executable}" procesador.py --evaluar'
        subprocess.Popen(cmd, cwd=str(self.base_dir), shell=True)


def iniciar_app():
    root = tk.Tk()
    app = FudoExtractorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    iniciar_app()
