"""
NexPOS - Pazarlama → Kahve Önerisi (11c)

Müşteri uygulamasındaki "Bana öner" soruları: soru ve cevap ekleme/düzenleme, cevabın etkisi (tat ağırlıkları,
nota, sütlü/sıcak süzgeci), "Dene" önizlemesi (menüdeki tat profilleriyle, uygulamadaki hesabın aynısı) ve
hazır sorulara dönme. Kaydetme internet ister (settings/quiz, editMenu yetkisi).
"""
import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import database
import quiz_logic as Q
from admin_access_pages import _button, cloud_action
from loyalty_pages import _muted

FILTER_MILK = [("Fark etmez", None), ("Sütlü", True), ("Sütsüz", False)]
FILTER_TEMP = [("Fark etmez", None), ("Sıcak", 'hot'), ("Soğuk", 'iced')]


class QuestionDialog(QDialog):
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.setWindowTitle("Soru")
        self.setStyleSheet("QDialog { background: white; }")
        form = QFormLayout(self)
        self.text = QLineEdit(text)
        self.text.setMaxLength(80)
        self.text.setPlaceholderText("Bugün nasıl hissediyorsun?")
        form.addRow("Soru:", self.text)
        ok = _button("Tamam")
        ok.clicked.connect(lambda: self.text.text().strip() and self.accept())
        form.addRow(ok)


class AnswerDialog(QDialog):
    def __init__(self, answer=None, parent=None):
        super().__init__(parent)
        a = answer or {}
        self.setWindowTitle("Cevap")
        self.setStyleSheet("QDialog { background: white; }")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.text = QLineEdit(a.get('text', ''))
        self.text.setMaxLength(40)
        self.text.setPlaceholderText("Uykuluyum 😴")
        form.addRow("Cevap:", self.text)
        form.addRow(_muted("Cevap seçilince hedef tat profili (başlangıç 3/5) bu kadar değişir:"))
        self.weights = {}
        for k in Q.DIMS:
            sp = QSpinBox()
            sp.setRange(-3, 3)
            sp.setPrefix("")
            sp.setValue((a.get('weights') or {}).get(k, 0))
            self.weights[k] = sp
            form.addRow(f"{Q.DIM_LABELS[k]}:", sp)
        self.notes = QLineEdit(", ".join(a.get('notes') or []))
        self.notes.setPlaceholderText("çikolata, fındık (ürünün notalarıyla eşleşirse artı puan)")
        form.addRow("Notalar:", self.notes)
        f = a.get('filter') or {}
        self.milk = QComboBox()
        self.temp = QComboBox()
        for box, options, key in ((self.milk, FILTER_MILK, 'milk'), (self.temp, FILTER_TEMP, 'temperature')):
            for label, value in options:
                box.addItem(label, value)
            box.setCurrentIndex(max(0, box.findData(f.get(key))) if key in f else 0)
        form.addRow("Süt süzgeci:", self.milk)
        form.addRow("Sıcaklık süzgeci:", self.temp)
        self.error = QLabel()
        self.error.setStyleSheet("color: #DC2626;")
        form.addRow(self.error)
        ok = _button("Tamam")
        ok.clicked.connect(self._ok)
        form.addRow(ok)

    def _ok(self):
        if not self.text.text().strip():
            self.error.setText("Cevap metni yazın.")
            return
        notes = [n.strip() for n in self.notes.text().split(',') if n.strip()]
        if len(notes) > 4:
            self.error.setText("En fazla 4 nota.")
            return
        self.accept()

    def value(self, answer_id):
        out = {'id': answer_id, 'text': self.text.text().strip()}
        w = {k: sp.value() for k, sp in self.weights.items() if sp.value()}
        if w:
            out['weights'] = w
        notes = [Q._tr_lower(n.strip()) for n in self.notes.text().split(',') if n.strip()]
        if notes:
            out['notes'] = list(dict.fromkeys(notes))
        f = {}
        if self.milk.currentData() is not None:
            f['milk'] = self.milk.currentData()
        if self.temp.currentData() is not None:
            f['temperature'] = self.temp.currentData()
        if f:
            out['filter'] = f
        return out


class QuizPanel(QWidget):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.quiz = None
        ly = QHBoxLayout(self)
        ly.setContentsMargins(28, 12, 28, 20)
        ly.setSpacing(20)

        left = QVBoxLayout()
        left.addWidget(QLabel("<b style='font-size:18px'>Kahve önerisi</b><br><span style='color:#64748b'>"
                              "Uygulamadaki \"Bana öner\" soruları. Cevaplar bir tat profili kurar; menüde tat profili "
                              "girilmiş, tükenmemiş ürünler bu profile yakınlığına göre önerilir (Menü → ürün → "
                              "Tat Profili).</span>"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Soru / cevap", "Etkisi"])
        self.tree.setColumnWidth(0, 300)
        self.tree.itemDoubleClicked.connect(lambda *_: self._edit())
        left.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.buttons = []
        for text, fn in (("+ Soru", self._add_question), ("+ Cevap", self._add_answer), ("Düzenle", self._edit),
                         ("Sil", self._delete), ("↑", lambda: self._move(-1)), ("↓", lambda: self._move(1))):
            b = _button(text, primary=False)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.buttons.append(b)
        row.addStretch()
        left.addLayout(row)
        row2 = QHBoxLayout()
        self.reset_btn = _button("Hazır sorulara dön", primary=False)
        self.reset_btn.clicked.connect(self._reset)
        row2.addWidget(self.reset_btn)
        row2.addStretch()
        self.save_btn = _button("Kaydet")
        self.save_btn.clicked.connect(self._save)
        row2.addWidget(self.save_btn)
        left.addLayout(row2)
        self.note = _muted("")
        left.addWidget(self.note)
        ly.addLayout(left, 3)

        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Dene</b> — müşteri bu cevapları verirse:"))
        self.try_form = QFormLayout()
        right.addLayout(self.try_form)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.RichText)
        self.result.setStyleSheet("font-size: 14px; background: transparent;")
        right.addWidget(self.result)
        right.addStretch()
        ly.addLayout(right, 2)
        self.refresh()

    # ------------------------------------------------------------------ görünüm
    def refresh(self):
        stored = database.get_setting('quiz') or {}
        self.quiz = copy.deepcopy({'questions': stored['questions']} if stored.get('questions') else Q.default_quiz())
        self.dirty = False
        can = database.user_can(self.user, 'editMenu')
        for b in self.buttons + [self.save_btn, self.reset_btn]:
            b.setEnabled(can)
        self.note.setText("" if can else "Soruları değiştirmek için menü düzenleme yetkisi gerekir.")
        self._render()

    def _render(self, select=None):
        self.tree.clear()
        for qi, q in enumerate(self.quiz['questions']):
            qitem = QTreeWidgetItem([f"{qi + 1}. {q['text']}", ""])
            qitem.setData(0, Qt.UserRole, (qi, None))
            f = qitem.font(0)
            f.setBold(True)
            qitem.setFont(0, f)
            for ai, a in enumerate(q['answers']):
                it = QTreeWidgetItem([a['text'], Q.answer_effect(a)])
                it.setData(0, Qt.UserRole, (qi, ai))
                qitem.addChild(it)
                if select == (qi, ai):
                    self.tree.setCurrentItem(it)
            self.tree.addTopLevelItem(qitem)
            qitem.setExpanded(True)
            if select == (qi, None):
                self.tree.setCurrentItem(qitem)
        self._build_try()

    def _build_try(self):
        while self.try_form.rowCount():
            self.try_form.removeRow(0)
        self.try_boxes = {}
        for q in self.quiz['questions']:
            box = QComboBox()
            box.addItem("—", None)
            for a in q['answers']:
                box.addItem(a['text'], a['id'])
            box.currentIndexChanged.connect(self._try)
            self.try_boxes[q['id']] = box
            self.try_form.addRow(q['text'], box)
        self._try()

    def _try(self, *_):
        answers = {qid: b.currentData() for qid, b in self.try_boxes.items() if b.currentData()}
        products = [p for p in database.menu_products() if p.get('flavor')]
        if not products:
            self.result.setText("Menüde tat profili girilmiş ürün yok. Menü → ürün → <b>Tat Profili</b> sekmesinden "
                                "(hazır şablonla) girin.")
            return
        names = {p['id']: p['name'] for p in products}
        recs = Q.recommend(products, self.quiz, answers, {'hour': 12})
        self.result.setText("<br>".join(f"{'☕' if i == 0 else '·'} <b>{names[r['productId']]}</b> — %{r['score']} uyum"
                                        for i, r in enumerate(recs)))

    # ----------------------------------------------------------------- düzenleme
    def _selected(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else (None, None)

    def _changed(self, select=None):
        self.dirty = True
        self.note.setText("Kaydedilmemiş değişiklik var.")
        self._render(select)

    def _add_question(self):
        if len(self.quiz['questions']) >= 6:
            self.note.setText("En fazla 6 soru olabilir.")
            return
        dlg = QuestionDialog(parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        text = dlg.text.text().strip()
        qid = Q.slug(text, {q['id'] for q in self.quiz['questions']})
        self.quiz['questions'].append({'id': qid, 'text': text, 'answers': [
            {'id': 'evet', 'text': 'Evet'}, {'id': 'hayir', 'text': 'Hayır'}]})
        self._changed((len(self.quiz['questions']) - 1, None))

    def _add_answer(self):
        qi, _ = self._selected()
        if qi is None:
            self.note.setText("Önce bir soru seçin.")
            return
        q = self.quiz['questions'][qi]
        if len(q['answers']) >= 5:
            self.note.setText("Bir soruda en fazla 5 cevap olabilir.")
            return
        dlg = AnswerDialog(parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        q['answers'].append(dlg.value(Q.slug(dlg.text.text(), {a['id'] for a in q['answers']})))
        self._changed((qi, len(q['answers']) - 1))

    def _edit(self):
        qi, ai = self._selected()
        if qi is None:
            return
        q = self.quiz['questions'][qi]
        if ai is None:
            dlg = QuestionDialog(q['text'], self)
            if dlg.exec() == QDialog.Accepted:
                q['text'] = dlg.text.text().strip()
                self._changed((qi, None))
            return
        dlg = AnswerDialog(q['answers'][ai], self)
        if dlg.exec() == QDialog.Accepted:
            q['answers'][ai] = dlg.value(q['answers'][ai]['id'])
            self._changed((qi, ai))

    def _delete(self):
        qi, ai = self._selected()
        if qi is None:
            return
        if ai is None:
            if len(self.quiz['questions']) <= 1:
                self.note.setText("En az bir soru kalmalı.")
                return
            del self.quiz['questions'][qi]
            self._changed()
        else:
            if len(self.quiz['questions'][qi]['answers']) <= 2:
                self.note.setText("Bir soruda en az 2 cevap olmalı.")
                return
            del self.quiz['questions'][qi]['answers'][ai]
            self._changed((qi, None))

    def _move(self, step):
        qi, ai = self._selected()
        if qi is None:
            return
        lst = self.quiz['questions'] if ai is None else self.quiz['questions'][qi]['answers']
        i = qi if ai is None else ai
        j = i + step
        if not 0 <= j < len(lst):
            return
        lst[i], lst[j] = lst[j], lst[i]
        self._changed((j, None) if ai is None else (qi, j))

    def _reset(self):
        self.quiz = copy.deepcopy(Q.default_quiz())
        self._changed()

    def _save(self):
        quiz = copy.deepcopy(self.quiz)

        def saved(result):
            database.set_setting('quiz', result)
            self.refresh()
            self.note.setText("Kaydedildi; uygulamaya birkaç saniyede yansır.")
        cloud_action(self, lambda api: api.save_quiz(quiz), "Öneri soruları kaydedildi.", saved)
