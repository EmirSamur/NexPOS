// Mağazaların istediği herkese açık sayfalar (web): /gizlilik (aydınlatma metni) ve /hesap-sil (hesap silme yolu).
// Metin panelden (Pazarlama → Mobil Uygulama) gelir; uygulama içindekiyle aynıdır.
import 'package:flutter/material.dart';

import '../state.dart';
import 'common.dart';

class PolicyPage extends StatelessWidget {
  final bool deletion;
  const PolicyPage({super.key, this.deletion = false});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final t = Theme.of(context).textTheme;
    final name = s.info.cafeName.isNotEmpty ? s.info.cafeName : s.brand.appName;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: ListView(padding: const EdgeInsets.all(24), children: [
              Row(children: [
                const BrandLogo(size: 48),
                const SizedBox(width: 12),
                Expanded(child: Text(name, style: t.headlineSmall?.copyWith(fontWeight: FontWeight.bold))),
              ]),
              const SizedBox(height: 20),
              if (deletion) ...[
                Text('Hesabını ve verilerini silme', style: t.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
                const SizedBox(height: 12),
                const Text('Uygulamada: Profil → "Hesabımı sil". Ad, telefon ve doğum günün hemen silinir; giriş hesabın '
                    'kapanır, ödüllerin iptal olur. Kafe kayıtlarındaki geçmiş satışlar adsız (anonim) olarak kalır '
                    '(yasal saklama yükümlülüğü).'),
                const SizedBox(height: 12),
                Text('Uygulamaya giremiyorsan kafeye başvurabilirsin'
                    '${s.info.phone.isNotEmpty ? ': ${s.info.phone}' : ''}${s.info.address.isNotEmpty ? ' · ${s.info.address}' : ''}. '
                    'Kasada telefon numaranla birlikte isteğini ilet; kaydın aynı şekilde silinir.'),
                const SizedBox(height: 24),
              ],
              Text('Aydınlatma metni (KVKK)', style: t.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
              const SizedBox(height: 12),
              SelectableText(s.info.kvkkText.isNotEmpty ? s.info.kvkkText : 'Metin yükleniyor…', key: const Key('policyText')),
            ]),
          ),
        ),
      ),
    );
  }
}
