"""Kahve önerisi: sunucu ve uygulamayla ortak senaryolar (firebase/functions/test/quiz_vectors.json)."""
import json
import os

import pytest

import quiz_logic as Q

VECTORS = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'firebase', 'functions', 'test',
                                      'quiz_vectors.json'), encoding='utf-8'))


@pytest.mark.parametrize('case', VECTORS['cases'], ids=[c['name'] for c in VECTORS['cases']])
def test_ortak_senaryo(case):
    pool = [p for p in VECTORS['products'] if p['id'] not in case['without']]
    assert Q.profile_from(VECTORS['quiz'], case['answers']) == case['profile']
    assert Q.recommend(pool, VECTORS['quiz'], case['answers'], case['ctx']) == case['expect']


def test_yardimcilar():
    assert len(Q.flavor_templates()) >= 15 and Q.default_quiz()['questions'][0]['id'] == 'mood'
    assert Q.answer_effect({'weights': {'strength': 2}, 'notes': ['çikolata'], 'filter': {'milk': True}}) == \
        'Sertlik +2 · çikolata · sütlü'
    assert Q.answer_effect({}) == 'etkisiz'
    assert Q.slug('Buz gibi 🧊', set()) == 'buz-gibi'
    assert Q.slug('Çikolata', {'cikolata'}) == 'cikolata2'
