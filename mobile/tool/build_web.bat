@echo off
rem Musteri uygulamasinin web surumunu derleyip firebase\hosting klasorune koyar (mutfak ekrani korunur).
cd /d "%~dp0.."
call flutter build web --release --base-href / %*
if errorlevel 1 exit /b 1
for /d %%D in (..\firebase\hosting\*) do (
  if /i not "%%~nxD"=="mutfak" if /i not "%%~nxD"==".well-known" rmdir /s /q "%%D"
)
del /q ..\firebase\hosting\*.* 2>nul
xcopy /e /i /y /q build\web ..\firebase\hosting >nul
echo Web surumu: firebase\hosting
