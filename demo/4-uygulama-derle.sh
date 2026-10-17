#!/usr/bin/env bash
# Müşteri uygulamasının web sürümünü derler (Flutter gerekir). Sonra: http://127.0.0.1:5005
cd "$(dirname "$0")/../mobile" && tool/build_web.sh
