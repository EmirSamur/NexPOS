@echo off
rem NexPOS'u emulatore bagli acar. Gercek kasa verisine (nexpos.db) dokunmaz: nexpos_demo.db kullanir.
cd /d "%~dp0.."
if not exist .venv (
  echo Ilk calistirma: Python paketleri kuruluyor...
  python -m venv .venv
  call .venv\Scripts\pip install -r requirements.txt
)
set NEXPOS_EMULATOR=1
call .venv\Scripts\python main.py
pause
