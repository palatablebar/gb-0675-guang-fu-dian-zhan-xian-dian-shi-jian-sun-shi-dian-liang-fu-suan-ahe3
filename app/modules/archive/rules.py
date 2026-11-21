import hashlib,json

def archive_decision(state):
    b=state['balance'];ready=b['row_balanced'] and b['time_balanced'] and b['energy_balanced'] and not b['unknown_segments'] and not state['quarantine'] and b['storage_balanced'] and b['net_balanced'] and not b['pending_storage']
    return {'status':'可归档' if ready else '待复核','seal':hashlib.sha256(json.dumps(state['energy_rows'],sort_keys=True).encode()).hexdigest(),'segments':len(state['energy_rows']),'unknown':b['unknown_segments'],'pending_storage':b['pending_storage'],'net_loss_kwh':b['net_loss_kwh']}
def apply(state):
    state['archive']=archive_decision(state);state['views']['archive']={'title':'运行凭证','rows':state['event_unions'],'metrics':{'切片':state['archive']['segments'],'未定':state['archive']['unknown'],'待查储能':state['archive']['pending_storage'],'净损失_kWh':state['archive']['net_loss_kwh'],'状态':state['archive']['status']}}
