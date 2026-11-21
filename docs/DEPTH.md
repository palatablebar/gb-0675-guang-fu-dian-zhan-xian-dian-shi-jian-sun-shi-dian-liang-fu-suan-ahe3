# 深度登记 光伏电站限电事件与损失电量复算

规模：中型。使用者：新能源场站运营分析员。核心规则：仅用有效对照逆变器和相同辐照区间拟合基线；重叠限电事件先求并集再积分。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 遥测采信 | 执行并复核遥测采信 | `POST /api/intake` | `app/modules/intake/rules.py` | `tests/test_intake.py` |
| M2 设备映射 | 执行并复核设备映射 | `POST /api/devices` | `app/modules/devices/rules.py` | `tests/test_devices.py` |
| M3 事件切片 | 执行并复核事件切片 | `POST /api/slicing` | `app/modules/slicing/rules.py` | `tests/test_slicing.py` |
| M4 基线拟合 | 执行并复核基线拟合 | `POST /api/baseline` | `app/modules/baseline/rules.py` | `tests/test_baseline.py` |
| M5 损失核算 | 执行并复核损失核算 | `POST /api/loss` | `app/modules/loss/rules.py` | `tests/test_loss.py` |
| M6 储能回补 | 执行并复核储能回补 | `POST /api/storage` | `app/modules/storage/rules.py` | `tests/test_storage.py`、`tests/test_storage_api.py` |
| M7 能量对账 | 执行并复核能量对账 | `POST /api/reconcile` | `app/modules/reconcile/rules.py` | `tests/test_reconcile.py` |
| M8 运行归档 | 执行并复核运行归档 | `POST /api/archive` | `app/modules/archive/rules.py` | `tests/test_archive.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码中文状态 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_legacy_source` |
| TRAP-02 | BOM表头 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_bom_source` |
| TRAP-04 | 分段表头 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_segment_header` |
| TRAP-05 | 缺列记录 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_bad_column` |
| TRAP-18 | 空态 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_three_empty_types` |
| TRAP-07 | 遥测哨兵 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/devices/rules.py` | `tests/test_devices.py::test_sentinel_real` |
| TRAP-14 | 设备时刻冲突 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/devices/rules.py` | `tests/test_devices.py::test_conflict_both_isolated` |
| TRAP-15 | 功率单位 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/devices/rules.py` | `tests/test_devices.py::test_megawatt_conversion` |
| TRAP-06 | 全角千分位 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/devices/rules.py` | `tests/test_devices.py::test_fullwidth_number` |
| TRAP-11 | UTC归一 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/devices/rules.py` | `tests/test_devices.py::test_time_equivalence` |
| TRAP-23 | 限电区间并集 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/slicing/rules.py` | `tests/test_slicing.py::test_overlapping_real` |
| TRAP-24 | 非限电充电冒充回补 | 净损失被多扣 | 充电与限电并集求交集分桶，非限电桶放电不回补 | `app/modules/storage/rules.py` | `tests/test_storage.py::test_non_curtail_charge_not_recovery_source` |
| TRAP-25 | 储能自用计入回补 | 净损失被多扣 | 自用只耗限电桶，回补字段强制为0 | `app/modules/storage/rules.py` | `tests/test_storage.py::test_self_use_drains_curtail_but_no_recovery` |
| TRAP-26 | 放电无来历 | 虚增回补、证据断裂 | 缺口记 ORIGIN_SHORTAGE 进待查并阻断封存 | `app/modules/storage/rules.py` | `tests/test_storage.py::test_unknown_origin_discharge_pending` |
| TRAP-27 | 充放损耗无去向 | 能量账不平 | 逐笔列示转换损耗，来历守恒校验 | `app/modules/storage/rules.py` | `tests/test_storage.py::test_round_trip_loss_has_destination` |
| TRAP-28 | 重试覆盖已确认值 | 复核结论被改写 | 快照重算批号不变，revision/status 保留 | `app/store.py`、`app/engine.py` | `tests/test_storage_api.py::test_rerun_keeps_run_and_confirmed_revision` |

## 对账规则

原始逻辑输入=采纳行+隔离行+空行+重复表头+同值重复。业务计算按 DATA-DICTIONARY.md 分别核验，不能把上级与下级重复加总。所有隔离保留编号、原值、原始行号和稳定原因码。储能按毛损失−回补=净损失、限电充入=回补+自用限电+限电桶结余两条恒等式对账，待查片段与隔离、未定片段并列展示并阻断封存。

## 已知不覆盖

数据来自仓内样例或用户粘贴文件，不连接外部业务生产系统。平台不执行实际资金划转或行政审批。
