import 'package:flutter/material.dart';

import '../state.dart';
import 'common.dart';
import 'home.dart';
import 'login.dart';
import 'menu.dart';
import 'order.dart';
import 'profile.dart';

/// Giriş durumuna göre ekran: yükleniyor · giriş · profil formu · uygulama (misafir de menüyü görür)
class Root extends StatefulWidget {
  const Root({super.key});

  @override
  State<Root> createState() => _RootState();
}

class _RootState extends State<Root> {
  // Masadaki QR ile gelen müşteri önce menüyü görür; giriş sipariş gönderirken istenir
  late bool _guest = AppScope.read(context).table != null;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    s.requestLogin = () => setState(() => _guest = false);
    switch (s.phase) {
      case Phase.loading:
        return const Scaffold(body: Center(child: CircularProgressIndicator()));
      case Phase.needsProfile:
        return const ProfileSetupScreen();
      case Phase.signedOut:
        if (!_guest) return LoginScreen(onGuest: () => setState(() => _guest = true));
        return HomeShell(onLogin: () => setState(() => _guest = false));
      case Phase.ready:
        return HomeShell(onLogin: () {});
    }
  }
}

class HomeShell extends StatefulWidget {
  final VoidCallback onLogin;
  const HomeShell({super.key, required this.onLogin});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  late int _tab;
  AppState? _state;

  @override
  void initState() {
    super.initState();
    _tab = AppScope.read(context).table != null ? 1 : 0; // masadaki QR ile açılınca menüden başlar
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final s = AppScope.of(context);
    if (!identical(s, _state)) {
      _state?.removeListener(_showNotice);
      _state = s..addListener(_showNotice);
    }
  }

  @override
  void dispose() {
    _state?.removeListener(_showNotice);
    super.dispose();
  }

  // "Siparişin hazır" gibi bildirimler hangi ekranda olunursa olsun görünür
  void _showNotice() {
    final n = _state?.notice;
    if (n == null || !mounted) return;
    _state!.takeNotice();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) showMessage(context, n);
    });
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      HomeTab(onLogin: widget.onLogin, onMenu: () => setState(() => _tab = 1)),
      const MenuTab(),
      ProfileTab(onLogin: widget.onLogin),
    ];
    return Scaffold(
      body: Column(children: [
        const TableBanner(),
        Expanded(child: IndexedStack(index: _tab, children: pages)),
        const CartBar(),
      ]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home), label: 'Ana sayfa'),
          NavigationDestination(icon: Icon(Icons.local_cafe_outlined), selectedIcon: Icon(Icons.local_cafe), label: 'Menü'),
          NavigationDestination(icon: Icon(Icons.person_outline), selectedIcon: Icon(Icons.person), label: 'Profil'),
        ],
      ),
    );
  }
}
