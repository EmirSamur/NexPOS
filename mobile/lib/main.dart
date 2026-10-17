// Kafe müşteri uygulaması (NexPOS, 11. ekran).
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'brand.dart';
import 'data/repo.dart';
import 'state.dart';
import 'ui/shell.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final brand = await Brand.load();
  final f = brand.firebase;
  await Firebase.initializeApp(
    options: FirebaseOptions(
      apiKey: f['apiKey'] ?? '',
      appId: f['appId'] ?? '',
      messagingSenderId: f['messagingSenderId'] ?? '',
      projectId: f['projectId'] ?? '',
      authDomain: f['authDomain'],
      storageBucket: f['storageBucket'],
    ),
  );
  final repo = FirebaseRepo(brand);
  if (brand.useEmulator) await repo.useEmulators();
  runApp(KafeApp(state: AppState(brand, repo)..start()));
}

class KafeApp extends StatelessWidget {
  final AppState state;
  const KafeApp({super.key, required this.state});

  @override
  Widget build(BuildContext context) {
    return AppScope(
      state: state,
      child: MaterialApp(
        title: state.brand.appName,
        debugShowCheckedModeBanner: false,
        theme: state.brand.theme(),
        locale: const Locale('tr'),
        supportedLocales: const [Locale('tr')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        home: const Root(),
      ),
    );
  }
}
