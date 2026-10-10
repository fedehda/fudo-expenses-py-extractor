@echo off
title FudoExtractor - Panel de Control & Precios (Dev)
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
    start "" .venv\Scripts\python.exe procesador.py --gui
) else (
    start "" python procesador.py --gui
)
