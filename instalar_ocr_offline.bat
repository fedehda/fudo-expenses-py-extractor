@echo off
title FudoExtractor - Instalador de OCR Offline
cd /d "%~dp0"
echo ========================================================
echo        INSTALADOR DE OCR OFFLINE (OPCIONAL)
echo ========================================================
echo.
echo Este script prepara el soporte de EasyOCR para permitir
echo procesar tickets de forma 100%% offline sin conexion a IA.
echo.
echo NOTA: Si utilizas la API de Gemini (gratuita), NO es necesario
echo instalar este componente, ya que Gemini procesa con mayor
echo precision y rapidez.
echo.
set /p RESP="Deseas proceder con la instalacion de EasyOCR? (s/n): "
if /i not "%RESP%"=="s" goto fin

echo.
echo [*] Instalando dependencias de EasyOCR...
pip install torch torchvision easyocr --extra-index-url https://download.pytorch.org/whl/cpu

if errorlevel 1 (
    echo [!] Hubo un error al instalar las dependencias con pip.
    goto fin
)

mkdir ocr_offline\modelos 2>nul
echo.
echo [OK] EasyOCR instalado con exito.
echo      FudoExtractor detectara automaticamente el motor en modo offline.
echo.

:fin
echo ========================================================
echo Presiona una tecla para cerrar.
echo ========================================================
pause >nul
