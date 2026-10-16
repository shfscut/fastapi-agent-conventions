# 领域术语与架构决策记录

同一个领域概念在表名、类名、接口字段和对话里叫法不一致，agent 每次都要重新推测含义，写出来的命名也会继续分叉。`CONTEXT.md` 把术语固定下来，ADR 记录那些从代码里看不出原因的决策。两者都是写给人和 agent 共同读的。

## 文件约定

```
CONTEXT.md                 # 领域术语表，放在仓库根目录，必须提交
docs/adr/NNNN-<slug>.md    # 架构决策记录，4 位编号递增，必须提交
```

## `CONTEXT.md`

只收录本服务特有、或在本服务里有特定含义的术语。通用技术名词（repository、schema 等）不写。

每个术语写清三件事：定义、在代码里叫什么、不要用的别名。

```markdown
# CONTEXT

## 订单（Order）

用户一次下单行为产生的记录，包含一个或多个订单行。创建后不可删除，只能取消。

- 代码：`Order`（models）、`orders`（表）、`OrderRead`（schema）、`/orders`（接口）
- 不要用：purchase、trade

## 订单行（Order Line）

订单中的一个商品及其数量、成交单价。成交单价在下单时固定，之后商品改价不影响已有订单行。

- 代码：`OrderLine`、`order_lines`、`OrderLineRead`
- 不要用：order item、detail

## 取消（Cancel）

把订单状态改为 `cancelled`，保留记录。区别于删除：订单不支持物理删除。

- 代码：`OrderStatus.CANCELLED`、`order_service.cancel_order()`、`POST /orders/{order_id}/cancel`
- 不要用：void、revoke
```

维护规则：

- 新的领域概念先补进 `CONTEXT.md`，再按条目里的命名写代码。
- 改名时同步更新术语表、代码和迁移，不允许新旧名字长期并存。

## ADR

### 什么时候写

- 有取舍的决策：选了 A 而没选 B，且理由不在代码里。
- 反直觉的做法：不解释的话，后来的人或 agent 很可能会"顺手修正"它。
- 影响多个 domain 或对外契约的约定。

能从代码直接看出来的事、只影响一个函数的实现细节，不写 ADR。

### 模板

```markdown
# 0003. 订单行冗余存储成交单价

- 状态：已采纳        <!-- 提议 / 已采纳 / 已废弃（被 NNNN 取代） -->
- 日期：2026-10-16

## 背景

商品价格会调整，但已下单的订单金额不能随之变化。

## 决策

`order_lines` 表冗余存储 `unit_price`，下单时从商品表复制，之后不再关联更新。

## 后果

- 订单金额可以直接从订单行汇总，不依赖商品价格历史。
- 商品表和订单行的价格允许不一致，这是预期行为，不是数据错误。
```

### 维护规则

- ADR 只追加，不改写。决策变化时新写一篇，并把旧的状态改为 `已废弃（被 NNNN 取代）`。
- 文件名用决策本身做 slug，例如 `0003-store-unit-price-on-order-line.md`。
