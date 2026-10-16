"""Sadakat kuralları: sunucuyla ortak senaryolar (firebase/functions/test/loyalty_vectors.json)."""
import json
import os
import re

import pytest

import loyalty_logic as L

VECTORS = os.path.join(os.path.dirname(__file__), '..', 'firebase', 'functions', 'test', 'loyalty_vectors.json')
CASES = json.load(open(VECTORS, encoding='utf-8'))


def _py_name(name):
    return re.sub(r'([A-Z])', lambda m: '_' + m.group(1).lower(), name)


@pytest.mark.parametrize('case', CASES, ids=[c['name'] for c in CASES])
def test_ortak_senaryo(case):
    fn = getattr(L, _py_name(case['fn']))
    if case.get('error'):
        with pytest.raises(L.LoyaltyError, match=case['error']):
            fn(*case['args'])
        return
    assert fn(*case['args']) == case['expect']


def test_telefon_bicimi():
    assert L.format_phone('5321234567') == '0532 123 45 67'
    assert L.tier_name('silver', L.DEFAULT_LOYALTY) == 'Gümüş'
