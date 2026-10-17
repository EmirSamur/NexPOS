// Kafeye özel ayarlar (assets/brand.json). Uygulama birden çok kafeye satılır: her kafe için yalnızca
// bu dosya, logo ve paket adı değişir; kod aynı kalır. Kafe bilgisi (adres, saatler, KVKK metni) ise
// panelden settings/app'e yazılır ve uygulamaya canlı iner.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;

class Brand {
  final String appName;
  final String slogan;
  final Color primary;
  final Color accent;
  final String? logoAsset;
  final Map<String, String> firebase;
  final String functionsRegion;
  final bool useEmulator;
  final String emulatorHost;

  const Brand({
    required this.appName,
    this.slogan = '',
    required this.primary,
    required this.accent,
    this.logoAsset,
    this.firebase = const {},
    this.functionsRegion = 'europe-west1',
    this.useEmulator = false,
    this.emulatorHost = '127.0.0.1',
  });

  static Color _color(Object? hex, Color fallback) {
    if (hex is! String || !RegExp(r'^#[0-9a-fA-F]{6}$').hasMatch(hex)) return fallback;
    return Color(int.parse('FF${hex.substring(1)}', radix: 16));
  }

  static Brand fromJson(Map<String, dynamic> d) {
    final fb = d['firebase'] is Map ? (d['firebase'] as Map).map((k, v) => MapEntry('$k', '$v')) : <String, String>{};
    final emu = d['emulator'] is Map ? d['emulator'] as Map : const {};
    return Brand(
      appName: d['appName'] is String ? d['appName'] as String : 'Kafe',
      slogan: d['slogan'] is String ? d['slogan'] as String : '',
      primary: _color(d['primaryColor'], const Color(0xFF6B4226)),
      accent: _color(d['accentColor'], const Color(0xFFE8A15A)),
      logoAsset: d['logoAsset'] is String ? d['logoAsset'] as String : null,
      firebase: fb,
      functionsRegion: d['functionsRegion'] is String ? d['functionsRegion'] as String : 'europe-west1',
      useEmulator: emu['enabled'] == true,
      emulatorHost: emu['host'] is String ? emu['host'] as String : '127.0.0.1',
    );
  }

  static Future<Brand> load() async =>
      Brand.fromJson(jsonDecode(await rootBundle.loadString('assets/brand.json')) as Map<String, dynamic>);

  ThemeData theme() {
    final scheme = ColorScheme.fromSeed(seedColor: primary, primary: primary, secondary: accent);
    return ThemeData(
      colorScheme: scheme,
      useMaterial3: true,
      fontFamily: 'Nunito', // uygulamayla gelir (Türkçe harfler ve ₺ dahil; internetsiz de aynı görünür)
      scaffoldBackgroundColor: const Color(0xFFFAF7F2),
      appBarTheme: AppBarTheme(backgroundColor: const Color(0xFFFAF7F2), foregroundColor: primary, elevation: 0),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(minimumSize: const Size(48, 52), textStyle: const TextStyle(fontWeight: FontWeight.w600)),
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: Colors.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        margin: EdgeInsets.zero,
      ),
    );
  }
}
