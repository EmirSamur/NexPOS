"""Vardiya/mesai hesapları: sunucuyla ortak senaryolar (firebase/functions/test/shift_vectors.json)."""
import json
import os

import pytest

import shifts_logic as s

DATA = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'firebase', 'functions', 'test',
                                   'shift_vectors.json'), encoding='utf-8'))


@pytest.mark.parametrize('case', DATA['cases'], ids=[c['name'] for c in DATA['cases']])
def test_ortak_senaryo(case):
    e, plan, entry = case['expect'], case['plan'], case['entry']
    if 'planned' in e:
        assert s.planned_minutes(plan) == e['planned']
    if 'late' in e:
        assert s.late_minutes(plan, (entry or {}).get('clockIn'), case['tolerance']) == e['late']
    if 'break' in e:
        assert s.break_minutes(entry, plan) == e['break']
    if 'worked' in e:
        assert s.worked_minutes(entry, plan) == e['worked']
    if 'businessDay' in e:
        assert s.business_day_of(entry['clockIn']) == e['businessDay']


def test_fazla_mesai_ve_bicim():
    for worked, expected in DATA['overtime']:
        assert s.overtime_minutes(worked) == expected
    assert (s.format_minutes(475), s.format_minutes(480), s.format_minutes(15)) == ('7 sa 55 dk', '8 sa', '15 dk')
