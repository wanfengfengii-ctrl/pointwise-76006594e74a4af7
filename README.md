# 临堤排水计量仓 V1

临堤排水中心接收计量归档的分区原批。接入员核对同件重投和原位勘误，档案员逐卷实读原行，日结员按固定口径签发，报送岗把带符号差额送入下游日账。复核员可以按原号领取已签发的日表。

## 运行

使用 Python 3.11 或更新版本的标准库。在项目根目录运行控制台提供的回归入口和整班样例。

```sh
python3 -B check_project.py
python3 -B -m lake samples/shift.json
```

样例在独立临时仓中登记甲乙两卷，载入甲区的 0、19、20、25 L，然后在 20 L 阈值下领取 2 笔、45 L 的现行汇总及起始差额。将 19 L 更正为 22 L 后，报送增加 1 笔、22 L。两卷分别核读后，日结员签发 3 笔、67 L。随后删除 25 L 的行，关仓重开，按原号领取 3 笔、67 L，现行为 2 笔、42 L，原游标续读 −1 笔、−25 L。样例核对实测值后输出计量场景和交班结果。

## 公开 Python 接口

```python
from lake import (
    correct_row, freeze, load_batch, mount_read, open_warehouse,
    read_feed, read_frozen, read_live, register_partition,
)

with open_warehouse('shift-warehouse', threshold=20) as warehouse:
    register_partition(warehouse, 'A', 'vault-A')
    load_batch(warehouse, 'A', 'batch-1', [('01', 19), ('02', 25)])
    first_page = read_feed(warehouse)
    correct_row(warehouse, 'edit-1', 'A', '01', 19, 22)
    mounted = mount_read(warehouse, 'A')
    issued = freeze(warehouse, 'shift-1')
    live = read_live(warehouse)
    incremental = read_feed(warehouse, first_page.cursor)

with open_warehouse('shift-warehouse') as warehouse:
    assert read_frozen(warehouse, 'shift-1') == issued
```

- 首次开仓须提供非负整数 `threshold`。重开可省略阈值，显式传入时须与原仓一致。重复初始化保留分区、接纳和勘误结果、报送及签发件。每个线程使用自己的 `Warehouse`，同仓会话共享 SQLite 提交和挂载约束。
- 标识是非空 UTF-8 字符串，不带首尾空白或 NUL。卷引用为业务标识，仓库将其映射到自己的卷目录。同分区同卷可复领，同分区异卷或同卷绑定另一分区报 `BindingConflict`。未知分区报 `UnknownPartition`。
- `load_batch(warehouse, partition_id, batch_id, rows)` 接收有序 `SourceRow` 或 `(row_id, liters)` 对。空批可登记。批号在同仓唯一。同号同件按原分区、行序、行号及升值比较，返回原 `IntakeReceipt`。异件报 `BatchConflict`，批内重复或已占用行号报 `RowConflict`，无效输入报 `ValueError`。不同分区可分别使用同一本地行号。批内位置和原件在勘误后仍可核查。
- `correct_row(warehouse, request_id, partition_id, row_id, expected_liters, replacement_liters)` 使用精确旧值，`replacement_liters=None` 表示删除。0 L 是存在的有效值。删除后该行身份仍占用。同号同申请复领 `CorrectionReceipt`，同号异申请报 `CorrectionConflict`。新申请对缺失或已删行报 `MissingRow`，旧值过期报 `StaleBeforeImage`。负数、布尔值和非整数升值报 `ValueError`。
- `mount_read(warehouse, partition_id)` 返回 `MountView`，行按行号排序，`covered_through` 是该卷最后已含的事实号。未接纳事实的空卷为 0，删空后的卷保留实际删除位置。挂载忙报 `MountBusy`，卷读或校验失败报 `MountReadError`，两者均没有部分结果。
- `read_live(warehouse, partition_id=None)` 返回阈值、达标笔数及总升量。存在行在 `liters >= threshold` 时贡献一笔及该行升值。全仓按分区归并，登记空区为 0 笔、0 L。所有数值用整升和精确整数运算。
- `freeze(warehouse, report_id)` 按一次提交视图冻结全仓事实截点、阈值及计量值。同号再办返回原件。`read_frozen` 按原号领取，未知号返回 `None`。后续勘误仍更新现行账。签发本身不分配事实号或报送位置。
- `read_feed(warehouse, cursor=None)` 从起点或 `FeedCursor` 位置之后读取已确认条目，顺序为报送位置。每条包含源事实号、分区及两项有符号差额。差额两项皆零时不发条目，事实与卷覆盖仍可推进。空页沿用输入游标，畸形或超出范围游标报 `ValueError`。

原批和勘误通过落盘主库与相关附加卷的同一事务提交。事务失败时，行、回执、卷覆盖、现行汇总及应发差额一起回滚。签发使用同一写事务读出全仓截点并保存固定件。仓库目录在关闭会话后可整体搬运，主库和卷目录需一同保留。

确定性故障检查可通过 `open_warehouse` 的 `before_commit(operation)` 和 `after_scan_row(partition_id, row)` 参数中断真实事务或实读。标记分别为 `register_partition`、`load_batch`、`correct_row` 和 `freeze`。前者在实际写入后、提交前调用，后者在每次卷扫描取得一行后调用。回归使用独立临时仓，期望值来自手算或明确的不变量。
