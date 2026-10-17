// "Bana öner" (11c): birkaç soru → en uyumlu içecek + 2 alternatif; sipariş açıksa sepete eklenir.
import 'package:flutter/material.dart';

import '../logic.dart';
import '../models.dart';
import '../quiz.dart';
import '../state.dart';
import 'common.dart';
import 'menu.dart';

class QuizScreen extends StatefulWidget {
  const QuizScreen({super.key});

  @override
  State<QuizScreen> createState() => _QuizScreenState();
}

class _QuizScreenState extends State<QuizScreen> {
  final _answers = <String, String>{};
  int _step = 0;
  List<Recommendation>? _result;
  bool _busy = false;

  Future<void> _answer(QuizQuestion q, QuizAnswer a) async {
    final s = AppScope.read(context);
    _answers[q.id] = a.id;
    if (_step + 1 < s.quiz.questions.length) {
      setState(() => _step++);
      return;
    }
    setState(() => _busy = true);
    final recs = await s.runQuiz(Map.of(_answers));
    if (mounted) {
      setState(() {
        _result = recs;
        _busy = false;
      });
    }
  }

  void _restart() => setState(() {
        _answers.clear();
        _step = 0;
        _result = null;
      });

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final qs = s.quiz.questions;
    final t = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Bana öner ✨'),
        leading: _result == null && _step > 0
            ? IconButton(
                tooltip: 'Önceki soru',
                icon: const Icon(Icons.arrow_back),
                onPressed: () => setState(() => _step--),
              )
            : null,
      ),
      body: _busy
          ? const Center(child: CircularProgressIndicator())
          : _result != null
              ? _results(context, s, _result!)
              : ListView(padding: const EdgeInsets.all(24), children: [
                  LinearProgressIndicator(value: (_step + 1) / qs.length, borderRadius: BorderRadius.circular(4)),
                  const SizedBox(height: 8),
                  Text('${_step + 1}/${qs.length}', style: const TextStyle(color: Colors.black54)),
                  const SizedBox(height: 20),
                  Text(qs[_step].text, key: const Key('quizQuestion'),
                      style: t.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
                  const SizedBox(height: 24),
                  for (final a in qs[_step].answers)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: OutlinedButton(
                        style: OutlinedButton.styleFrom(
                          minimumSize: const Size.fromHeight(56),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                          textStyle: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
                        ),
                        onPressed: () => _answer(qs[_step], a),
                        child: Text(a.text),
                      ),
                    ),
                ]),
    );
  }

  Widget _results(BuildContext context, AppState s, List<Recommendation> recs) {
    final t = Theme.of(context).textTheme;
    if (recs.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Text('Şu an önerebileceğimiz bir içecek yok.', textAlign: TextAlign.center),
            const SizedBox(height: 12),
            TextButton(onPressed: _restart, child: const Text('Baştan başla')),
          ]),
        ),
      );
    }
    Product? product(String id) => s.menu.product(id);
    final top = product(recs.first.productId);
    return ListView(padding: const EdgeInsets.all(20), children: [
      Text('Sana önerimiz', style: t.titleMedium?.copyWith(color: Colors.black54)),
      const SizedBox(height: 8),
      if (top != null)
        Card(
          color: s.brand.accent.withValues(alpha: 0.18),
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                ProductImage(top, size: 72),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(top.name, key: const Key('quizTop'), style: t.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
                    Text('%${recs.first.score} uyum · ${formatTl(top.price)}',
                        style: TextStyle(color: s.brand.primary, fontWeight: FontWeight.bold)),
                  ]),
                ),
              ]),
              if (top.description.isNotEmpty) ...[const SizedBox(height: 10), Text(top.description)],
              if (recs.first.reasons.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(recs.first.reasons.map((r) => reasonLabels[r] ?? r).join(' · '),
                      style: const TextStyle(color: Colors.black54)),
                ),
              const SizedBox(height: 14),
              FilledButton(
                key: const Key('quizPick'),
                onPressed: () => _open(context, top),
                child: Text(s.canOrder ? 'Sepete ekle' : 'Ürüne bak'),
              ),
            ]),
          ),
        ),
      if (recs.length > 1) const SectionTitle('Ya da bunlar'),
      for (final r in recs.skip(1))
        if (product(r.productId) case final p?)
          Card(
            margin: const EdgeInsets.only(bottom: 10),
            child: ListTile(
              leading: ProductImage(p, size: 48),
              title: Text(p.name, style: const TextStyle(fontWeight: FontWeight.bold)),
              subtitle: Text('%${r.score} uyum · ${formatTl(p.price)}'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _open(context, p),
            ),
          ),
      const SizedBox(height: 8),
      TextButton(onPressed: _restart, child: const Text('Tekrar dene')),
    ]);
  }

  void _open(BuildContext context, Product p) =>
      Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => ProductScreen(product: p)));
}
