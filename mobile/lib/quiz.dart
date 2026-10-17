// Kahve önerisi ("Bana öner", 11c): sorular ve kural tabanlı eşleştirme — internetsiz, telefonda hesaplanır.
// Sunucudaki src/quiz.js ve paneldeki quiz_logic.py ile aynıdır; üçü de quiz_vectors.json ile test edilir.
import 'models.dart';

const quizDims = ['strength', 'sweetness', 'acidity', 'body'];

class QuizAnswer {
  final String id;
  final String text;
  final Map<String, int> weights;
  final List<String> notes;
  final bool? milk;
  final String? temperature;
  const QuizAnswer(this.id, this.text, {this.weights = const {}, this.notes = const [], this.milk, this.temperature});

  static QuizAnswer fromMap(Map d) {
    final w = d['weights'] is Map ? d['weights'] as Map : const {};
    final f = d['filter'] is Map ? d['filter'] as Map : const {};
    return QuizAnswer(
      '${d['id']}',
      '${d['text']}',
      weights: {for (final e in w.entries) if (e.value is num) '${e.key}': (e.value as num).toInt()},
      notes: d['notes'] is List ? (d['notes'] as List).whereType<String>().toList() : const [],
      milk: f['milk'] is bool ? f['milk'] as bool : null,
      temperature: f['temperature'] is String ? f['temperature'] as String : null,
    );
  }
}

class QuizQuestion {
  final String id;
  final String text;
  final List<QuizAnswer> answers;
  const QuizQuestion(this.id, this.text, this.answers);
}

class Quiz {
  final List<QuizQuestion> questions;
  const Quiz(this.questions);

  /// settings/quiz; yoksa ya da bozuksa hazır sorular
  static Quiz fromDoc(Map<String, dynamic>? d) {
    final qs = d?['questions'];
    if (qs is! List || qs.isEmpty) return defaultQuiz;
    try {
      return Quiz([
        for (final q in qs.whereType<Map>())
          QuizQuestion('${q['id']}', '${q['text']}',
              [for (final a in (q['answers'] as List).whereType<Map>()) QuizAnswer.fromMap(a)]),
      ]);
    } catch (_) {
      return defaultQuiz;
    }
  }
}

const defaultQuiz = Quiz([
  QuizQuestion('mood', 'Bugün nasıl hissediyorsun?', [
    QuizAnswer('sleepy', 'Uykuluyum 😴', weights: {'strength': 2, 'body': 1}),
    QuizAnswer('happy', 'Keyifliyim 🙂', weights: {'sweetness': 1}),
    QuizAnswer('calm', 'Sakin bir şey', weights: {'strength': -2}),
  ]),
  QuizQuestion('milk', 'Sütlü mü?', [
    QuizAnswer('yes', 'Evet', milk: true),
    QuizAnswer('no', 'Hayır', milk: false),
    QuizAnswer('any', 'Fark etmez'),
  ]),
  QuizQuestion('temp', 'Sıcak mı soğuk mu?', [
    QuizAnswer('hot', 'Sıcak ☕', temperature: 'hot'),
    QuizAnswer('iced', 'Buz gibi 🧊', temperature: 'iced'),
  ]),
  QuizQuestion('taste', 'Hangisi sana yakın?', [
    QuizAnswer('choc', 'Çikolata 🍫', weights: {'sweetness': 1, 'body': 1}, notes: ['çikolata']),
    QuizAnswer('fruit', 'Meyvemsi 🍓', weights: {'acidity': 2}, notes: ['meyvemsi']),
    QuizAnswer('nut', 'Fındık 🌰', weights: {'body': 1}, notes: ['fındık', 'karamel']),
    QuizAnswer('plain', 'Sade', weights: {'sweetness': -1}),
  ]),
]);

String trLower(String s) => s.replaceAll('I', 'ı').replaceAll('İ', 'i').toLowerCase();

class TasteProfile {
  final Map<String, int> target;
  final List<String> notes;
  final bool? milk;
  final String? temperature;
  const TasteProfile(this.target, this.notes, this.milk, this.temperature);
}

TasteProfile profileFrom(Quiz quiz, Map<String, String> answers) {
  final target = {for (final k in quizDims) k: 3};
  final notes = <String>[];
  bool? milk;
  String? temperature;
  for (final q in quiz.questions) {
    final a = q.answers.where((x) => x.id == answers[q.id]).firstOrNull;
    if (a == null) continue;
    a.weights.forEach((k, v) => target[k] = (target[k]! + v).clamp(1, 5));
    for (final n in a.notes) {
      if (!notes.contains(n)) notes.add(n);
    }
    if (a.milk != null) milk = a.milk;
    if (a.temperature != null) temperature = a.temperature;
  }
  return TasteProfile(target, notes, milk, temperature);
}

class Recommendation {
  final String productId;
  final int score; // 0–100 uyum
  final List<String> reasons; // notes | decaf | iced | new
  const Recommendation(this.productId, this.score, this.reasons);
}

List<Recommendation> recommend(List<Product> products, Quiz quiz, Map<String, String> answers,
    {int hour = 12, bool hotDay = false, Set<String>? triedIds}) {
  final p = profileFrom(quiz, answers);
  final usable = products.where((x) => x.flavor != null && !x.soldOut).toList();
  bool milkOk(Product x) => p.milk == null || x.flavor!.milk == p.milk;
  bool tempOk(Product x) => p.temperature == null || x.flavor!.temperature == p.temperature;
  var pool = usable.where((x) => milkOk(x) && tempOk(x)).toList();
  // Süzgece uyan yoksa önce sıcaklık, sonra süt gevşetilir
  if (pool.isEmpty && p.temperature != null) pool = usable.where(milkOk).toList();
  if (pool.isEmpty) pool = usable;
  final scored = <Recommendation>[];
  for (final x in pool) {
    final f = x.flavor!;
    final distance = quizDims.fold<int>(0, (s, k) => s + (p.target[k]! - f.dims[k]!).abs());
    var score = 1 - distance / 16;
    final reasons = <String>[];
    final pnotes = f.notes.map(trLower).toList();
    if (p.notes.any(pnotes.contains)) {
      score += 0.15;
      reasons.add('notes');
    }
    if (hour >= 17 && x.caffeineMg == 0) {
      score += 0.1;
      reasons.add('decaf');
    }
    if (hotDay && f.temperature == 'iced') {
      score += 0.1;
      reasons.add('iced');
    }
    if (triedIds != null && !triedIds.contains(x.id)) {
      score += 0.05;
      reasons.add('new');
    }
    scored.add(Recommendation(x.id, (score.clamp(0, 1) * 100).round(), reasons));
  }
  scored.sort((a, b) => a.score != b.score ? b.score.compareTo(a.score) : a.productId.compareTo(b.productId));
  return scored.take(3).toList();
}

const reasonLabels = {
  'notes': 'sevdiğin tatlar',
  'decaf': 'akşam için kafeinsiz',
  'iced': 'sıcak güne serinlik',
  'new': 'henüz denemedin',
};
