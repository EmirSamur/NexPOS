#!/usr/bin/env bash
# NexPOS deneme: Firebase emülatörleri. Kapatırken Ctrl+C: veriler firebase/demo-veri'ye kaydedilir.
set -e
cd "$(dirname "$0")/../firebase"
# Fonksiyonların ilk yüklenmesi yavaş bilgisayarda 10 saniyeyi aşabiliyor
export FUNCTIONS_DISCOVERY_TIMEOUT=120
[ -d functions/node_modules ] || (cd functions && npm install)
[ -d tests/node_modules ] || (cd tests && npm install)
if [ -d demo-veri ]; then
  firebase emulators:start --project demo-nexpos --import demo-veri --export-on-exit demo-veri
else
  firebase emulators:start --project demo-nexpos --export-on-exit demo-veri
fi
