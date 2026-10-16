"""Kampanya hesabı: sunucuyla ortak senaryolar (firebase/functions/test/campaign_vectors.json)."""
import json
import os

import pytest

import campaigns_logic as C

V = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'firebase', 'functions', 'test',
                                'campaign_vectors.json'), encoding='utf-8'))


@pytest.mark.parametrize('case', V['validate'], ids=[c['name'] for c in V['validate']])
def test_dogrulama(case):
    if case.get('error'):
        with pytest.raises(C.CampaignError, match=case['error']):
            C.validate_campaign(case['input'])
    else:
        assert C.validate_campaign(case['input']) == case['expect']


@pytest.mark.parametrize('case', V['live'], ids=[c['name'] for c in V['live']])
def test_gecerlilik(case):
    assert C.is_live(case['campaign'], case['at'], case['customer']) is case['expect']


@pytest.mark.parametrize('case', V['compute'], ids=[c['name'] for c in V['compute']])
def test_hesap(case):
    assert C.compute_campaigns(case['order'], case['campaigns'], case['at'], case['categoryOf']) == case['expect']


def test_aciklamalar():
    assert C.describe({'type': 'nth', 'nthQty': 3, 'value': 100}) == '3 al 2 öde'
    assert C.describe({'type': 'nth', 'nthQty': 2, 'value': 50}) == '2. ürün %50'
    assert C.schedule_text({'schedule': {'days': [1, 2, 3, 4, 5], 'from': '14:00', 'to': '17:00'}}) == 'Hafta içi 14:00–17:00'
