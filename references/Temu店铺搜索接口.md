# Temu 店铺搜索接口

## 目录

- [脚本调用](#脚本调用)
- [基础参数](#基础参数)
- [站点解析](#站点解析)
- [区间筛选参数](#区间筛选参数)
- [排序字段](#排序字段)
- [响应与失败处理](#成功响应)

## 脚本调用

单页数量最大为 200。

通过以下命令调用：

```bash
python3 scripts/temu_shop_search.py \
  --param "keyword=店铺名称或ID" \
  --param "siteId=48" \
  --param "size=20" \
  --param "sort=mallSold" \
  --param "order=desc"
```

服务端要求暂停查询时，按 [查询暂停与恢复流程](查询暂停与恢复流程.md) 提示用户；恢复条件满足后再次运行同一命令。

## 基础参数

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `keyword` | string | 无 | 店铺名称或店铺 ID，最长 300 个字符 |
| `catIds` | integer，可重复 | 无 | Temu 通用类目 ID；多个值匹配其中任一类目 |
| `siteId` | integer | `48` | 极鲸云站点 ID；美国站直接使用默认值，其他国家或地区先用 `scripts/temu_site_list.py` 实时解析 |
| `page` | integer | `1` | 页码，从 1 开始 |
| `size` | integer | `20` | 每页数量，最大 200 |
| `sort` | string | 无 | 排序字段，取值见下方 |
| `order` | string | `desc` | `asc` 或 `desc` |
| `hostingMode` | integer | 无 | 托管模式：`1` 全托管，`2` 半托管 |

不要从类目中文名或英文名自行推断 ID。没有可信 ID 时，不传 `catIds`，仅按店铺关键词搜索；用户的请求必须限定类目时，请用户提供明确类目 ID。

## 站点解析

- 未指定站点或指定美国站时，直接使用默认站点 ID `48`，不额外查询站点列表。
- 用户指定其他国家或地区时，运行 `python3 scripts/temu_site_list.py --country "国家或地区名"`，将唯一精确匹配的站点 ID 传给店铺搜索。
- 脚本实时匹配服务端返回的中文名或英文名，不使用本地静态站点表，不按语言、币种或相似名称猜测。
- 无匹配时请用户确认国家或地区名；多个匹配时列出中文站点名请用户澄清，不自行选择。

## 区间筛选参数

每项均支持 `Min` 和 `Max` 后缀：

| 维度 | 最小值 | 最大值 |
| --- | --- | --- |
| 店铺总销量 | `mallSoldMin` | `mallSoldMax` |
| 店铺总销售额 | `mallSalesMin` | `mallSalesMax` |
| 店铺评分 | `mallStarMin` | `mallStarMax` |
| 评论数 | `reviewNumMin` | `reviewNumMax` |
| 商品数量 | `goodsNumMin` | `goodsNumMax` |
| 粉丝数 | `followerNumMin` | `followerNumMax` |
| 平均价格 | `avgPriceMin` | `avgPriceMax` |
| 开店时间 | `mallOpenTimeMin` | `mallOpenTimeMax` |
| 日均销量 | `daySoldMin` | `daySoldMax` |
| 周均销量 | `weekSoldMin` | `weekSoldMax` |
| 月均销量 | `monthSoldMin` | `monthSoldMax` |
| 日均销售额 | `daySalesMin` | `daySalesMax` |
| 周均销售额 | `weekSalesMin` | `weekSalesMax` |
| 月均销售额 | `monthSalesMin` | `monthSalesMax` |
| 日均销量增长率 | `daySoldRateMin` | `daySoldRateMax` |
| 周均销量增长率 | `weekSoldRateMin` | `weekSoldRateMax` |
| 月均销量增长率 | `monthSoldRateMin` | `monthSoldRateMax` |
| 日均销售额增长率 | `daySalesRateMin` | `daySalesRateMax` |
| 周均销售额增长率 | `weekSalesRateMin` | `weekSalesRateMax` |
| 月均销售额增长率 | `monthSalesRateMin` | `monthSalesRateMax` |
| 日均商品数 | `dayItemCountMin` | `dayItemCountMax` |
| 周均商品数 | `weekItemCountMin` | `weekItemCountMax` |
| 月均商品数 | `monthItemCountMin` | `monthItemCountMax` |
| 日均商品数增长率 | `dayItemCountRateMin` | `dayItemCountRateMax` |
| 周均商品数增长率 | `weekItemCountRateMin` | `weekItemCountRateMax` |
| 月均商品数增长率 | `monthItemCountRateMin` | `monthItemCountRateMax` |
| 日均粉丝数 | `dayFollowerMin` | `dayFollowerMax` |
| 周均粉丝数 | `weekFollowerMin` | `weekFollowerMax` |
| 月均粉丝数 | `monthFollowerMin` | `monthFollowerMax` |
| 日均粉丝数增长率 | `dayFollowerRateMin` | `dayFollowerRateMax` |
| 周均粉丝数增长率 | `weekFollowerRateMin` | `weekFollowerRateMax` |
| 月均粉丝数增长率 | `monthFollowerRateMin` | `monthFollowerRateMax` |
| 日动销商品数 | `daySellthroughCountMin` | `daySellthroughCountMax` |
| 周动销商品数 | `weekSellthroughCountMin` | `weekSellthroughCountMax` |
| 月动销商品数 | `monthSellthroughCountMin` | `monthSellthroughCountMax` |
| 日动销率 | `daySellthroughRateMin` | `daySellthroughRateMax` |
| 周动销率 | `weekSellthroughRateMin` | `weekSellthroughRateMax` |
| 月动销率 | `monthSellthroughRateMin` | `monthSellthroughRateMax` |

开店时间使用 ISO 8601 日期时间。平均价格和销售额使用当前查询站点币种，向用户展示时必须标明币种。

比率口径需要特别区分：

- 销量、销售额、商品数和粉丝数的增长率，查询和响应均使用小数；例如用户要求增长率至少 20%，请求值使用 `0.2`。
- 动销率查询使用 0–100 的百分比值；例如至少 20%，请求值使用 `20`。响应中动销率仍是小数，展示给用户时转成百分比。

## 排序字段

| 维度 | `sort` 可选值 |
| --- | --- |
| 店铺总销量 | `mallSold` |
| 店铺总销售额 | `mallSales` |
| 店铺评分 | `mallStar` |
| 评论数 | `reviewNum` |
| 商品数量 | `goodsNum` |
| 粉丝数 | `followerNum` |
| 平均价格 | `avgPrice` |
| 热度 | `hot` |
| 日/周/月均销量 | `daySold`、`weekSold`、`monthSold` |
| 日/周/月均销量增长率 | `daySoldRate`、`weekSoldRate`、`monthSoldRate` |
| 日/周/月均销售额 | `daySales`、`weekSales`、`monthSales` |
| 日/周/月均销售额增长率 | `daySalesRate`、`weekSalesRate`、`monthSalesRate` |
| 日/周/月均商品数 | `dayItemCount`、`weekItemCount`、`monthItemCount` |
| 日/周/月均商品数增长率 | `dayItemCountRate`、`weekItemCountRate`、`monthItemCountRate` |
| 日/周/月均粉丝数 | `dayFollower`、`weekFollower`、`monthFollower` |
| 日/周/月均粉丝数增长率 | `dayFollowerRate`、`weekFollowerRate`、`monthFollowerRate` |
| 日/周/月动销商品数 | `daySellthroughCount`、`weekSellthroughCount`、`monthSellthroughCount` |
| 日/周/月动销率 | `daySellthroughRate`、`weekSellthroughRate`、`monthSellthroughRate` |
| 开店时间 | `mallOpenTime` |
| 数据更新时间 | `updateTime` |

`order` 使用 `asc` 或 `desc`。

## 成功响应

```json
{
  "code": 0,
  "data": {
    "total": 100,
    "list": []
  }
}
```

- `data.total` 是当前条件下的命中总数。
- `data.list` 是当前页店铺列表。
- 核心字段包括站点 ID、店铺 ID、名称、Logo、评分、评论数、商品数量、粉丝数、总销量、总销售额、平均价格、热度、经营类目、托管模式、开店时间、数据更新时间和 `linkUrl`。
- 同时返回日/周/月均销量、销售额、商品数、粉丝数及其增长率，以及日/周/月动销商品数和动销率。
- `linkUrl` 指向该店铺在极鲸云的 Temu 店铺详情页。展示结果时必须将每个店铺名称写成 `[店铺名称](<linkUrl>)`；该要求覆盖列表、表格、排名、候选清单和正文，不因用户未主动要求链接、要求简洁回答或表格空间有限而省略。

## 失败处理

- 服务端要求暂停查询时，按 [查询暂停与恢复流程](查询暂停与恢复流程.md) 展示提示，有跳转地址时再展示可点击链接，不把它解释为无数据。
- 退出码 `1` 时读取 stderr 一级 `msg`，面向用户只提示该中文文案。
- `code != 0`、HTTP 非 2xx、响应不是 JSON 或缺少 `data` 时，本次查询失败。
- 请求多页时逐页累计并记录实际读取页数；未完成全部分页时不得声称结果为全量。
