#!/usr/bin/env python3
"""每日公开研究看板生成器（GitHub 全自动化版）

数据源（均为公开 API / 公开页面，无需密钥）：
  - CoinGecko                : 币价 + 24h 涨跌幅 (BTC/ETH/BNB)
  - OKX                      : BTC-USDT 现货最新价 / 24h 高低 / 近 24 根 1H K 线
  - bitwu-research.github.io : 每日 X 热帖榜、每日安全提醒（抓取后整理进来）

时间：北京时间 (UTC+8)
产物：
  - <YYYY-MM-DD>/index.html   当日看板（市场体温 + 热帖 + 安全）
  - index.html                首页（= 当日看板）
  - archive.html              按日期归档
  - .nojekyll

自动化：由 .github/workflows/daily.yml 的 cron（北京时间 20:10）触发；
原站 20:00 更新，我们 20:10 抓取以确保能拿到当天内容。
git commit/push 由 workflow 用 GITHUB_TOKEN 完成。
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import html as htmlmod
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
CST = timezone(timedelta(hours=8))

# ── 改成你自己的品牌名即可 ──
BRAND = "PEERS-MAX 公开研究看板"
SOURCE_SITE = "bitwu-research.github.io"


def log(*a):
    print("[gen]", *a, file=sys.stderr)


def http_text(url, timeout=25, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (daily-board)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except Exception as e:
            last = e
            log("http_text retry", i + 1, "failed:", e)
            time.sleep(1.5 * (i + 1))
    raise last


def http_json(url, timeout=20, retries=3):
    return json.loads(http_text(url, timeout, retries))


def strip_html(h):
    h = re.sub(r"<script[\s\S]*?</script>", "", h)
    h = re.sub(r"<style[\s\S]*?</style>", "", h)
    h = re.sub(r"<[^>]+>", " ", h)
    return htmlmod.unescape(re.sub(r"\s+", " ", h))


def pct(x):
    return f"{x:+.2f}%"


def fetch_market():
    out = {}
    try:
        cg = http_json(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum,binancecoin&vs_currencies=usd&include_24hr_change=true"
        )
        out["cg"] = {
            "BTC": (cg["bitcoin"]["usd"], cg["bitcoin"]["usd_24h_change"]),
            "ETH": (cg["ethereum"]["usd"], cg["ethereum"]["usd_24h_change"]),
            "BNB": (cg["binancecoin"]["usd"], cg["binancecoin"]["usd_24h_change"]),
        }
    except Exception as e:
        log("coingecko failed:", e)
        out["cg"] = None
    try:
        tk = http_json("https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT")["data"][0]
        kl = http_json("https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=24")["data"]
        hi = [float(k[2]) for k in kl]
        lo = [float(k[3]) for k in kl]
        out["okx"] = {
            "last": float(tk["last"]),
            "high24h": float(tk["high24h"]),
            "low24h": float(tk["low24h"]),
            "wh": max(hi),
            "wl": min(lo),
        }
    except Exception as e:
        log("okx failed:", e)
        out["okx"] = None
    return out


def fetch_source(date_str, kind):
    # 用原站部署版（与线上一致，比 raw 分支路径更稳）
    url = f"https://{SOURCE_SITE}/{kind}/{date_str}/index.html"
    try:
        return http_text(url)
    except Exception as e:
        log(f"source {kind}/{date_str} unavailable:", e)
        return None


def extract_hot(html):
    if not html:
        return None
    try:
        text = strip_html(html)
        items = re.findall(r"(\d+)\s+@([A-Za-z0-9_]+)\s+([\s\S]*?)查看原帖", text)
        urls = re.findall(r'href="(https://x\.com/[^"]+/status/\d+)"[^>]*>[\s\S]*?查看原帖', html)
        out = []
        for i, (rank, handle, summary) in enumerate(items):
            summary = re.sub(r"\s+", " ", summary).strip()
            url = urls[i] if i < len(urls) else "#"
            out.append((rank, handle, summary, url))
        return out if out else None
    except Exception as e:
        log("extract_hot failed:", e)
        return None


def extract_security(html):
    if not html:
        return None
    try:
        text = strip_html(html)
        m = re.search(r"行业风险等级[：:]\s*(\S+)", text)
        level = m.group(1) if m else "未知"
        items = re.findall(r"(\d+)\.\s+([\s\S]*?)(?=\s*\d+\.\s+|\s*行业风险等级|$)", text)
        urls = re.findall(r'href="(https://x\.com/[^"]+/status/\d+)"', html)
        out = []
        for i, (num, body) in enumerate(items):
            body = re.sub(r"\s+", " ", body).strip()
            if not body:
                continue
            url = urls[i] if i < len(urls) else "#"
            out.append((body, url))
        return {"level": level, "items": out} if out else None
    except Exception as e:
        log("extract_security failed:", e)
        return None


def render_hot(items):
    if not items:
        return "<p class='note'>今日热帖暂未更新（原站 20:00 更新，本页 20:10 抓取；若原站当日未更新则此处为空）。</p>"
    rows = "".join(
        f"<li><b>@{h}</b> {s} <a href='{u}' target='_blank' rel='noopener'>原帖↗</a></li>"
        for _, h, s, u in items
    )
    return (f"<p class='src'>内容整理自 {SOURCE_SITE}（每日 X 热帖榜）</p>"
            f"<ol class='hot'>{rows}</ol>")


def render_security(sec):
    if not sec:
        return "<p class='note'>今日安全提醒暂未更新。</p>"
    level = sec["level"]
    rows = "".join(
        f"<li>{b} <a href='{u}' target='_blank' rel='noopener'>来源↗</a></li>"
        for b, u in sec["items"]
    )
    return (f"<p>行业风险等级：<b>{level}</b></p>"
            f"<p class='src'>内容整理自 {SOURCE_SITE}（每日安全提醒）</p>"
            f"<ol class='sec'>{rows}</ol>")


def wrap(body, title):
    return f"""<!doctype html><html lang='zh'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{BRAND} {title}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem;color:#1a1a1a;background:#fff;line-height:1.6}}
 nav a{{margin-right:1rem;color:#2563eb;text-decoration:none;font-size:.9rem}}
 h1{{font-size:1.4rem}} h2{{font-size:1.15rem;margin-top:1.8rem;border-left:4px solid #2563eb;padding-left:.5rem}}
 table.mkt{{border-collapse:collapse;width:100%;margin:1rem 0}}
 table.mkt th,table.mkt td{{border:1px solid #e5e7eb;padding:.5rem .75rem;text-align:left}}
 .up{{color:#e11d48}} .down{{color:#059669}}
 .note{{color:#6b7280;font-size:.85rem}}
 .src{{color:#6b7280;font-size:.8rem;margin:.3rem 0}}
 ol.hot,ol.sec{{padding-left:1.2rem}} ol.hot li,ol.sec li{{margin:.4rem 0}}
 ul.arch li{{margin:.25rem 0}}
</style></head><body>
<nav><a href='/'>看板</a><a href='/archive.html'>归档</a></nav>
<h1>{BRAND} 📊</h1>
{body}
</body></html>"""


def page_day(date_str, m, hot, sec):
    cg = m.get("cg")
    okx = m.get("okx")

    def row(sym, name):
        if not cg:
            return f"<tr><td>{name}</td><td colspan='2'>数据获取失败</td></tr>"
        price, chg = cg[sym]
        cls = "up" if chg >= 0 else "down"  # 中国习惯：涨红跌绿
        return f"<tr><td>{name}</td><td>${price:,.2f}</td><td class='{cls}'>{pct(chg)}</td></tr>"

    okx_html = ""
    if okx:
        okx_html = (
            f"<p>OKX BTC-USDT 最新 <b>${okx['last']:,.1f}</b>；"
            f"24h 高 ${okx['high24h']:,.1f} / 低 ${okx['low24h']:,.1f}；"
            f"窗口(近24根1H)高 ${okx['wh']:,.1f} / 低 ${okx['wl']:,.1f}</p>"
        )
    body = f"""
    <h2>市场体温（{date_str} 北京时间）</h2>
    <table class='mkt'><tr><th>币种</th><th>价格(USD)</th><th>24h</th></tr>
      {row('BTC', 'BTC')}{row('ETH', 'ETH')}{row('BNB', 'BNB')}</table>
    {okx_html}
    <h2>🔥 每日 X 热帖榜</h2>
    {render_hot(hot)}
    <h2>🛡️ 每日安全提醒</h2>
    {render_security(sec)}
    <p class='note'>数据源：CoinGecko、OKX、{SOURCE_SITE}（均为公开数据，无需密钥）。
    时间均为北京时间。本页由 GitHub Actions 每日 20:10 自动生成，只整理公开数据，不构成投资建议。</p>
    """
    return wrap(body, date_str)


def main():
    today = datetime.now(CST)
    date_str = today.strftime("%Y-%m-%d")
    m = fetch_market()
    hot = extract_hot(fetch_source(date_str, "hot"))
    sec = extract_security(fetch_source(date_str, "security"))

    day_dir = os.path.join(ROOT, date_str)
    os.makedirs(day_dir, exist_ok=True)
    with open(os.path.join(day_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(page_day(date_str, m, hot, sec))

    dates = sorted(
        d for d in os.listdir(ROOT)
        if len(d) == 10 and d[4] == "-" and os.path.isdir(os.path.join(ROOT, d))
    )
    arch_links = "".join(f"<li><a href='/{d}/'>{d}</a></li>" for d in dates)
    arch = wrap(
        f"<h2>按日期归档</h2><ul class='arch'>{arch_links}</ul>"
        f"<p class='note'>生成于 {date_str}（北京时间）</p>",
        "归档",
    )
    with open(os.path.join(ROOT, "archive.html"), "w", encoding="utf-8") as f:
        f.write(arch)

    with open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8") as f:
        f.write(page_day(date_str, m, hot, sec))

    with open(os.path.join(ROOT, ".nojekyll"), "a", encoding="utf-8") as f:
        pass

    log("generated", date_str, "| archive days:", len(dates),
        "| hot:", len(hot) if hot else 0, "| sec:", len(sec["items"]) if sec else 0)


if __name__ == "__main__":
    main()
