import 'package:flutter/material.dart';

import '../logic.dart';
import '../state.dart';
import 'common.dart';

/// Telefon + SMS kodu. "Giriş yapmadan menüye bak" misafir modunu açar.
class LoginScreen extends StatefulWidget {
  final VoidCallback onGuest;
  const LoginScreen({super.key, required this.onGuest});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _phone = TextEditingController();
  final _code = TextEditingController();
  bool _codeSent = false;
  bool _busy = false;
  String? _error;

  Future<void> _send() async {
    final e164 = toE164(_phone.text);
    if (e164 == null) {
      setState(() => _error = 'Telefon numarası geçersiz.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AppScope.read(context).repo.sendCode(e164);
      if (mounted) setState(() => _codeSent = true);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirm() async {
    if (_code.text.trim().length < 6) {
      setState(() => _error = 'SMS ile gelen 6 haneli kodu girin.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AppScope.read(context).repo.confirmCode(_code.text.trim());
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final t = Theme.of(context).textTheme;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(28),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Center(child: BrandLogo(size: 84)),
                  const SizedBox(height: 16),
                  Text(s.info.cafeName.isNotEmpty ? s.info.cafeName : s.brand.appName,
                      textAlign: TextAlign.center, style: t.headlineMedium?.copyWith(fontWeight: FontWeight.bold, color: s.brand.primary)),
                  if (s.brand.slogan.isNotEmpty)
                    Text(s.brand.slogan, textAlign: TextAlign.center, style: t.bodyLarge?.copyWith(color: Colors.black54)),
                  const SizedBox(height: 36),
                  if (!_codeSent) ...[
                    Text('Telefon numaran', style: t.titleMedium),
                    const SizedBox(height: 8),
                    TextField(
                      key: const Key('phone'),
                      controller: _phone,
                      keyboardType: TextInputType.phone,
                      autofillHints: const [AutofillHints.telephoneNumber],
                      decoration: const InputDecoration(hintText: '0532 123 45 67', border: OutlineInputBorder(), prefixIcon: Icon(Icons.phone)),
                      onSubmitted: (_) => _send(),
                    ),
                    const SizedBox(height: 6),
                    Text('Kasada üye olduysan aynı numarayla gir; kartın aynen gelir.',
                        style: t.bodySmall?.copyWith(color: Colors.black54)),
                    const SizedBox(height: 16),
                    FilledButton(key: const Key('sendCode'), onPressed: _busy ? null : _send, child: const Text('Kod gönder')),
                  ] else ...[
                    Text('${_phone.text} numarasına gelen kod', style: t.titleMedium),
                    const SizedBox(height: 8),
                    TextField(
                      key: const Key('code'),
                      controller: _code,
                      keyboardType: TextInputType.number,
                      maxLength: 6,
                      autofillHints: const [AutofillHints.oneTimeCode],
                      decoration: const InputDecoration(hintText: '123456', border: OutlineInputBorder(), counterText: ''),
                      onSubmitted: (_) => _confirm(),
                    ),
                    const SizedBox(height: 16),
                    FilledButton(key: const Key('confirmCode'), onPressed: _busy ? null : _confirm, child: const Text('Giriş yap')),
                    TextButton(
                        onPressed: _busy ? null : () => setState(() => _codeSent = false), child: const Text('Numarayı değiştir')),
                  ],
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                    ),
                  const SizedBox(height: 28),
                  TextButton(key: const Key('guest'), onPressed: widget.onGuest, child: const Text('Giriş yapmadan menüye bak →')),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// İlk girişte: ad, doğum günü (isteğe bağlı), bildirim izni ve aydınlatma metni onayı
class ProfileSetupScreen extends StatefulWidget {
  const ProfileSetupScreen({super.key});

  @override
  State<ProfileSetupScreen> createState() => _ProfileSetupScreenState();
}

class _ProfileSetupScreenState extends State<ProfileSetupScreen> {
  final _name = TextEditingController();
  String? _birth;
  bool _consent = false;
  bool _kvkk = false;
  bool _busy = false;
  String? _error;

  Future<void> _save() async {
    if (_name.text.trim().isEmpty) {
      setState(() => _error = 'Adını yaz.');
      return;
    }
    if (!_kvkk) {
      setState(() => _error = 'Devam etmek için aydınlatma metnini onayla.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AppScope.read(context).completeProfile(name: _name.text.trim(), birthDate: _birth, marketingConsent: _consent);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final s = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Hoş geldin!'),
        actions: [TextButton(onPressed: s.signOut, child: const Text('Vazgeç'))],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            Text('Kartını oluşturalım. Her kahvede damga kazan, kart dolunca bir içecek bizden.', style: t.bodyLarge),
            const SizedBox(height: 24),
            TextField(
              key: const Key('name'),
              controller: _name,
              maxLength: 60,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(labelText: 'Adın', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 8),
            Text('Doğum günün (isteğe bağlı, yıl sorulmaz)', style: t.titleSmall),
            const SizedBox(height: 8),
            BirthdayPicker(value: _birth, onChanged: (v) => setState(() => _birth = v)),
            const SizedBox(height: 4),
            Text('Doğum günü haftanda bir içecek hediye.', style: t.bodySmall?.copyWith(color: Colors.black54)),
            const SizedBox(height: 16),
            SwitchListTile(
              key: const Key('consent'),
              contentPadding: EdgeInsets.zero,
              value: _consent,
              onChanged: (v) => setState(() => _consent = v),
              title: const Text('Kampanya ve fırsat bildirimleri almak istiyorum'),
              subtitle: const Text('İstediğin zaman profilden kapatabilirsin.'),
            ),
            CheckboxListTile(
              key: const Key('kvkk'),
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: _kvkk,
              onChanged: (v) => setState(() => _kvkk = v ?? false),
              title: Wrap(children: [
                InkWell(
                  onTap: () => showKvkk(context),
                  child: Text('Aydınlatma metnini', style: TextStyle(color: s.brand.primary, decoration: TextDecoration.underline)),
                ),
                const Text(' okudum, kabul ediyorum.'),
              ]),
            ),
            if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            const SizedBox(height: 16),
            FilledButton(key: const Key('saveProfile'), onPressed: _busy ? null : _save, child: const Text('Kartımı oluştur')),
          ],
        ),
      ),
    );
  }
}
