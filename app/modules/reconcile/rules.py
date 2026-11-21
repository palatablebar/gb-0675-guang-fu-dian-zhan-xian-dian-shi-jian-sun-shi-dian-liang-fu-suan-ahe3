from decimal import Decimal
from app.coerce import number

def reconcile(state):
    known=[r for r in state['energy_rows'] if r['loss_kwh'] is not None];unknown=[r for r in state['energy_rows'] if r['loss_kwh'] is None]
    sums={k:sum((number(r[k]) for r in known),Decimal(0)) for k in ['loss_kwh','actual_kwh','baseline_kwh']}
    union_seconds=sum(r['seconds'] for r in state['event_unions']);slice_seconds=sum(r['seconds'] for r in state['energy_rows']);c=state['counts'];explained=len(state['records'])+len(state['quarantine'])+c['blank']+c['duplicate']+c['repeated_header']
    # Decimal周期小数允许最后一位精度误差，展示前统一量化到0.0001kWh再检查。
    quant=lambda v:v.quantize(Decimal('.0001'))
    storage=state.get('storage')
    recover=number(storage['totals']['recover_total_kwh']) if storage else Decimal(0)
    net_loss=quant(sums['loss_kwh']-recover)
    pending=len(storage['pending']) if storage else 0
    storage_balanced=storage['storage_balanced'] if storage else True
    net_balanced=(not storage) or net_loss==number(storage['net_loss_kwh'])
    return {'input':c['input'],'accepted':len(state['records']),'quarantined':len(state['quarantine']),'row_balanced':explained==c['input'],'union_seconds':union_seconds,'slice_seconds':slice_seconds,'time_balanced':union_seconds==slice_seconds,'loss_kwh':str(quant(sums['loss_kwh'])),'actual_kwh':str(quant(sums['actual_kwh'])),'baseline_kwh':str(quant(sums['baseline_kwh'])),'energy_balanced':quant(sums['baseline_kwh'])==quant(sums['actual_kwh']+sums['loss_kwh']),'unknown_segments':len(unknown),'unknown_seconds':sum(r['seconds'] for r in unknown),'gross_loss_kwh':str(quant(sums['loss_kwh'])),'recover_kwh':str(quant(recover)),'net_loss_kwh':str(net_loss),'storage_balanced':storage_balanced,'net_balanced':net_balanced,'pending_storage':pending}
def apply(state):
    state['balance']=reconcile(state);state['views']['reconcile']={'title':'时间与能量四账','rows':[state['balance']],'metrics':{'毛损失_kWh':state['balance']['gross_loss_kwh'],'回补_kWh':state['balance']['recover_kwh'],'净损失_kWh':state['balance']['net_loss_kwh'],'未定分钟':state['balance']['unknown_seconds']//60,'并集分钟':state['balance']['union_seconds']//60,'待查片段':state['balance']['pending_storage']}}
