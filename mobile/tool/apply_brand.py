#!/usr/bin/env python3
"""
Kafeye özel ayarları (assets/brand.json) uygulama projesine uygular. Her yeni kafe için brand.json'u
doldurup bir kez çalıştırın:  python3 tool/apply_brand.py   (Pillow gerekir: pip install pillow)

Yaptıkları:
  - Android: uygulama adı, paket adı (applicationId), masa QR bağlantısının uygulamayı açması (App Links),
    bildirim izni; simgeler (logo varsa logodan, yoksa marka renginde baş harf).
  - Web: başlık, renkler, simgeler, bildirim servis çalışanı (firebase-messaging-sw.js).
Tekrar çalıştırmak güvenlidir; yalnızca bu alanları günceller.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def path(*p):
    return os.path.join(ROOT, *p)


def read(p):
    with open(path(p), encoding='utf-8') as f:
        return f.read()


def write(p, text):
    with open(path(p), 'w', encoding='utf-8') as f:
        f.write(text)


def xml_escape(s):
    return s.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')


def android(brand):
    package = brand.get('androidPackage') or 'com.nexpos.kafe_app'
    if not re.fullmatch(r'[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+', package):
        sys.exit(f"androidPackage geçersiz: {package} (ör. com.kafeadi.app)")
    g = read('android/app/build.gradle.kts')
    write('android/app/build.gradle.kts', re.sub(r'applicationId = "[^"]*"', f'applicationId = "{package}"', g))

    m = read('android/app/src/main/AndroidManifest.xml')
    m = re.sub(r'android:label="[^"]*"', f'android:label="{xml_escape(brand["appName"])}"', m, count=1)
    if 'POST_NOTIFICATIONS' not in m:
        m = m.replace('<application', '<uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>\n'
                                       '    <application', 1)
    # Masadaki QR (https://<webHost>/masa/...) uygulama yüklüyse uygulamayı açar
    m = re.sub(r'\n\s*<!-- nexpos:applinks -->.*?<!-- /nexpos:applinks -->', '', m, flags=re.DOTALL)
    host = brand.get('webHost')
    if host:
        block = (f'\n            <!-- nexpos:applinks -->\n'
                 f'            <intent-filter android:autoVerify="true">\n'
                 f'                <action android:name="android.intent.action.VIEW"/>\n'
                 f'                <category android:name="android.intent.category.DEFAULT"/>\n'
                 f'                <category android:name="android.intent.category.BROWSABLE"/>\n'
                 f'                <data android:scheme="https" android:host="{xml_escape(host)}" android:pathPrefix="/masa/"/>\n'
                 f'            </intent-filter>\n'
                 f'            <!-- /nexpos:applinks -->')
        m = m.replace('            </intent-filter>\n        </activity>',
                      '            </intent-filter>' + block + '\n        </activity>', 1)
    write('android/app/src/main/AndroidManifest.xml', m)
    return package


def web(brand):
    color = brand.get('primaryColor', '#6B4226')
    man = json.loads(read('web/manifest.json'))
    man.update(name=brand['appName'], short_name=brand['appName'][:12], theme_color=color, background_color='#FAF7F2',
               description=brand.get('slogan') or f"{brand['appName']} — menü, sadakat kartı ve sipariş")
    write('web/manifest.json', json.dumps(man, ensure_ascii=False, indent=4) + '\n')
    html = read('web/index.html')
    html = re.sub(r'<title>.*?</title>', f'<title>{xml_escape(brand["appName"])}</title>', html)
    html = re.sub(r'(<meta name="apple-mobile-web-app-title" content=")[^"]*', lambda m: m.group(1) + xml_escape(brand['appName']), html)
    html = re.sub(r'(<meta name="description" content=")[^"]*',
                  lambda m: m.group(1) + xml_escape(man['description']), html)
    write('web/index.html', html)
    # Web bildirimleri: Firebase'in servis çalışanı (uygulama kapalıyken gelen bildirimi gösterir)
    fb = {k: v for k, v in (brand.get('firebase') or {}).items() if k in
          ('apiKey', 'appId', 'messagingSenderId', 'projectId', 'authDomain', 'storageBucket')}
    write('web/firebase-messaging-sw.js', (
        "// apply_brand.py üretir — elle değiştirmeyin.\n"
        "importScripts('https://www.gstatic.com/firebasejs/10.14.1/firebase-app-compat.js');\n"
        "importScripts('https://www.gstatic.com/firebasejs/10.14.1/firebase-messaging-compat.js');\n"
        f"firebase.initializeApp({json.dumps(fb, ensure_ascii=False)});\n"
        "firebase.messaging();\n"))


def asset_links(brand, package):
    """Masa QR bağlantısının uygulamayı doğrudan açması için (Android App Links): imza parmak izi gerekir."""
    sha = brand.get('androidSha256')
    if not sha or not brand.get('webHost'):
        return False
    out = os.path.join(ROOT, '..', 'firebase', 'hosting', '.well-known')
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'assetlinks.json'), 'w', encoding='utf-8') as f:
        json.dump([{'relation': ['delegate_permission/common.handle_all_urls'],
                    'target': {'namespace': 'android_app', 'package_name': package, 'sha256_cert_fingerprints': [sha]}}],
                  f, indent=2)
    return True


def icons(brand):
    from PIL import Image, ImageDraw, ImageFont
    logo = brand.get('logoAsset')
    color = brand.get('primaryColor', '#6B4226')

    def make(size, padding=0.0, round_corners=True):
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if logo and os.path.exists(path(logo)):
            src = Image.open(path(logo)).convert('RGBA')
            inner = int(size * (1 - 2 * padding))
            src.thumbnail((inner, inner), Image.LANCZOS)
            if padding:
                d.rectangle([0, 0, size, size], fill=color)
            img.paste(src, ((size - src.width) // 2, (size - src.height) // 2), src)
            return img
        if round_corners and not padding:
            d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=color)
        else:
            d.rectangle([0, 0, size, size], fill=color)
        letter = brand['appName'].strip()[:1].upper() or 'K'
        font = ImageFont.truetype(path('assets/fonts/Nunito-800.ttf'), int(size * (0.5 - padding)))
        box = d.textbbox((0, 0), letter, font=font)
        d.text(((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]), letter,
               font=font, fill='white')
        return img

    for folder, size in (('mdpi', 48), ('hdpi', 72), ('xhdpi', 96), ('xxhdpi', 144), ('xxxhdpi', 192)):
        make(size).save(path(f'android/app/src/main/res/mipmap-{folder}/ic_launcher.png'))
    make(192).save(path('web/icons/Icon-192.png'))
    make(512).save(path('web/icons/Icon-512.png'))
    make(192, padding=0.12, round_corners=False).save(path('web/icons/Icon-maskable-192.png'))
    make(512, padding=0.12, round_corners=False).save(path('web/icons/Icon-maskable-512.png'))
    make(32).save(path('web/favicon.png'))
    os.makedirs(path('store'), exist_ok=True)
    make(512, round_corners=False).save(path('store/icon_512.png'))  # Google Play mağaza simgesi (512×512)


def main():
    brand = json.loads(read('assets/brand.json'))
    if not brand.get('appName'):
        sys.exit("brand.json: appName gerekli.")
    package = android(brand)
    web(brand)
    icons(brand)
    links = asset_links(brand, package)
    warn = "  ⚠ emulator.enabled true: canlı derlemede false yapın." if (brand.get('emulator') or {}).get('enabled') else ""
    print(f"Uygulandı: {brand['appName']} · {package} · {brand.get('webHost') or '(webHost yok: masa QR uygulamayı açmaz)'}"
          + ("" if links else "\n  i androidSha256 yok: masa QR'ı tarayıcıda açılır (uygulama yüklü olsa da)")
          + ("\n" + warn if warn else ""))


if __name__ == '__main__':
    main()
