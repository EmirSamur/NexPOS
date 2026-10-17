@echo off
rem Musteri uygulamasinin web surumunu derler (Flutter gerekir). Sonra: http://127.0.0.1:5005
cd /d "%~dp0..\mobile"
call tool\build_web.bat
start http://127.0.0.1:5005
pause
