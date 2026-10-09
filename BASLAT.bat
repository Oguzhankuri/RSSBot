@echo off
chcp 65001 >nul
title Bulten Studyosu
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [Kurulum] Sanal ortam olusturuluyor...
  python -m venv .venv || goto :hata
)
".venv\Scripts\python.exe" -c "import streamlit" 2>nul || (
  echo [Kurulum] Paketler yukleniyor, ilk seferde birkac dakika surebilir...
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :hata
)

echo Panel aciliyor... Kapatmak icin bu pencereyi kapat.
".venv\Scripts\python.exe" -m streamlit run panel\app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
goto :eof

:hata
echo.
echo Bir sorun oldu. Python 3.10+ kurulu mu? (python.org)
pause
