# 每日公开研究看板（GitHub 全自动化版）

参考 `bitwu-research.github.io` 的形态与数据源思路，自建的**纯 GitHub 自动化**版本。
原仓库只放出静态 HTML、没有开源生成代码、也没有 `.github/workflows`（它靠仓库外脚本 push）。
本方案把"抓取 → 生成 → 部署"全部收进 GitHub Actions，可审计、零外部依赖。

## 它做什么
- 每天**北京时间 20:00**（= UTC 12:00）由 GitHub Actions cron 自动触发
- 抓取公开 API（无需密钥）：
  - **CoinGecko** — BTC / ETH / BNB 实时价 + 24h 涨跌幅
  - **OKX** — BTC-USDT 最新价、24h 高低、近 24 根 1H K 线
- 生成当日看板 `<YYYY-MM-DD>/index.html`、首页 `index.html`、归档 `archive.html`
- 用 `GITHUB_TOKEN` 自动 commit 回仓库，GitHub Pages 自动部署

## 本地运行（验证用）
```bash
python generate.py
```
会在当前目录生成 `2026-XX-XX/`、`index.html`、`archive.html`。

## 接入自己的 GitHub 仓库
1. 新建一个仓库（公开，因为 GitHub Pages 对公开仓库免费）
2. 把本目录内容（含 `.github/`）push 上去
3. 仓库 **Settings → Pages → Source** 选 `Deploy from a branch` → `main` → `/ (root)`
4. 第一次可手动到 **Actions** 页点 `daily-board` → `Run workflow` 立即跑一次看效果
5. 之后每天 20:00 自动更新；也可随时手动触发

## 自定义
- **加币种**：改 `generate.py` 里 CoinGecko 的 `ids` 与 `row()` 调用
- **改时间**：改 `daily.yml` 的 `cron`（GitHub 用 UTC）
- **加热帖榜 / 安全提醒**：原仓库这两块没有明确公开 API（疑似人工或爬社交平台），
  需自行接入数据源；本原型先交付可全自动的"市场体温"核心部分

## 已知限制
- CoinGecko 免费档有速率限制，cron 一天一次完全够用
- 偶发网络抖动已由 `http_get` 的 3 次重试兜底
- 站内所有结论均基于公开数据，不含投资建议
