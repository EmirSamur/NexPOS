import 'package:flutter/material.dart';

import '../state.dart';
import 'home.dart';
import 'login.dart';
import 'menu.dart';
import 'profile.dart';

/// Giriş durumuna göre ekran: yükleniyor · giriş · profil formu · uygulama (misafir de menüyü görür)
class Root extends StatefulWidget {
  const Root({super.key});

  @override
  State<Root> createState() => _RootState();
}

class _RootState extends State<Root> {
  bool _guest = false;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
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
  int _tab = 0;

  @override
  Widget build(BuildContext context) {
    final pages = [
      HomeTab(onLogin: widget.onLogin, onMenu: () => setState(() => _tab = 1)),
      const MenuTab(),
      ProfileTab(onLogin: widget.onLogin),
    ];
    return Scaffold(
      body: IndexedStack(index: _tab, children: pages),
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
