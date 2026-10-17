#!/usr/bin/env bash
# Müşteri uygulamasının web sürümünü derleyip Firebase Hosting klasörüne koyar (mutfak ekranı korunur).
# Masadaki QR (https://<kafe>/masa/<masa>?t=<anahtar>) bu sürümü açar. Sonra: cd firebase && firebase deploy --only hosting
set -euo pipefail
cd "$(dirname "$0")/.."
flutter build web --release --base-href / "$@"
OUT=../firebase/hosting
find "$OUT" -mindepth 1 -maxdepth 1 ! -name mutfak ! -name .well-known -exec rm -rf {} +
cp -r build/web/. "$OUT"/
echo "Web sürümü: $OUT"
