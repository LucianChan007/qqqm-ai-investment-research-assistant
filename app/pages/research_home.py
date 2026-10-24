from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from app.services.ui_workflows import run_project_command

ROOT = Path(__file__).resolve().parents[2]
MARKET_DB = ROOT / "data" / "market_data.db"
USERS_DB = ROOT / "data" / "users.db"
AUTH_KEY = "qqqm_authenticated_user"

st.markdown("""
<style>
:root { --qqqm-ink:#15263f; --qqqm-muted:#6b7890; --qqqm-blue:#2458e6; }
.block-container {padding-top:1.7rem; padding-bottom:2.5rem; max-width:1440px;}
[data-testid="stSidebar"] {border-right:1px solid rgba(100,116,139,.18);}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {letter-spacing:-.02em;}
.qqqm-hero {padding:28px 30px; border-radius:22px; color:white; background:linear-gradient(118deg,#101d35 0%,#1d3e78 58%,#2765e8 100%); position:relative; overflow:hidden; margin-bottom:20px;}
.qqqm-hero:after {content:''; position:absolute; width:280px;height:280px;right:-70px;top:-130px;border:1px solid rgba(255,255,255,.18);border-radius:50%;box-shadow:0 0 0 28px rgba(255,255,255,.035),0 0 0 58px rgba(255,255,255,.025);}
.qqqm-kicker {font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:#b9d1ff;margin-bottom:10px;}
.qqqm-hero h1 {font-size:32px;line-height:1.18;margin:0 0 9px 0;color:white;font-weight:750;letter-spacing:-.035em;}
.qqqm-hero p {font-size:14px;line-height:1.65;color:#e0eaff;max-width:760px;margin:0;}
.qqqm-pill {display:inline-block;border:1px solid rgba(255,255,255,.25);background:rgba(255,255,255,.09);border-radius:999px;padding:6px 10px;font-size:11px;color:#f0f5ff;margin-top:18px;}
.metric-card {background:var(--secondary-background-color);border:1px solid rgba(100,116,139,.19);border-radius:16px;padding:17px 18px;min-height:120px;}
.metric-label {font-size:12px;color:var(--qqqm-muted);margin-bottom:9px;}
.metric-value {font-size:27px;line-height:1.2;font-weight:750;letter-spacing:-.035em;color:var(--qqqm-ink);}
.metric-note {font-size:11px;color:var(--qqqm-muted);margin-top:8px;}
.section-title {font-size:19px;font-weight:750;letter-spacing:-.025em;margin:18px 0 4px;color:var(--text-color);}
.section-sub {font-size:12px;color:var(--qqqm-muted);margin-bottom:12px;}
.feature-card {border:1px solid rgba(100,116,139,.2);border-radius:16px;padding:18px 18px 14px;min-height:168px;background:var(--secondary-background-color);}
.feature-num {font-size:11px;color:#3567e8;font-weight:800;letter-spacing:.12em;margin-bottom:12px;}
.feature-title {font-size:16px;font-weight:750;margin-bottom:7px;color:var(--text-color);}
.feature-copy {font-size:12px;line-height:1.65;color:var(--qqqm-muted);}
div[data-testid="stButton"] button, div[data-testid="stPageLink"] a {border-radius:10px;font-weight:650;}
@media (prefers-color-scheme: dark) {.metric-value{color:#eef3ff;}}
</style>
""", unsafe_allow_html=True)


def read_market() -> tuple[pd.DataFrame, list[tuple], dict]:
    if not MARKET_DB.exists():
        return pd.DataFrame(), [], {}
    try:
        with sqlite3.connect(MARKET_DB) as conn:
            frame = pd.read_sql_query(
                "SELECT trade_date, close, adj_close, volume FROM market_daily WHERE UPPER(ticker)='QQQM' ORDER BY trade_date DESC LIMIT 90",
                conn,
            )
            news = conn.execute(
                "SELECT title, source_name, published_at, url FROM news_items WHERE COALESCE(published_at,'')<>'' ORDER BY published_at DESC LIMIT 4"
            ).fetchall()
            latest = conn.execute(
                "SELECT trade_date, source, fetched_at FROM market_daily WHERE UPPER(ticker)='QQQM' ORDER BY trade_date DESC LIMIT 1"
            ).fetchone()
        if not frame.empty:
            frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
            frame["price"] = pd.to_numeric(frame["adj_close"], errors="coerce").fillna(pd.to_numeric(frame["close"], errors="coerce"))
            frame = frame.dropna(subset=["trade_date", "price"]).sort_values("trade_date")
        meta = {"trade_date": latest[0], "source": latest[1], "fetched_at": latest[2]} if latest else {}
        return frame, news, meta
    except Exception:
        return pd.DataFrame(), [], {}


def read_portfolio(user_id: int | None) -> dict:
    empty = {"shares": 0.0, "avg_cost": 0.0, "realized": 0.0, "transactions": 0, "dividends": 0.0}
    if not user_id or not USERS_DB.exists():
        return empty
    try:
        with sqlite3.connect(USERS_DB) as conn:
            tx = conn.execute("""
                SELECT symbol, side, quantity, price, fees, realized_pnl, shares_after, average_cost_after
                FROM portfolio_transactions t
                WHERE user_id=? AND NOT EXISTS (
                    SELECT 1 FROM portfolio_transaction_voids v WHERE v.transaction_id=t.transaction_id
                ) ORDER BY executed_at_utc DESC, transaction_id DESC
            """, (user_id,)).fetchall()
            dividends = conn.execute("""
                SELECT COALESCE(SUM(net_amount),0) FROM portfolio_dividends d
                WHERE user_id=? AND NOT EXISTS (
                    SELECT 1 FROM portfolio_dividend_voids v WHERE v.dividend_id=d.dividend_id
                ) AND UPPER(symbol)='QQQM'
            """, (user_id,)).fetchone()[0]
        qqqm = [r for r in tx if str(r[0]).upper() == "QQQM"]
        if not qqqm:
            return empty
        latest = qqqm[0]
        return {
            "shares": float(latest[6] or 0), "avg_cost": float(latest[7] or 0),
            "realized": sum(float(r[5] or 0) for r in qqqm),
            "transactions": len(qqqm), "dividends": float(dividends or 0),
        }
    except Exception:
        return empty


def money(value: float) -> str:
    return f"${value:,.2f}"


principal = st.session_state.get(AUTH_KEY, {})
user_id = principal.get("user_id") if isinstance(principal, dict) else None
prices, news, market_meta = read_market()
portfolio = read_portfolio(user_id)
latest_date = prices["trade_date"].max().date() if not prices.empty else None
latest_price = float(prices.iloc[-1]["price"]) if not prices.empty else None
prev_price = float(prices.iloc[-2]["price"]) if len(prices) > 1 else None
change_pct = ((latest_price / prev_price) - 1) * 100 if latest_price and prev_price else None
age_days = (date.today() - latest_date).days if latest_date else None
market_value = portfolio["shares"] * latest_price if latest_price is not None else 0.0
cost_value = portfolio["shares"] * portfolio["avg_cost"]
unrealized = market_value - cost_value

st.markdown("""
<div class="qqqm-hero">
  <div class="qqqm-kicker">AI-POWERED INVESTMENT RESEARCH</div>
  <h1>QQQM 智能投资研究助手</h1>
  <p>把市场行情、宏观信息与个人交易记录放在同一条研究流程里。先看数据，再读解释，最后用真实结果检验预测。</p>
  <span class="qqqm-pill">QQQM AI Investment Research Assistant&nbsp;&nbsp;·&nbsp;&nbsp;Research, not trading</span>
</div>
""", unsafe_allow_html=True)

st.subheader("数据同步与研究流程")
st.caption("此操作会主动请求行情、新闻和宏观数据源，并结算已有预测；若行情日期更新或发现预测文件落后，还会生成新预测。打开网页本身不会偷偷发起 API 请求。")
update_col, status_col = st.columns([1, 2])
with update_col:
    if st.button("🔄 立即同步并更新预测", type="primary", use_container_width=True, key="home_run_full_update"):
        with st.spinner("正在同步公开行情、新闻/宏观数据并更新预测反馈……"):
            result = run_project_command(["-m", "app.daily_automation"], timeout=2400)
        st.session_state["home_daily_update_result"] = result
        st.rerun()
with status_col:
    st.caption(f"本地最新行情：{market_meta.get('trade_date', '未知')} · 来源：{market_meta.get('source', '未知')} · 记录更新时间：{market_meta.get('fetched_at', '未知')}")

update_result = st.session_state.get("home_daily_update_result")
if update_result:
    if update_result.get("returncode") == 0:
        st.success("完整更新流程返回成功。请核对上方最新行情日期和来源。")
    else:
        st.warning("本次更新存在失败步骤。已有本地数据会保留，具体失败原因见下方日志；不能把失败视作实时同步成功。")
    with st.expander("查看最近一次同步/预测工作流日志", expanded=update_result.get("returncode") != 0):
        if update_result.get("stdout"):
            st.code(update_result["stdout"][-12000:])
        if update_result.get("stderr"):
            st.code(update_result["stderr"][-6000:])
        st.caption("自动任务详细状态保存在 reports/automation/latest_status.json。")

source = str(market_meta.get("source") or "")
if latest_date is not None and age_days is not None:
    if source.startswith("public_snapshot_"):
        st.warning(
            f"本地行情截至 {latest_date:%Y-%m-%d}，收盘价是公开历史网页校验快照（来源：StockAnalysis），"
            "不是本次 API 实时同步。首次演示可使用该已核对历史数据；点击上方同步后，若供应商 API 成功，数据库会改为记录对应的 API 数据源。"
        )
        st.markdown("[打开原始公开历史行情来源](https://stockanalysis.com/etf/qqqm/history/)")
    elif age_days > 2:
        st.warning(f"行情数据提示：本地最新交易日为 {latest_date:%Y-%m-%d}，距今天 {age_days} 天。以下数据按最近可用记录展示，并非实时行情。请运行上方同步并核对日志。")
    else:
        st.caption(f"行情数据截至 {latest_date:%Y-%m-%d} · 数据源 {source or '未知'} · 价格为最近可用收盘参考价，不是实时成交价。")
else:
    st.error("暂时无法读取本地 QQQM 行情数据。请运行上方同步工作流并检查终端日志。")

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.markdown(f'<div class="metric-card"><div class="metric-label">最近可用收盘价</div><div class="metric-value">{money(latest_price) if latest_price is not None else "暂无数据"}</div><div class="metric-note">{latest_date.strftime("%Y-%m-%d") if latest_date else "请检查行情库"}</div></div>', unsafe_allow_html=True)
with m2:
    color = "#15803d" if (change_pct or 0) >= 0 else "#dc2626"
    change_text = f'{change_pct:+.2f}%' if change_pct is not None else "暂无数据"
    st.markdown(f'<div class="metric-card"><div class="metric-label">最近交易日涨跌</div><div class="metric-value" style="color:{color}">{change_text}</div><div class="metric-note">与上一条可用日线记录比较</div></div>', unsafe_allow_html=True)
with m3:
    st.markdown(f'<div class="metric-card"><div class="metric-label">QQQM 持仓市值估算</div><div class="metric-value">{money(market_value)}</div><div class="metric-note">{portfolio["shares"]:g} 股 × 最近可用收盘价</div></div>', unsafe_allow_html=True)
with m4:
    color = "#15803d" if unrealized >= 0 else "#dc2626"
    st.markdown(f'<div class="metric-card"><div class="metric-label">持仓浮动盈亏估算</div><div class="metric-value" style="color:{color}">{money(unrealized)}</div><div class="metric-note">按账本平均成本估算，不含额外税务影响</div></div>', unsafe_allow_html=True)

st.markdown('<div class="section-title">研究工作台</div><div class="section-sub">四个核心区域。旧实验工具已从主导航收起，避免演示时被大量菜单打断。</div>', unsafe_allow_html=True)
c1, c2, c3 = st.columns(3, gap="medium")
with c1:
    st.markdown('<div class="feature-card"><div class="feature-num">01 / MARKET</div><div class="feature-title">市场与持仓</div><div class="feature-copy">查看历史行情、个人交易账本、盈亏构成、宏观数据与新闻来源。</div></div>', unsafe_allow_html=True)
    st.page_link("app/dashboard.py", label="打开市场与持仓 →", icon="📊", use_container_width=True)
with c2:
    st.markdown('<div class="feature-card"><div class="feature-num">02 / FORECAST</div><div class="feature-title">下一交易日情景</div><div class="feature-copy">查看预测参考、历史价格与情景区间，区分模型估计和真实市场表现。</div></div>', unsafe_allow_html=True)
    st.page_link("app/pages/next_day_forecast.py", label="打开预测情景 →", icon="🔭", use_container_width=True)
with c3:
    st.markdown('<div class="feature-card"><div class="feature-num">03 / VALIDATION</div><div class="feature-title">预测评估与复盘</div><div class="feature-copy">跟踪已结算样本、误差指标、简单基准和历史预测记录。</div></div>', unsafe_allow_html=True)
    st.page_link("app/pages/model_learning_review.py", label="打开预测复盘 →", icon="🧠", use_container_width=True)

left, right = st.columns([1.6, 1], gap="large")
with left:
    st.markdown('<div class="section-title">QQQM 近期价格走势</div><div class="section-sub">最近 90 条本地日线记录；若数据过期，请先更新。</div>', unsafe_allow_html=True)
    if not prices.empty:
        chart = prices.set_index("trade_date")[["price"]].rename(columns={"price": "QQQM 收盘参考价"})
        st.line_chart(chart, height=270, use_container_width=True)
        start_price = float(prices.iloc[0]["price"])
        end_price = float(prices.iloc[-1]["price"])
        period_change = (end_price / start_price - 1) * 100 if start_price else 0
        st.caption(f"图表区间：{prices.iloc[0]['trade_date']:%Y-%m-%d} 至 {prices.iloc[-1]['trade_date']:%Y-%m-%d} · 区间变化 {period_change:+.2f}% · 不代表未来收益。")
    else:
        st.info("没有可用行情记录。")
with right:
    st.markdown('<div class="section-title">账本概况</div><div class="section-sub">只读取当前登录用户的本地账本。</div>', unsafe_allow_html=True)
    st.metric("当前持有股数", f"{portfolio['shares']:g} 股")
    st.metric("已实现盈亏累计", money(portfolio["realized"]))
    st.metric("股息净额累计", money(portfolio["dividends"]))
    st.caption(f"QQQM 交易流水 {portfolio['transactions']} 笔。持仓估值基于最近可用收盘价，不连接券商、不自动交易。")

st.markdown('<div class="section-title">最近收录的市场信息</div><div class="section-sub">以下为本地数据库中已保存的新闻，时间可能滞后；阅读前请检查发布日期。</div>', unsafe_allow_html=True)
if news:
    for title, source, published, url in news[:4]:
        published_day = None
        try:
            published_day = datetime.fromisoformat(str(published).replace("Z", "+00:00")).date()
        except (TypeError, ValueError):
            pass
        freshness = " · 较早信息，请核对原文" if published_day and (date.today() - published_day).days > 7 else ""
        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.caption(f"{source or '来源未标注'} · {published or '发布日期未知'}{freshness}")
            if url and str(url).startswith(("https://", "http://")):
                st.markdown(f"[查看原始来源]({url})")
else:
    st.info("暂无已保存新闻。可在市场分析页检查新闻数据源。")

st.divider()
st.caption("研究与学习用途，不构成投资建议。预测结果存在不确定性，历史表现不代表未来结果。本工具不会自动下单。")
