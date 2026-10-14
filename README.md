# AI Investment Intelligence 0.1.0-dev

独立投资情报项目，提供美股、数字货币、A股行情与 RSS 新闻看板。后台默认每 60 秒采集，看板每 15 秒读取后台。所有价格保留供应商时间戳，300 秒以上标记 stale。闭市期间旧成交仍显示 stale，不解释为当前可成交价格。

## 启动

Python 3.10+，无需第三方依赖。在本目录复制 `.env.example` 为 `.env`，填写本项目独立凭证，然后运行：

```
python app.py
```

打开 http://127.0.0.1:8765 。单次采集：`python app.py --once`。修改 `config.json` 设置自选标的和经过确认的 RSS 源。

## 数据能力

- 美股：Alpaca latest trade / IEX，覆盖单一交易所。未实现 websocket 推送、盘口深度或盘面指标。
- 数字货币：Coinbase 最新 spot trades，BTC-USD / ETH-USD，交易所覆盖。
- A股：Tushare rt_k，需要 token 和单独的实时接口权限；缺失时间戳或权限时 unavailable。
- 新闻：Federal Reserve / CoinDesk RSS。尚未接入 A股公告源、公司公告源或 AI 重要性评估。无源不填新闻。
- 当前为事实采集原型，AI研究、组合决策和消息提醒待后续接入。没有自动交易功能。

## GitHub

源码已发布到用户授权的公开仓库 https://github.com/tudefeng123-ctrl/tudefeng 。这不等于网页服务已部署，启动方式仍是本地运行 `python app.py`。不要上传 `.env` 或旧系统账户数据。

## 官方接口文档

- https://docs.alpaca.markets/us/reference/stocklatesttradesingle-1
- https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-trades
- https://tushare.pro/document/1?doc_id=372