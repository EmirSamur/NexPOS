"""Sipariş mantığı: sunucuyla ortak senaryolar (firebase/functions/test/order_vectors.json)."""
import json
import os

import pytest

from cloud.orders import OrderError, apply_order_op, merge_orders, stamp_count, table_status_for

VECTORS = os.path.join(os.path.dirname(__file__), '..', 'firebase', 'functions', 'test', 'order_vectors.json')
CASES = json.load(open(VECTORS, encoding='utf-8'))


def run(steps):
    orders = {}
    for s in steps:
        if s['op'] == 'mergeOrders':
            t, src = merge_orders(orders[s['payload']['orderId']], orders[s['payload']['sourceOrderId']], s['at'])
            orders[t['id']], orders[src['id']] = t, src
        else:
            oid = s['payload']['orderId']
            orders[oid] = apply_order_op(orders.get(oid), s['op'], s['payload'], s['staffId'], s['at'])
    return orders


@pytest.mark.parametrize('case', CASES, ids=[c['name'] for c in CASES])
def test_ortak_senaryo(case):
    if case.get('expectError'):
        with pytest.raises(OrderError, match=case['expectError']):
            run(case['steps'])
        return
    orders = run(case['steps'])
    for oid, fields in case.get('expect', {}).items():
        for k, v in fields.items():
            assert orders[oid][k] == v, f"{oid}.{k}"
    for oid, lines in case.get('expectLines', {}).items():
        assert len(orders[oid]['items']) == len(lines)
        for line, exp in zip(orders[oid]['items'], lines):
            for k, v in exp.items():
                assert line[k] == v, f"{oid}.{line['lineId']}.{k}"
    for oid, pays in case.get('expectPayments', {}).items():
        for pay, exp in zip(orders[oid]['payments'], pays):
            for k, v in exp.items():
                assert pay[k] == v
    for oid, st in case.get('expectTableStatus', {}).items():
        assert table_status_for(orders[oid]) == st
    for oid, n in case.get('expectStamps', {}).items():
        assert stamp_count(orders[oid]) == n


def test_bool_tutar_olarak_kabul_edilmez():
    o = apply_order_op(None, 'openOrder', {'orderId': 'o', 'no': 'A1', 'businessDay': 'd', 'type': 'takeaway'}, 's', 'x')
    with pytest.raises(OrderError):
        apply_order_op(o, 'addItems', {'orderId': 'o', 'items': [
            {'lineId': 'a', 'name': 'X', 'unitPrice': True, 'qty': 1, 'station': 'bar'}]}, 's', 'x')
