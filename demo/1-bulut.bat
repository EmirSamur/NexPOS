@echo off
rem NexPOS deneme: Firebase emulatorleri (bulutun bilgisayardaki kopyasi). Pencere acik kalsin.
rem Kapatirken Ctrl+C: veriler firebase\demo-veri klasorune kaydedilir, sonraki acilista geri gelir.
cd /d "%~dp0..\firebase"
rem Windows'ta fonksiyonlarin ilk yuklenmesi 10 saniyeyi asabiliyor (antivirus taramasi); bekleme suresi uzatilir
set FUNCTIONS_DISCOVERY_TIMEOUT=120
if not exist functions\node_modules (
  echo Ilk calistirma: paketler kuruluyor...
  pushd functions & call npm install & popd
  pushd tests & call npm install & popd
)
if exist demo-veri (
  call firebase emulators:start --project demo-nexpos --import demo-veri --export-on-exit demo-veri
) else (
  call firebase emulators:start --project demo-nexpos --export-on-exit demo-veri
)
pause
