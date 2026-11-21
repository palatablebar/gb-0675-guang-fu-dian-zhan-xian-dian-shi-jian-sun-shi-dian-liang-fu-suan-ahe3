from app.modules.storage.rules import classify_charge, trace_discharge, build_charge_ledger
from app.coerce import instant, number
from decimal import Decimal

D = lambda v: Decimal(v)

def test_curtail_charge_classified(clean):
    row = next(r for r in clean['storage']['charges'] if r['id'] == 'SC-E-00')
    assert row['origin'] == '限电充电'
    assert row['curtail_charge_kwh'] == '2.0000'
    assert row['other_charge_kwh'] == '0.0000'

def test_non_curtail_charge_not_recovery_source(clean):
    row = next(r for r in clean['storage']['charges'] if r['id'] == 'SC-D-40')
    assert row['origin'] == '非限电充电'
    assert row['curtail_charge_kwh'] == '0.0000'
    # 非限电充电后上网：放电可追溯，但不形成任何回补。
    dis = next(r for r in clean['storage']['discharges'] if r['id'] == 'SD-D-40')
    assert dis['from_curtail_kwh'] == '0.0000'
    assert dis['from_other_kwh'] == '1.2000'
    assert dis['recover_kwh'] == '0.0000'

def test_gross_minus_recovery_equals_net(clean):
    st = clean['storage']
    assert st['gross_loss_kwh'] == '26.6667'
    assert st['totals']['recover_total_kwh'] == '1.5000'
    assert st['net_loss_kwh'] == '25.1667'
    assert D(st['gross_loss_kwh']) - D(st['totals']['recover_total_kwh']) == D(st['net_loss_kwh'])

def test_self_use_drains_curtail_but_no_recovery(clean):
    dis = next(r for r in clean['storage']['discharges'] if r['id'] == 'SD-E-40')
    assert dis['purpose'] == '储能自用'
    assert dis['recover_kwh'] == '0.0000'
    assert dis['selfuse_kwh'] == '0.9000'
    assert dis['from_curtail_kwh'] == '0.9000'

def test_round_trip_loss_has_destination(clean):
    # 损耗 = 放电量 − 折算可追溯电量，逐笔列示，不计入回补。
    for dis in clean['storage']['discharges']:
        assert D(dis['discharge_kwh']) - D(dis['traceable_kwh']) == D(dis['loss_kwh_storage'])
    assert clean['storage']['totals']['storage_loss_kwh'] == '0.4000'

def test_origin_identity_balanced(clean):
    # 限电充入 = 回补 + 自用限电 + 限电桶结余。
    t = clean['storage']['totals']
    assert D(t['curtail_charge_kwh']) == D(t['recover_total_kwh']) + D(t['selfuse_total_kwh']) + D(t['remaining_curtail_kwh'])
    assert clean['storage']['storage_balanced'] is True

def test_clean_has_no_pending(clean):
    assert clean['storage']['pending'] == []
    assert clean['balance']['pending_storage'] == 0

def test_unknown_origin_discharge_pending(sample):
    st = sample['storage']
    pending = next(p for p in st['pending'] if p['id'] == 'SD-X-40')
    assert pending['code'] == 'ORIGIN_SHORTAGE'
    assert pending['shortage_kwh'] == '1.2167'
    assert sample['balance']['pending_storage'] == 1
    # 待查片段不产生回补，且阻断封存。
    assert sample['archive']['status'] == '待复核'

def test_pending_discharge_not_counted_as_recovery(sample):
    dis = next(r for r in sample['storage']['discharges'] if r['id'] == 'SD-X-40')
    assert dis['recover_kwh'] == '0.0000'
    assert D(dis['shortage_kwh']) > 0

def test_fifo_bucket_order(clean):
    # 先充先耗：10:30 上网放电先消耗最早（10:00）的限电桶。
    dis = next(r for r in clean['storage']['discharges'] if r['id'] == 'SD-E-30')
    assert dis['from_curtail_kwh'] == '1.5000'
    assert D(clean['storage']['totals']['curtail_charge_kwh']) == D('6.0000')

def test_mixed_charge_split():
    row = {'id': 'M1', 'device': 'BESS-E', 'at': '2026-10-15T02:00:00+00:00',
           'power_kw': '12', 'zone': '东区', 'purpose': '限电充电'}
    unions = {'INV-A': [{'zone': '东区', 'start': '2026-10-15T02:00:00+00:00',
                         'end': '2026-10-15T02:05:00+00:00'}]}
    out = classify_charge(row, unions, 600)
    # 5 分钟落在限电并集内、5 分钟落在外面：各 1 kWh。
    assert out['curtail_charge_kwh'] == '1.0000'
    assert out['other_charge_kwh'] == '1.0000'
    assert out['origin'] == '混合充电'

def test_discharge_shortage_marked():
    buckets = {'round_trip': '0.9', 'queue': [{'origin': '非限电充电', 'kwh': D('0.5'), 'from': 'C1'}]}
    row = {'id': 'X1', 'device': 'B', 'at': '2026-10-15T03:00:00+00:00',
           'power_kw': '10', 'purpose': '储能上网'}
    out = trace_discharge(row, buckets, 600)
    assert out['code'] == 'ORIGIN_SHORTAGE'
    assert D(out['shortage_kwh']) > 0
    assert out['recover_kwh'] == '0.0000'

def test_legacy_encoding_storage_kept():
    from app.engine import evaluate
    s = evaluate({'dataset': 'legacy'})
    assert s['encoding'] == 'gb18030'
    assert any(r['id'] == 'SC-E-00' for r in s['storage']['charges'])
    assert s['storage']['net_loss_kwh'] == '25.1667'

def test_storage_device_validation(sample):
    # 储能状态非法必须隔离，不能静默吞掉。
    bad = next(q for q in sample['quarantine'] if q['id'] == 'BAD-STORAGE')
    assert bad['code'] == 'BAD_STATUS'
    assert not any(r['id'] == 'BAD-STORAGE' for r in sample['records'])

def test_storage_on_non_storage_device_rejected(clean):
    from app.modules.devices.rules import normalize
    from app.errors import BusinessError
    import pytest
    row = {'id': 'Z1', 'kind': 'STORAGE', 'device': 'INV-A', 'at': '2026-10-15T02:00:00+00:00',
           'power': '10', 'unit': 'kW', 'irradiance': '', 'status': '限电充电',
           'start': '', 'end': '', '_line': 1}
    with pytest.raises(BusinessError) as e:
        normalize(row, clean['context'])
    assert e.value.code == 'NOT_STORAGE'
