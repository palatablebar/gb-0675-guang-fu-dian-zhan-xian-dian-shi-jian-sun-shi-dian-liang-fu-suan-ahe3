from datetime import timedelta
from decimal import Decimal
from app.coerce import number, instant

Q = Decimal('.0001')

def quantize(value):
    return value.quantize(Q)

def overlap_seconds(a_start, a_end, b_start, b_end):
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return max(0, int((end - start).total_seconds()))

def energy(power_kw, seconds):
    return number(power_kw) * Decimal(seconds) / Decimal(3600)

def classify_charge(row, unions_by_device, cadence):
    # 充电区间与限电并集求交集：有交集即为受限电量（限电充电），否则为非限电充电。
    # STORAGE 记录沿用遥测左值保持口径：自采样时刻起一个采样周期。
    start = instant(row['at'])
    end = start + timedelta(seconds=cadence)
    hit = Decimal(0)
    for device, unions in unions_by_device.items():
        for union in unions:
            if union['zone'] != row['zone']:
                continue
            secs = overlap_seconds(start, end, instant(union['start']), instant(union['end']))
            if secs:
                hit += energy(row['power_kw'], secs)
    total = energy(row['power_kw'], cadence)
    curtail = min(total, hit)
    other = total - curtail
    return {'kind': 'CHARGE', 'id': row['id'], 'device': row['device'], 'at': row['at'],
            'purpose': row['purpose'], 'charge_kwh': str(quantize(total)),
            'curtail_charge_kwh': str(quantize(curtail)),
            'other_charge_kwh': str(quantize(other)),
            'origin': '限电充电' if curtail > 0 and other == 0 else ('非限电充电' if curtail == 0 else '混合充电')}

def build_charge_ledger(records, event_unions, context, cadence):
    unions_by_device = {}
    for union in event_unions:
        unions_by_device.setdefault(union['device'], []).append(
            {**union, 'zone': context['devices'][union['device']]['zone']})
    charges = [classify_charge(r, unions_by_device, cadence) for r in records
               if r['kind'] == 'STORAGE' and r['direction'] == '充电']
    return sorted(charges, key=lambda r: (instant(r['at']), r['id']))

def trace_discharge(row, buckets, cadence):
    # 放电先按循环效率折算到充入侧，再按 FIFO 从各来历桶扣减；折算缺口即转换损耗，有去向。
    discharge = energy(row['power_kw'], cadence)
    efficiency = number(buckets['round_trip'])
    traceable = discharge * efficiency
    remaining = traceable
    drawn = {'限电充电': Decimal(0), '非限电充电': Decimal(0)}
    for bucket in buckets['queue']:
        if remaining <= 0:
            break
        take = min(remaining, bucket['kwh'])
        bucket['kwh'] -= take
        drawn[bucket['origin']] += take
        remaining -= take
    shortage = remaining
    from_curtail = drawn['限电充电']
    from_other = drawn['非限电充电']
    is_self = row['purpose'] == '储能自用'
    # 自用放电不形成回补；只有上网且来历为限电桶的部分才回补毛损失。
    recover = Decimal(0) if is_self else from_curtail
    selfuse = from_curtail if is_self else Decimal(0)
    conversion_loss = discharge - traceable
    return {'kind': 'DISCHARGE', 'id': row['id'], 'device': row['device'], 'at': row['at'],
            'purpose': row['purpose'], 'discharge_kwh': str(quantize(discharge)),
            'traceable_kwh': str(quantize(traceable)),
            'from_curtail_kwh': str(quantize(from_curtail)),
            'from_other_kwh': str(quantize(from_other)),
            'recover_kwh': str(quantize(recover)),
            'selfuse_kwh': str(quantize(selfuse)),
            'loss_kwh_storage': str(quantize(conversion_loss)),
            'shortage_kwh': str(quantize(shortage)),
            'code': 'STORAGE_TRACE' if shortage == 0 else 'ORIGIN_SHORTAGE'}

def apply(state):
    context = state['context']
    cadence = context['cadence_seconds']
    charges = build_charge_ledger(state['records'], state['event_unions'], context, cadence)
    # 每台储能各自维护来历桶；桶按充电时间 FIFO。
    devices = {}
    for row in state['records']:
        if row['kind'] != 'STORAGE':
            continue
        meta = context['devices'][row['device']]
        devices.setdefault(row['device'], {'queue': [], 'round_trip': meta.get('round_trip', '1')})
    discharge_rows = []
    pending = []
    for charge in charges:
        bucket = devices.setdefault(charge['device'], {'queue': [], 'round_trip': context['devices'][charge['device']].get('round_trip', '1')})
        if number(charge['curtail_charge_kwh']) > 0:
            bucket['queue'].append({'origin': '限电充电', 'kwh': number(charge['curtail_charge_kwh']), 'from': charge['id']})
        if number(charge['other_charge_kwh']) > 0:
            bucket['queue'].append({'origin': '非限电充电', 'kwh': number(charge['other_charge_kwh']), 'from': charge['id']})
    for row in sorted((r for r in state['records'] if r['kind'] == 'STORAGE' and r['direction'] == '放电'),
                      key=lambda r: (instant(r['at']), r['id'])):
        traced = trace_discharge(row, devices[row['device']], cadence)
        discharge_rows.append(traced)
        if traced['code'] != 'STORAGE_TRACE':
            pending.append({'id': traced['id'], 'device': traced['device'], 'at': traced['at'],
                            'code': 'ORIGIN_SHORTAGE', 'detail': '放电缺少可追溯充电来历',
                            'shortage_kwh': traced['shortage_kwh']})
    totals_num = {
        'curtail_charge_kwh': quantize(sum((number(r['curtail_charge_kwh']) for r in charges), Decimal(0))),
        'other_charge_kwh': quantize(sum((number(r['other_charge_kwh']) for r in charges), Decimal(0))),
        'discharge_kwh': quantize(sum((number(r['discharge_kwh']) for r in discharge_rows), Decimal(0))),
        'recover_total_kwh': quantize(sum((number(r['recover_kwh']) for r in discharge_rows), Decimal(0))),
        'selfuse_total_kwh': quantize(sum((number(r['selfuse_kwh']) for r in discharge_rows), Decimal(0))),
        'storage_loss_kwh': quantize(sum((number(r['loss_kwh_storage']) for r in discharge_rows), Decimal(0))),
        'shortage_kwh': quantize(sum((number(r['shortage_kwh']) for r in discharge_rows), Decimal(0))),
        'remaining_curtail_kwh': quantize(sum((b['kwh'] for d in devices.values() for b in d['queue'] if b['origin'] == '限电充电'), Decimal(0))),
        'remaining_other_kwh': quantize(sum((b['kwh'] for d in devices.values() for b in d['queue'] if b['origin'] == '非限电充电'), Decimal(0))),
    }
    totals = {k: str(v) for k, v in totals_num.items()}
    gross = sum((number(r['loss_kwh']) for r in state['energy_rows'] if r['loss_kwh'] is not None), Decimal(0))
    net = gross - totals_num['recover_total_kwh']
    # 来历守恒：限电充入 = 回补 + 自用限电 + 限电桶结余（量化到 0.0001 后比较）。
    storage_balanced = totals_num['curtail_charge_kwh'] == quantize(
        totals_num['recover_total_kwh'] + totals_num['selfuse_total_kwh'] + totals_num['remaining_curtail_kwh'])
    state['storage'] = {'charges': charges, 'discharges': discharge_rows, 'pending': pending,
                        'totals': totals, 'gross_loss_kwh': str(quantize(gross)),
                        'net_loss_kwh': str(quantize(net)), 'storage_balanced': storage_balanced}
    state['views']['storage'] = {
        'title': '储能回补裁定',
        'rows': charges + discharge_rows,
        'metrics': {'毛损失_kWh': str(quantize(gross)), '回补合计_kWh': str(totals['recover_total_kwh']),
                    '净损失_kWh': str(quantize(net)), '损耗合计_kWh': str(totals['storage_loss_kwh']),
                    '待查片段': len(pending)}}
