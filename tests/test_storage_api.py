from fastapi.testclient import TestClient
from app import main
from decimal import Decimal

def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB_PATH', str(tmp_path / 'test.sqlite'))
    return TestClient(main.app)

def test_rerun_keeps_run_and_confirmed_revision(tmp_path, monkeypatch):
    # 重试不得新增版本或覆盖确认值：同输入快照重算批号不变，已复核状态与版本号保留。
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    reviewed = c.post(f'/api/runs/{rid}/review', json={'revision': 1}).json()
    assert reviewed['revision'] == 2
    assert reviewed['status'] == '已复核'
    rerun = c.post(f'/api/runs/{rid}/rerun', json={}).json()
    assert rerun['manifest']['run_id'] == rid
    assert rerun['revision'] == 2
    assert rerun['status'] == '已复核'
    assert len(c.get('/api/runs').json()) == 1

def test_switch_failure_keeps_old_run(tmp_path, monkeypatch):
    # 切换失败（非法输入）不得覆盖或删除旧批次，旧版结果仍可读。
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    bad = c.post('/api/runs', json={'csv_text': 'only,header\n'})
    assert bad.status_code == 422
    history = c.get('/api/runs').json()
    assert len(history) == 1
    assert history[0]['id'] == rid
    assert c.get(f'/api/runs/{rid}').status_code == 200

def test_storage_endpoint_and_page(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    api = c.post('/api/storage', json={'dataset': 'clean'}).json()
    assert api['storage']['net_loss_kwh'] == '25.1667'
    html = c.get(f'/storage?run_id={rid}').text
    assert '25.1667' in html
    assert '回补' in html and '待查片段' in html

def test_reconcile_net_loss_identity(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    b = run['balance']
    assert Decimal(b['gross_loss_kwh']) - Decimal(b['recover_kwh']) == Decimal(b['net_loss_kwh'])
    assert b['net_balanced'] is True
    assert b['storage_balanced'] is True

def test_dirty_pending_blocks_export_ready(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'dirty'}).json()
    assert run['archive']['status'] == '待复核'
    assert run['balance']['pending_storage'] == 1

def test_export_bundle_contains_storage(tmp_path, monkeypatch):
    import io, json, zipfile
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    z = zipfile.ZipFile(io.BytesIO(c.get(f'/api/export/{rid}').content))
    evidence = json.loads(z.read('evidence.json'))
    assert evidence['storage']['net_loss_kwh'] == '25.1667'
    assert len(evidence['storage']['discharges']) == 3
