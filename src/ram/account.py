"""The book of sleeves (book.py) on a real T-Bank account, and the wealth around it.

- The account, week by week from the book's first decision: the book's weights held in whole lots of the picked shares
  (today's lot sizes on the panel's prices, which are on today's share count), the bond, index and money-market funds
  (their measured lag behind the index they follow), the trend's and the bonds' futures in whole contracts (today's
  contract value scaled back by the market's price), the account's fees and the half spread, 13% of the dividends at
  the source and of the year's realized result (losses carried forward), the tariff's monthly fee. Every rouble that is
  not in shares or the bond fund sits in the money-market fund; the futures' variation margin settles through it.
- The trend: `daily` - the bot trades the rule every day (the book's trend sleeve, plus the error of whole contracts
  against the rule's notional); `weekly` - the book's positions at the week's close, held for the week, by hand.
- The plan: what to buy today for the account's money, in lots and contracts, with the margin.
- The wealth: physical gold, cash currency and real-estate funds outside the account, valued today and moved by the
  book's scenarios next to the account.
"""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import date

import numpy as np

from . import book, events, sources, store, universe
from .assets import carry_rate, ffill_on
from .net import fetch_json
from .presets import PRESETS

FUTURES = ["CNYRUBF", "GLDRUBF", "IMOEXF", "RB"]  # the trend book's markets in book.MARKETS order
FUTURE_TITLES = ["юань (вечный)", "золото в рублях (вечный)", "индекс МосБиржи (вечный)", "ОФЗ, индекс RGBI (квартальный)"]
FUND_CHOICES = {"mmf": ("LQDT", "SBMM", "AKMM", "TMON"), "bond": ("SBGB", "TOFZ"), "index": ("SBMX", "TMOS", "EQMX")}
CORP_FUND = "SBRB"  # the corporate bonds' sleeve (RUCBTRNS) on the account
FUND_INDEX = {"mmf": "cash", "bond": "moex:index:RGBITR", "index": "moex:index:MCFTR", "corp": "moex:index:RUCBTRNS"}
DRAG_YEARS = 4  # the funds' lag behind their index: measured over the last years
ROLL_DAYS = 7  # the RB contract: the nearest with at least this many days left, as the bot rolls
FX_CODES = ("USD", "EUR", "CNY", "GBP", "CHF", "JPY", "HKD", "AED", "KZT", "TRY", "INR")
CAPITAL_PLANS = ("book", "now", "risk", "regime")  # = capital.PLANS
FUND_BETA_FALLBACK = (0.4, 0.2)  # a real-estate fund with less than half a year of prices: assumed betas (MCFTR, OFZ)
WEEKS = book.WEEKS
ISS_TQBR = ("https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json?iss.meta=off"
            "&iss.only=securities,marketdata&securities.columns=SECID,SHORTNAME,LOTSIZE,PREVPRICE"
            "&marketdata.columns=SECID,LAST,BID,OFFER,VALTODAY")
ISS_FORTS = ("https://iss.moex.com/iss/engines/futures/markets/forts/securities.json?iss.meta=off"
             "&iss.only=securities,marketdata&securities.columns=SECID,SHORTNAME,ASSETCODE,LASTTRADEDATE,MINSTEP,"
             "STEPPRICE,PREVSETTLEPRICE,INITIALMARGIN&marketdata.columns=SECID,LAST")


# ---------------------------------------------------------------------------- the settings


@dataclass
class Settings:
    """The account and the wealth outside it; saved in data/user/account.json (outside git)."""
    money: float = 200_000.0  # shares, bonds and the money-market fund
    futures_money: float = 100_000.0  # set aside for the futures (margin and variation margin)
    fee: float = 0.0005  # shares, bonds, funds: per side
    fee_fut: float = 0.00025  # futures: per side of the contract's value
    fee_month: float = 390.0  # the tariff's monthly fee
    tax: float = 0.13
    slip_stock: float = 0.0003  # half the spread of a picked share (today's picks: 0.002-0.11%, median 0.02%)
    slip_fut: float = 0.0001  # about one tick
    slip_fund: float = 0.0001  # half the spread of a liquid fund (LQDT, SBGB, SBMX: 0.002-0.02%)
    mmf: str = "LQDT"
    bond_fund: str = "SBGB"
    index_fund: str = "SBMX"
    bonds: str = "fund"  # fund | futures (RB over the money-market fund, netted with the trend's RB)
    trend_exec: str = "daily"  # daily (the bot) | weekly (by hand at the book's weekly decision)
    gold_grams: float = 0.0
    gold_haircut: float = 0.05  # a bank buys bars below the exchange price
    fx: dict[str, float] = field(default_factory=lambda: {"USD": 0.0, "EUR": 0.0, "CNY": 0.0})
    fx_haircut: float = 0.01
    funds: list[dict] = field(default_factory=list)  # real-estate funds: {"secid", "units", "payout"}
    capital_plan: str = "risk"  # the whole capital's plan (capital.PLANS) the account and the bot's plan follow

    @property
    def capital(self) -> float:
        return self.money + self.futures_money

    @staticmethod
    def from_dict(d: dict) -> Settings:
        known = {k: v for k, v in (d or {}).items() if k in Settings.__dataclass_fields__}
        s = Settings(**known)
        for k in ("money", "futures_money", "fee", "fee_fut", "fee_month", "tax", "slip_stock", "slip_fut", "slip_fund",
                  "gold_grams",
                  "gold_haircut", "fx_haircut"):
            setattr(s, k, float(getattr(s, k)))
        if not 10_000 <= s.money <= 1e10 or not 0 <= s.futures_money <= 1e10:
            raise ValueError("деньги счёта: от 10 000 ₽ на бумаги, на фьючерсы - от нуля")
        for k in ("fee", "fee_fut", "slip_stock", "slip_fut", "slip_fund"):
            if not 0 <= getattr(s, k) <= 0.02:
                raise ValueError("комиссии и спред - от 0 до 2% за сделку")
        if not 0 <= s.fee_month <= 100_000 or not 0 <= s.tax <= 0.3:
            raise ValueError("плата за тариф - от 0 до 100 000 ₽ в месяц, налог - от 0 до 30%")
        if s.capital_plan not in CAPITAL_PLANS:
            raise ValueError(f"план всего капитала: один из {', '.join(CAPITAL_PLANS)}")
        if s.bonds not in ("fund", "futures") or s.trend_exec not in ("daily", "weekly"):
            raise ValueError("облигации: fund | futures; тренд: daily | weekly")
        for k, choices in (("mmf", FUND_CHOICES["mmf"]), ("bond_fund", FUND_CHOICES["bond"]),
                           ("index_fund", FUND_CHOICES["index"])):
            if getattr(s, k) not in choices:
                raise ValueError(f"{k}: один из {', '.join(choices)}")
        if not 0 <= s.gold_grams <= 1e7 or not 0 <= s.gold_haircut < 0.5 or not 0 <= s.fx_haircut < 0.5:
            raise ValueError("золото - граммы от нуля, скидка при продаже - до 50%")
        fx = {}
        for code, amount in dict(s.fx or {}).items():
            code = str(code).strip().upper()
            if code not in FX_CODES:
                raise ValueError(f"валюта {code!r}: одна из {', '.join(FX_CODES)}")
            if not 0 <= float(amount) <= 1e9:
                raise ValueError("наличная валюта - сумма от нуля")
            fx[code] = float(amount)
        s.fx = fx
        funds = []
        for f in list(s.funds or []):
            code = str(f.get("secid", "")).strip().upper()
            if not re.fullmatch(r"[A-Z0-9]{4,14}", code):
                raise ValueError(f"код фонда {code!r}: тикер или ISIN, как на Мосбирже")
            units, payout = float(f.get("units") or 0), float(f.get("payout") or 0)
            if not 0 <= units <= 1e8 or not -0.5 <= payout <= 0.5:
                raise ValueError("паи - от нуля, выплаты - от −50% до 50% в год")
            funds.append({"secid": code, "units": units, "payout": payout})
        s.funds = funds
        return s

    def as_dict(self) -> dict:
        return {**asdict(self), "capital": self.capital}


def _path():
    return events._user_dir() / "account.json"


def load_settings() -> Settings:
    p = _path()
    try:
        return Settings.from_dict(json.loads(p.read_text())) if p.exists() else Settings()
    except (ValueError, TypeError):
        return Settings()


def save_settings(d: dict) -> Settings:
    s = Settings.from_dict(d)
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    blob = asdict(s)
    p.write_text(json.dumps(blob, ensure_ascii=False, indent=1))
    return s


# ---------------------------------------------------------------------------- today's market


def _rows(j: dict, block: str) -> dict[str, dict]:
    cols = j[block]["columns"]
    return {r[0]: dict(zip(cols, r)) for r in j[block]["data"]}


def share_specs() -> dict[str, dict]:
    """TQBR today (shares and funds): lot, price, bid/offer, the day's traded value. ISS, 12 h."""
    def fetch() -> dict:
        j = fetch_json(ISS_TQBR)
        sec, md = _rows(j, "securities"), _rows(j, "marketdata")
        out = {}
        for k, s in sec.items():
            m = md.get(k, {})
            price = m.get("LAST") or s.get("PREVPRICE")
            if not s.get("LOTSIZE") or not price:
                continue
            bid, offer = m.get("BID"), m.get("OFFER")
            out[k] = {"name": s.get("SHORTNAME") or k, "lot": int(s["LOTSIZE"]), "price": float(price),
                      "spread": float((offer - bid) / price) if bid and offer and offer >= bid else None,
                      "value": float(m.get("VALTODAY") or 0)}
        return out
    return store.cached_json("iss-tqbr-specs", fetch, 12)


def futures_specs() -> dict[str, dict]:
    """The four futures today: the contract's value in roubles, its initial margin, the code (RB: the nearest quarter
    with at least ROLL_DAYS left). ISS, 12 h."""
    def fetch() -> dict:
        j = fetch_json(ISS_FORTS)
        sec, md = _rows(j, "securities"), _rows(j, "marketdata")
        cutoff = date.fromordinal(date.today().toordinal() + ROLL_DAYS).isoformat()
        rb = sorted((s for s in sec.values() if s.get("ASSETCODE") == "RGBI" and (s.get("LASTTRADEDATE") or "") >= cutoff),
                    key=lambda s: s["LASTTRADEDATE"])
        out = {}
        for key in FUTURES:
            s = (rb[0] if rb else None) if key == "RB" else sec.get(key)
            if not s:
                continue
            price = (md.get(s["SECID"], {}).get("LAST") or s.get("PREVSETTLEPRICE"))
            value = float(price) * float(s["STEPPRICE"]) / float(s["MINSTEP"])
            out[key] = {"secid": s["SECID"], "name": s.get("SHORTNAME"), "price": float(price), "value": value,
                        "margin": float(s.get("INITIALMARGIN") or 0), "expiry": s.get("LASTTRADEDATE")}
        return out
    return store.cached_json("iss-forts-specs", fetch, 12)


_drags: dict[tuple, dict] = {}


def fund_drag(secid: str, kind: str) -> dict:
    """How much a fund lagged its index (RUONIA for the money market) a year over the last DRAG_YEARS years: the
    management fee, the cash it keeps, the tax inside. ISS closes against the index, both from the cache."""
    key = (secid, kind, date.today().isoformat())
    if key in _drags:
        return _drags[key]
    out = {"secid": secid, "index": FUND_INDEX[kind], "drag": 0.01, "years": 0.0, "from": None, "measured": False}
    try:
        end = date.today().toordinal()
        days = [date.fromordinal(end - 7 * k).isoformat() for k in range(int(DRAG_YEARS * 52.18), -1, -1)]
        f = sources.load(f"moex:shares:{secid}")
        vf = ffill_on(f.dates, f.values, days)
        if kind == "mmf":
            rate = carry_rate("rub", days, [])
            ords = np.array([date.fromisoformat(x).toordinal() for x in days])
            vi = np.r_[1.0, np.cumprod(1 + rate[:-1] * np.diff(ords) / 365)]
        else:
            ix = sources.load(FUND_INDEX[kind])
            vi = ffill_on(ix.dates, ix.values, days)
        ok = np.flatnonzero(np.isfinite(vf) & np.isfinite(vi))
        if len(ok) >= 26:
            a, b = ok[0], ok[-1]
            yrs = (date.fromisoformat(days[b]).toordinal() - date.fromisoformat(days[a]).toordinal()) / 365.25
            lag = (vi[b] / vi[a]) ** (1 / yrs) - (vf[b] / vf[a]) ** (1 / yrs)
            out.update(drag=float(lag), years=float(yrs), **{"from": days[a]}, measured=True)
    except Exception as e:  # noqa: BLE001 - the exchange did not answer: an assumed 1% a year
        out["error"] = str(e)
    _drags[key] = out
    return out


@dataclass
class Market:
    """What the account trades on the book's weeks."""
    col: dict[str, int]
    P: np.ndarray  # W x N share prices, carried over the weeks a share is off the board
    live: np.ndarray  # W x N on the board that week (can be traded)
    D: np.ndarray  # W x N dividends per share that left the price during the week
    lot: np.ndarray  # N today's lot sizes (1 for a share no longer on TQBR)
    V: np.ndarray  # W x 4 a futures contract's value in roubles
    margin: np.ndarray  # 4 the initial margin as a share of the contract's value, today
    specs: dict  # today's futures
    shares: dict  # today's TQBR


def _ffill(a: np.ndarray) -> np.ndarray:
    out = a.copy()
    for t in range(1, len(out)):
        m = np.isnan(out[t])
        out[t, m] = out[t - 1, m]
    return out


def market(d: book.Data) -> Market:
    p = universe.panel()
    specs, shares = futures_specs(), share_specs()
    lot = np.array([float(shares.get(tk, {}).get("lot", 1)) for tk in p.tickers])
    px = _ffill(d.fut_px)
    first = np.array([px[np.flatnonzero(np.isfinite(px[:, i]))[0], i] for i in range(4)])
    px = np.where(np.isnan(px), first[None, :], px)
    value = np.array([specs[k]["value"] for k in FUTURES])
    V = value[None, :] * px / px[-1][None, :]
    margin = np.array([specs[k]["margin"] / specs[k]["value"] for k in FUTURES])
    return Market(col={tk: j for j, tk in enumerate(p.tickers)}, P=_ffill(p.P), live=np.isfinite(p.P),
                  D=np.nan_to_num(p.D), lot=lot, V=V, margin=margin, specs=specs, shares=shares)


# ---------------------------------------------------------------------------- the account week by week


def trade_weeks(d: book.Data, o: book.Opts, res: dict) -> set[int]:
    """The weeks the book moved its weights (the month's decision, a cut, an adjustment), not just let them drift."""
    bk = book.assemble(d, o)
    t0, H = res["t0"], res["held"]
    out = {t0}
    for k in range(1, len(H)):
        r = np.nan_to_num(bk.R[t0 + k])
        drift = H[k - 1] * (1 + r)
        drift = drift / drift.sum()
        if np.abs(H[k] - drift).max() > 1e-9:
            out.add(t0 + k)
    return out


OWN_DRAG = {"secid": "свои выпуски", "index": "", "drag": 0.0, "years": 0.0, "from": None, "measured": True}


def drags(o: book.Opts, s: Settings) -> dict[str, dict]:
    bond = (OWN_DRAG if o.bonds == "own" else fund_drag(s.bond_fund, "bond") if o.bonds == "ofz"
            else fund_drag(CORP_FUND, "corp"))
    return {"mmf": fund_drag(s.mmf, "mmf"), "bond": bond,
            "index": fund_drag(s.index_fund, "index")}


def simulate(d: book.Data, o: book.Opts, mk: Market, s: Settings, capital: float, res: dict | None = None,
             dr: dict | None = None) -> dict:
    """The account at `capital` from the book's first decision to the panel's last week (see the module's notes)."""
    book.ensure(d, o)
    res = res or book.run(d, o)
    dr = dr or drags(o, s)
    t0, H = res["t0"], res["held"]
    own = o.bonds == "own"  # single issues: the coupon tax is withheld at each payment, no tax on selling a fund
    r_own_tax = d.returns["bonds:own:tax"] if own else None
    W = len(d.dates)
    traded = trade_weeks(d, o, res)
    stocks = o.equity != "mcftr"
    picks = d.picks.get(book.equity_key(o), {}) if stocks else {}
    forms = sorted(picks)
    sold: dict[int, list[str]] = {}
    if stocks and o.events:
        for x in (d.sales or {}).get(o.equity, []):
            sold.setdefault(x["week"], []).append(x["ticker"])
    bonds_fut = s.bonds == "futures" and o.bonds == "ofz"
    weekly = s.trend_exec == "weekly"
    pos, r_tr, r_cash = d.pos[o.trend], d.returns[f"trend:{o.trend}"], d.returns["cash"]
    r_bd, r_ix = d.returns[f"bonds:{o.bonds}"], d.returns.get("equity:mcftr", np.zeros(W))
    lag = {k: dr[k]["drag"] / WEEKS for k in ("mmf", "bond", "index")}
    rets = {"mmf": r_cash, "bond": r_bd, "index": r_ix}
    fee_s, fee_f, fee_x = s.fee + s.slip_stock, s.fee + s.slip_fund, s.fee_fut + s.slip_fut
    n = np.zeros(len(mk.col))
    avg = np.zeros(len(mk.col))
    funds = {"mmf": [0.0, 0.0], "bond": [0.0, 0.0], "index": [0.0, 0.0]}  # value, cost basis
    nf, F_prev, Fb_prev, capT = np.zeros(4), np.zeros(4), 0.0, 0.0
    cost = dict.fromkeys(("stocks", "funds", "futures", "fixed", "drag", "div_tax", "income_tax"), 0.0)
    acc = {"realized": 0.0, "carry": 0.0, "shadow": 0.0}  # shadow: the taxes paid, grown in the money-market fund
    nav, margin = np.full(W, np.nan), np.full(W, np.nan)
    devs, trades_n = [], 0

    def settle(flow: float) -> None:
        """The week's money into the money-market fund (or out of it)."""
        if abs(flow) < 1e-9:
            return
        c = abs(flow) * fee_f
        cost["funds"] += c
        acc["realized"] -= c
        v, b = funds["mmf"]
        if flow > 0:
            funds["mmf"] = [v + flow - c, b + flow - c]
        else:
            out = -flow + c
            frac = min(1.0, out / v) if v > 0 else 1.0
            if v > 0:
                acc["realized"] += (v - b) * frac
            funds["mmf"] = [v - out, b * (1 - frac)]  # below zero: the account borrows (a whole lot bought up)

    def fund_trade(k: str, amount: float) -> float:
        v, b = funds[k]
        if amount < 0:
            amount = -min(-amount, v)
            frac = -amount / v if v > 0 else 0.0
            if not (own and k == "bond"):  # own bonds: their coupons were taxed when paid
                acc["realized"] += (v - b) * frac
            funds[k] = [v + amount, b * (1 - frac)]
        else:
            funds[k] = [v + amount, b + amount]
        c = abs(amount) * fee_f
        cost["funds"] += c
        acc["realized"] -= c
        return -amount - c

    def trade_to(t: int, j: int, want: float) -> float:
        nonlocal trades_n
        q = want - n[j]
        if abs(q) < 1e-9 or not mk.live[t, j]:
            return 0.0
        price = mk.P[t, j]
        val = q * price
        c = abs(val) * fee_s
        if q < 0:
            acc["realized"] += (price - avg[j]) * (-q)
        else:
            avg[j] = (avg[j] * n[j] + val) / (n[j] + q)
        n[j] = want
        cost["stocks"] += c
        acc["realized"] -= c
        trades_n += 1
        return -val - c

    for t in range(t0, W):
        flow = 0.0
        if t == t0:
            settle(capital)
        else:
            if d.dates[t][:4] != d.dates[t - 1][:4]:  # the year's tax, paid in the first week of the next one
                net = acc["realized"] - acc["carry"]
                if net > 0:
                    flow -= s.tax * net
                    cost["income_tax"] += s.tax * net
                    acc["shadow"] += s.tax * net
                    acc["carry"] = 0.0
                else:
                    acc["carry"] = -net
                acc["realized"] = 0.0
            acc["shadow"] *= 1 + float(np.nan_to_num(r_cash[t])) - lag["mmf"]
            div = float(n @ mk.D[t])
            flow += div * (1 - s.tax)
            cost["div_tax"] += div * s.tax
            acc["shadow"] += div * s.tax
            for k, hv in funds.items():
                v = hv[0]
                if v:
                    hv[0] = v * (1 + float(np.nan_to_num(rets[k][t])) - lag[k])
                    cost["drag"] += v * lag[k]
                    if own and k == "bond":  # the broker withholds 13% of each coupon: out of the money
                        withheld = v * float(np.nan_to_num(rets[k][t]) - np.nan_to_num(r_own_tax[t]))
                        flow -= withheld
                        cost["income_tax"] += withheld
                        acc["shadow"] += withheld
            xr = np.nan_to_num(d.fut_xr[t])
            if weekly:
                pnl = float((nf * mk.V[t - 1]) @ xr)
            else:
                pnl = capT * float(np.nan_to_num(r_tr[t]) - np.nan_to_num(r_cash[t])) + Fb_prev * xr[3] \
                    + float((nf * mk.V[t - 1] - F_prev) @ xr)
            flow += pnl
            acc["realized"] += pnl
            months = (int(d.dates[t][:4]) * 12 + int(d.dates[t][5:7])) - (int(d.dates[t - 1][:4]) * 12 + int(d.dates[t - 1][5:7]))
            if months > 0:
                flow -= s.fee_month * months
                cost["fixed"] += s.fee_month * months
                acc["realized"] -= s.fee_month * months
            settle(flow)
            flow = 0.0
        px = mk.P[t]
        held = n > 0
        sv = float(n[held] @ px[held])
        NAV = sv + sum(v for v, _ in funds.values())
        h = H[t - t0]
        for tk in sold.get(t, []):  # an exchange event: sold at the week's close, as the sleeve does
            j = mk.col.get(tk)
            if j is not None and n[j] > 0:
                flow += trade_to(t, j, 0.0)
        if stocks:
            prior = [f for f in forms if f <= t]
            if t in picks or (t == t0 and prior):
                names = picks.get(t) or picks[prior[-1]]
                cols = [mk.col[tk] for tk in names if tk in mk.col and mk.live[t, mk.col[tk]]]
                each = h[0] * NAV / max(len(cols), 1)
                dev = 0.0
                for j in cols:
                    want = round(each / (mk.lot[j] * px[j])) * mk.lot[j]
                    dev += abs(want * px[j] - each)
                    flow += trade_to(t, j, want)
                for j in np.flatnonzero(n > 0):
                    if j not in cols:
                        flow += trade_to(t, j, 0.0)
                if cols and h[0] > 0:
                    devs.append(dev / (h[0] * NAV))
            elif t in traded and sv > 0:
                scale = h[0] * NAV / sv
                for j in np.flatnonzero(n > 0):
                    flow += trade_to(t, j, round(n[j] * scale / mk.lot[j]) * mk.lot[j])
        elif t in traded:
            flow += fund_trade("index", h[0] * NAV - funds["index"][0])
        if not bonds_fut and t in traded:
            flow += fund_trade("bond", h[1] * NAV - funds["bond"][0])
        capT = h[2] * NAV
        target = np.nan_to_num(pos[t]) * capT
        Fb = h[1] * NAV if bonds_fut else 0.0
        target[3] += Fb
        new = np.round(target / mk.V[t])
        c = fee_x * (float(np.abs(new - nf) @ mk.V[t]) if weekly else abs(Fb - Fb_prev))
        cost["futures"] += c
        acc["realized"] -= c
        flow -= c
        nf, F_prev, Fb_prev = new, target, Fb
        margin[t] = float(np.abs(nf) @ (mk.V[t] * mk.margin))
        settle(flow)
        held = n > 0
        nav[t] = float(n[held] @ px[held]) + sum(v for v, _ in funds.values())
    unreal = float(((mk.P[-1] - avg) * n)[n > 0].sum()) + sum(v - b for k, (v, b) in funds.items()
                                                                 if not (own and k == "bond"))
    final_tax = s.tax * max(0.0, acc["realized"] + unreal - acc["carry"])
    v = nav[t0:]
    x = v[1:] / v[:-1] - 1
    years = len(x) / WEEKS
    mean_nav = float(np.mean(v))
    ideal = np.asarray(res["x"])
    ok = np.isfinite(ideal)
    after = v[-1] - final_tax
    dd = 1 - v / np.maximum.accumulate(v)
    return {
        "capital": capital, "t0": t0, "x": x, "nav": v, "years": years,
        "cagr": float(((v[-1] + acc["shadow"]) / capital) ** (1 / years) - 1),
        "paid_tax_cagr": float((v[-1] / capital) ** (1 / years) - 1),
        "after_tax_cagr": float((max(after, 1.0) / capital) ** (1 / years) - 1),
        "ideal_cagr": float(np.prod(1 + ideal[ok]) ** (1 / years) - 1),
        "vol": float(x.std() * math.sqrt(WEEKS)), "dd": float(dd.max()),
        "tracking": float(np.std(x[ok] - ideal[ok]) * math.sqrt(WEEKS)),
        "costs": {k: float(c / (mean_nav * years)) for k, c in cost.items()},
        "final_tax": float(final_tax / v[-1]), "end": float(v[-1]), "end_after_tax": float(after),
        "rounding": float(np.mean(devs)) if devs else 0.0,
        "margin_mean": float(np.nanmean(margin[t0:] / nav[t0:])), "margin_max": float(np.nanmax(margin[t0:] / nav[t0:])),
        "mmf_min": float(min(0.0, funds["mmf"][0])), "trades_year": trades_n / years,
    }


def money_only(d: book.Data, t0: int, s: Settings, capital: float, drag: float) -> dict:
    """The whole account in the money-market fund from the same week: bought once, the tax when it is sold."""
    r = np.nan_to_num(d.returns["cash"][t0 + 1:])
    v = capital * (1 - s.fee - s.slip_fund) * np.r_[1.0, np.cumprod(1 + r - drag / WEEKS)]
    x = v[1:] / v[:-1] - 1
    years = len(x) / WEEKS
    after = v[-1] - s.tax * max(0.0, v[-1] - capital)
    cagr = float((v[-1] / capital) ** (1 / years) - 1)
    return {"capital": capital, "x": x, "nav": v, "years": years, "cagr": cagr,
            "after_tax_cagr": float((after / capital) ** (1 / years) - 1),
            "ldv_cagr": cagr if years >= 3 else None,  # units held over 3 years: the long-holding exemption
            "vol": float(x.std() * math.sqrt(WEEKS)),
            "dd": float((1 - v / np.maximum.accumulate(v)).max()), "end": float(v[-1]), "end_after_tax": float(after)}


# ---------------------------------------------------------------------------- the plan for today


def on_account(cap: dict | None, C: float) -> dict[str, float]:
    """Roubles of the exchange gold and the currency bonds the account holds for the whole capital's plan: the plan's
    share of the whole capital (the broker capital C and the wealth outside it) less what the bars and the cash already
    hold; at most the account's money."""
    if not cap:
        return {"gold": 0.0, "fx": 0.0}
    out_ = cap.get("outside", {})
    total = C + sum(out_.values())
    want = {c: max(0.0, cap["shares"].get(c, 0.0) * total - out_.get(c, 0.0)) for c in ("gold", "fx")}
    s = sum(want.values())
    return {c: v * min(1.0, C / s) for c, v in want.items()} if s > 0 else want


def capital_rows(cap: dict, amounts: dict[str, float]) -> list[dict]:
    """The exchange gold and the currency bonds for `amounts` (roubles of each class), in whole grams and bonds; the
    price of a currency bond in roubles at the Bank of Russia's rate (its clean price and accrued interest are in the
    face's currency)."""
    out = []
    for r in cap["rows"]:
        cls = "gold" if r["kind"] == "gold" else "fx"
        target = amounts[cls] * r["weight"]
        rate = cap["rates"].get(r.get("currency", "RUB"), 1.0)
        unit = (r["price"] + r.get("accint", 0.0)) * rate
        lots = int(np.round(target / (unit * r["lot"]))) if unit > 0 else 0
        out.append({**r, "lots": lots, "units": lots * r["lot"], "value": lots * r["lot"] * unit, "target": target,
                    "spread": None, "price_rub": unit})
    return out


def plan(d: book.Data, o: book.Opts, mk: Market, s: Settings, res: dict, cap: dict | None = None) -> dict:
    """What to hold today for the account's money: the picks in lots, the funds in units, the futures in contracts;
    with the whole capital's plan (`cap`, capital.plan_section) the exchange gold and the currency bonds first and the
    book on the rest."""
    acc = on_account(cap, s.capital)
    C = s.capital - sum(acc.values())  # the book's capital
    t = len(d.dates) - 1
    h = res["held"][-1]
    rows: list[dict] = []
    names: list[str] = []
    if o.equity != "mcftr":
        picks = d.picks.get(book.equity_key(o), {})
        form = max((k for k in picks if k <= t), default=None)
        out = {x["ticker"] for x in (d.sales or {}).get(o.equity, []) if form is not None and x["week"] > form} \
            if o.events else set()
        names = [tk for tk in (picks.get(form, []) if form is not None else []) if tk not in out]
        each = h[0] * C / max(len(names), 1)
        for tk in names:
            sp = mk.shares.get(tk) or {"lot": int(mk.lot[mk.col[tk]]), "price": float(mk.P[t, mk.col[tk]]), "spread": None}
            lot_rub = sp["lot"] * sp["price"]
            lots = int(np.round(each / lot_rub))
            rows.append({"kind": "share", "code": tk, "name": d.names.get(tk, tk), "lot": sp["lot"], "price": sp["price"],
                         "lots": lots, "units": lots * sp["lot"], "value": lots * lot_rub, "target": each,
                         "spread": sp.get("spread")})
    else:
        rows.append(_fund_row(mk, s.index_fund, "index", h[0] * C))
    if o.bonds == "own":
        rows.extend(_bond_rows(d, h[1] * C))
    elif s.bonds == "fund" or o.bonds != "ofz":
        rows.append(_fund_row(mk, s.bond_fund if o.bonds == "ofz" else CORP_FUND, "bond", h[1] * C))
    capT = h[2] * C
    target = np.nan_to_num(d.pos[o.trend][t]) * capT
    trend_part = target.copy()
    if s.bonds == "futures" and o.bonds == "ofz":
        target[3] += h[1] * C
    fut = []
    for i, key in enumerate(FUTURES):
        sp = mk.specs[key]
        k = int(np.round(target[i] / sp["value"]))
        fut.append({"kind": "future", "code": sp["secid"], "market": FUTURE_TITLES[i], "contracts": k,
                    "notional": k * sp["value"], "target": float(target[i]), "trend": float(trend_part[i]),
                    "value": sp["value"], "margin": abs(k) * sp["margin"], "margin_one": sp["margin"]})
    if cap:
        rows.extend(capital_rows(cap, acc))
    spent = sum(r["value"] for r in rows)
    mmf = _fund_row(mk, s.mmf, "mmf", s.capital - spent)
    rows.append(mmf)
    status = {}
    checked = names + [r["code"] for r in rows if r["kind"] in ("bond_issue", "fx_bond")]
    if checked:
        try:
            status = events.check(checked)
        except Exception:  # noqa: BLE001 - the exchange's news did not load
            status = {}
    for r in rows:
        if r["kind"] in ("share", "bond_issue", "fx_bond"):
            st = status.get(r["code"], {})
            r["status"] = st.get("status", "ok")
            r["events"] = st.get("events", [])[:2]
    margin = sum(f["margin"] for f in fut)
    stocks_value = sum(r["value"] for r in rows if r["kind"] in ("share", "bond_issue", "fx_bond", "gold"))  # an exchange spread
    devs = [abs(r["value"] - r["target"]) for r in rows if r["kind"] == "share"]
    pol = d.bond_policy if o.bonds == "own" else None
    return {"date": d.dates[t], "weights": h.tolist(), "capital": C, "account": s.capital, "on_account": acc,
            "capital_plan": {k: cap[k] for k in ("plan", "title", "shares", "outside")} if cap else None,
            "rows": rows, "futures": fut,
            "bond_policy": {k: pol[k] for k in ("regime", "title", "since", "key", "mix")} if pol else None,
            "margin": margin, "futures_money": s.futures_money, "margin_share": margin / C,
            "entry_cost": (s.fee + s.slip_stock) * stocks_value + (s.fee + s.slip_fund) * sum(
                r["value"] for r in rows if r["kind"] not in ("share", "bond_issue", "fx_bond", "gold"))
            + (s.fee_fut + s.slip_fut) * sum(abs(f["notional"]) for f in fut),
            "rounding": sum(devs) / max(h[0] * C, 1.0) if devs else 0.0,
            "off": sum(1 for r in rows if r["kind"] == "share" and r["target"] and abs(r["value"] / r["target"] - 1) > 0.25)}


def _bond_rows(d: book.Data, amount: float) -> list[dict]:
    """The own bonds' issues for `amount`: whole bonds (a lot is one bond) at the clean price plus the accrued
    interest paid at a purchase."""
    from . import bonds
    pol = d.bond_policy or {}
    out = []
    for b in bonds.plan_issues(pol.get("mix", {}), without_exits(pol.get("today", {}))):
        clean = b["price"] / 100 * b["face"]
        dirty = clean + b["accint"]
        target = amount * b["weight"]
        lots = int(np.round(target / dirty)) if dirty > 0 else 0
        out.append({"kind": "bond_issue", "code": b["secid"], "name": b["name"], "lot": 1, "price": clean,
                    "accint": b["accint"], "face": b["face"], "price_pct": b["price"], "bond_kind": b["kind"],
                    "ytm": b["ytm"], "duration": b["duration"], "lots": lots, "units": lots, "value": lots * dirty,
                    "target": target, "spread": None})
    return out


def without_exits(today: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Today's issues of every kind less those an exchange event takes out (a default, a bankruptcy, the defaulted
    bonds' sector, a delisting - of the issue or of its issuer, events.py): the plan picks the next ones instead."""
    codes = sorted({b["secid"] for items in today.values() for b in items})
    if not codes:
        return today
    try:
        st = events.check(codes)
    except Exception:  # noqa: BLE001 - the exchange's news did not load: the issues as they are
        return today
    return {k: [b for b in items if st.get(b["secid"], {}).get("status") != "exclude"] for k, items in today.items()}


def _fund_row(mk: Market, code: str, kind: str, amount: float) -> dict:
    sp = mk.shares.get(code) or {"lot": 1, "price": 1.0, "name": code}
    units = max(0, int(amount // (sp["lot"] * sp["price"]))) * sp["lot"]
    title = {"mmf": "денежный рынок", "bond": "облигации", "index": "индекс МосБиржи"}[kind]
    return {"kind": kind, "code": code, "name": f"{sp.get('name') or code} ({title})", "lot": sp["lot"],
            "price": sp["price"], "lots": units // sp["lot"], "units": units, "value": units * sp["price"],
            "target": max(amount, 0.0), "spread": sp.get("spread")}


# ---------------------------------------------------------------------------- the wealth around the account


def fund_stats(d: book.Data, secid: str) -> dict:
    """A real-estate fund's exchange price on the book's weeks: growth, swings, the worst fall, the betas to MCFTR and
    to the OFZ (Dimson's sum over this and the last week: a thin price follows the market late)."""
    s = sources.load(f"moex:shares:{secid}")
    v = ffill_on(s.dates, s.values, d.dates)
    ok = np.flatnonzero(np.isfinite(v))
    out = {"secid": secid, "name": s.name, "price": float(s.values[-1]), "last": s.dates[-1], "first": s.dates[0],
           "weeks": len(ok)}
    if len(ok) < 8:
        return {**out, "beta_eq": FUND_BETA_FALLBACK[0], "beta_bd": FUND_BETA_FALLBACK[1], "assumed": True}
    a = ok[0]
    x = v[a + 1:] / v[a:-1] - 1
    years = len(x) / WEEKS
    eq = v[a:] / v[a]
    out.update(price_cagr=float(eq[-1] ** (1 / years) - 1), vol=float(np.std(x) * math.sqrt(WEEKS)),
               dd=float((1 - eq / np.maximum.accumulate(eq)).max()))
    if len(x) < 26:
        return {**out, "beta_eq": FUND_BETA_FALLBACK[0], "beta_bd": FUND_BETA_FALLBACK[1], "assumed": True}
    me, mb = np.nan_to_num(d.returns["equity:mcftr"][a + 1:]), np.nan_to_num(d.returns["bonds:ofz"][a + 1:])
    X = np.column_stack([np.ones(len(x) - 1), me[1:], me[:-1], mb[1:], mb[:-1]])
    c, *_ = np.linalg.lstsq(X, x[1:], rcond=None)
    return {**out, "beta_eq": float(c[1] + c[2]), "beta_bd": float(c[3] + c[4]), "assumed": False}


def wealth(d: book.Data, s: Settings, account_value: float, scen_rows: list[dict]) -> dict:
    items: list[dict] = [{"kind": "account", "label": "счёт: портфель из блоков", "value": account_value,
                          "sale": account_value}]
    notes: list[str] = []
    gold_v = fx_v = 0.0
    if s.gold_grams > 0:
        g = sources.load("moex:currency:GLDRUB_TOM")
        gold_v = s.gold_grams * float(g.values[-1])
        items.append({"kind": "gold", "label": "физическое золото", "value": gold_v, "sale": gold_v * (1 - s.gold_haircut),
                      "detail": f"{s.gold_grams:g} г по {float(g.values[-1]):,.0f} ₽ (Мосбиржа, {g.dates[-1]})"})
    for code, amount in s.fx.items():
        if amount > 0:
            c = sources.load(f"cbr:{code}")
            rate = float(c.values[-1])
            v = amount * rate
            fx_v += v
            items.append({"kind": "fx", "label": f"наличные {code}", "value": v, "sale": v * (1 - s.fx_haircut),
                          "detail": f"{amount:,.0f} {code} по курсу ЦБ {rate:,.4f} ({c.dates[-1]})"})
    funds = []
    for f in s.funds:
        try:
            st = fund_stats(d, f["secid"])
        except Exception as e:  # noqa: BLE001 - not on the exchange
            notes.append(f"{f['secid']}: цена не загрузилась ({e})")
            continue
        v = f["units"] * st["price"]
        st.update(units=f["units"], payout=f["payout"], value=v,
                  total=(st["price_cagr"] + f["payout"]) if "price_cagr" in st else None)
        funds.append(st)
        items.append({"kind": "fund", "label": st["name"], "value": v, "sale": v, "code": f["secid"],
                      "detail": f"{f['units']:g} паёв по {st['price']:,.0f} ₽ ({st['last']})"})
    total = sum(i["value"] for i in items)
    for i in items:
        i["share"] = i["value"] / total if total else 0.0
    scen = []
    for r in scen_rows:
        m = r["moves"]
        acc = -r["loss"] * account_value
        gold = gold_v * m[1]
        fx = fx_v * m[0]
        fu = sum(f["value"] * (f["beta_eq"] * m[2] + f["beta_bd"] * m[3]) for f in funds)
        tot = acc + gold + fx + fu
        scen.append({"label": r["label"], "kind": r["kind"], "to": r.get("to"), "account": acc, "gold": gold, "fx": fx,
                     "funds": fu, "total": tot, "share": tot / total if total else 0.0,
                     "account_share": -r["loss"], "moves": m})
    if fx_v:
        notes.append("наличная валюта в сценариях движется как юань (единственная валюта счёта бота): в девальвации "
                     "рубля доллар, евро и юань дорожали вместе, но в 2022 году наличные доллары и евро продавали с "
                     "большим спредом")
    if funds:
        notes.append("фонды недвижимости в сценариях: бета цены пая к MCFTR и ОФЗ на недельной истории; биржевая цена "
                     "пая редкая и сглаженная (оценка объектов раз в полгода), поэтому колебания и бета занижены")
    return {"items": items, "total": total, "scenarios": scen, "funds": funds, "notes": notes,
            "cushion": gold_v + fx_v, "cushion_share": (gold_v + fx_v) / total if total else 0.0}


# ---------------------------------------------------------------------------- the report


VARIANTS_CAPITAL = (1_000_000.0, 3_000_000.0)


def report(req: dict) -> dict:
    t_start = time.time()
    o = book.Opts.from_dict(req.get("opts") or {})
    s = Settings.from_dict({**asdict(load_settings()), **(req.get("settings") or {})})
    d = book.data(o.cost)
    if d.fut_px is None:
        raise ValueError("данные блоков собраны старой версией: перезапустите сервер")
    mk = market(d)
    res = book.run(d, o, log=True)
    dr = drags(o, s)
    live = simulate(d, o, mk, s, s.capital, res, dr)
    rows = [_row("ideal", "портфель из блоков без лотов, налогов и твоих комиссий (как на странице блоков)",
                 _ideal(res, live), "ideal")]
    rows.append(_row("live", "твой счёт: целые лоты и контракты, комиссии, налоги", live, "live"))
    alt = []
    if o.bonds == "ofz":
        other = "futures" if s.bonds == "fund" else "fund"
        alt.append(("bonds_" + other, "облигации — фьючерсом RB поверх денег (взаимозачёт с трендом)" if other == "futures"
                    else "облигации — фондом " + s.bond_fund, o, replace(s, bonds=other), s.capital))
    other = "weekly" if s.trend_exec == "daily" else "daily"
    alt.append(("trend_" + other, "тренд руками раз в неделю (позиции на конец недели)" if other == "weekly"
                else "тренд ботом каждый день", o, replace(s, trend_exec=other), s.capital))
    if o.equity != "mcftr":
        alt.append(("index", f"акции — индексный фонд {s.index_fund} вместо отбора", replace(o, equity="mcftr"), s, s.capital))
    if 0 < o.limit < 0.4:
        alt.append(("limit40", "сценарный предел 40% вместо " + f"{o.limit:.0%}", replace(o, limit=0.4), s, s.capital))
    if o.limit > 0:
        alt.append(("no_cap", "без сценарного предела", replace(o, limit=0.0), s, s.capital))
    for C in VARIANTS_CAPITAL:
        if C > s.capital * 1.2:
            alt.append((f"cap{int(C)}", f"те же настройки на {C / 1e6:g} млн ₽", o, s, C))
    curves = {"ideal": np.asarray(res["x"]), "live": live["x"]}
    for key, title, vo, vs, C in alt:
        vres = res if vo == o else book.run(d, vo)
        sim = simulate(d, vo, mk, vs, C, vres, drags(vo, vs))
        rows.append(_row(key, title, sim, "alt"))
    money = money_only(d, res["t0"], s, s.capital, dr["mmf"]["drag"])
    rows.append(_row("money", f"всё в фонде денежного рынка {s.mmf}", money, "money"))
    curves["money"] = money["x"]
    days = res["days"]
    idx = book.thin_idx(len(days))
    series = {"dates": [days[i] for i in idx]}
    for k, x in curves.items():
        eq = np.cumprod(1 + np.nan_to_num(x))
        series[k] = [float(eq[i]) for i in idx]
    today = book.today_section(d, o, res)
    pl = plan(d, o, mk, s, res, _capital(d, o, res, s))
    w = wealth(d, s, s.capital, today["scenarios"])
    return {
        "meta": {"opts": o.as_dict(), "from": d.dates[res["t0"]], "to": d.dates[-1], "years": live["years"],
                 "drags": dr, "specs_date": date.today().isoformat(), "unknown_lots": int(sum(
                     1 for tk in mk.col if tk not in mk.shares)), "notes": _notes(s, live, pl)},
        "settings": s.as_dict(), "rows": rows, "live": {k: v for k, v in live.items() if k not in ("x", "nav")},
        "series": series, "plan": pl, "wealth": w, "elapsed": time.time() - t_start,
    }


PLAN_VERSION = 3  # 2: own bonds as issues (kind "bond_issue"); 3: the whole capital ("capital": gold, currency bonds)
SLEEVE_KEYS = ("equity", "bonds", "trend", "cash")


def export(req: dict) -> dict:
    """The plan for the trading bot (trade-t-bot reads the file, compares it with the broker account and shows the
    orders in the app): today's weights of the book as shares of the book's capital - every picked share, the bond,
    index and money-market funds, the futures' notionals - with today's lot sizes and prices; and (version 3) the whole
    capital's plan: its shares, the wealth outside the broker accounts, the exchange gold and the currency bonds. The
    bot works out the book's capital (the broker capital less the gold and the currency bonds the account holds for the
    whole capital) and the lots from the account's real value, so the plan does not depend on the capital set here."""
    from datetime import UTC, datetime

    from .study import clean

    o = book.Opts.from_dict(req.get("opts") or {})
    s = Settings.from_dict({**asdict(load_settings()), **(req.get("settings") or {})})
    d = book.data(o.cost)
    if d.fut_px is None:
        raise ValueError("данные блоков собраны старой версией: перезапустите расчёт")
    mk = market(d)
    res = book.run(d, o, log=True)
    cap = _capital(d, o, res, s)
    pl = plan(d, o, mk, s, res, cap)
    today = book.today_section(d, o, res)
    C = pl["capital"]
    rows = []
    for r in pl["rows"]:
        if r["kind"] in ("mmf", "gold", "fx_bond"):
            continue
        row = {"kind": r["kind"], "code": r["code"], "name": r["name"], "weight": r["target"] / C if C > 0 else 0.0,
               "lot": r["lot"], "price": r["price"], "status": r.get("status", "ok"), "events": r.get("events", [])}
        if r["kind"] == "bond_issue":
            row.update({k: r[k] for k in ("accint", "face", "price_pct", "bond_kind", "ytm", "duration")})
        rows.append(row)
    held = sum(r["weight"] for r in rows)
    mmf = next(r for r in pl["rows"] if r["kind"] == "mmf")
    rows.append({"kind": "mmf", "code": mmf["code"], "name": mmf["name"], "weight": max(0.0, 1 - held), "lot": mmf["lot"],
                 "price": mmf["price"], "status": "ok", "events": []})
    futures = [{"code": f["code"], "market": f["market"], "weight": f["target"] / C, "trend_weight": f["trend"] / C,
                "value": f["value"], "margin_one": f["margin_one"]} for f in pl["futures"]]
    h = res["held"][-1]
    return clean({
        "version": PLAN_VERSION, "made": datetime.now(UTC).isoformat(timespec="seconds"), "date": d.dates[-1],
        "decided": today["decided"], "picked": today["picked"], "opts": o.as_dict(),
        "funds": {"mmf": s.mmf, "bond": s.bond_fund, "index": s.index_fund},
        "bonds_mode": "own" if o.bonds == "own" else s.bonds,
        "bond_policy": ({k: d.bond_policy[k] for k in ("regime", "title", "since", "key", "mix")}
                        if o.bonds == "own" and d.bond_policy else None),
        "weights": dict(zip(SLEEVE_KEYS, (float(x) for x in h))),
        "trend": {"weight": float(h[2]), "risk": float(next(x for x in PRESETS if x["key"] == o.trend)["params"]["risk"]),
                  "rule": o.trend},
        "rows": rows, "futures": futures,
        "worst": [{"label": x["label"], "loss": x["loss"]} for x in today["scenarios"][:3]], "limit": o.limit,
        "capital": _capital_export(cap, pl),
    })


def _capital(d: book.Data, o: book.Opts, res: dict, s: Settings) -> dict | None:
    from . import capital
    try:
        return capital.plan_section(d, o, res, s)
    except Exception as e:  # noqa: BLE001 - gold, the rates or the bonds did not load: the book alone, said so
        d.notes.append(f"план всего капитала не посчитался ({e}): только портфель из блоков")
        return None


def _capital_export(cap: dict | None, pl: dict) -> dict | None:
    """The whole capital's part of the plan (version 3): the plan's shares of the whole capital, the wealth outside the
    broker accounts in roubles, the rates, and the exchange gold and currency bonds - their weights are shares of their
    class's amount on the account, which the bot works out from the account's real value."""
    if not cap:
        return None
    status = {r["code"]: r for r in pl["rows"] if r["kind"] in ("gold", "fx_bond")}
    rows = [{**r, "status": status.get(r["code"], {}).get("status", "ok"), "events": status.get(r["code"], {}).get("events", [])}
            for r in cap["rows"]]
    return {**{k: cap[k] for k in ("plan", "title", "shares", "outside", "rates", "regime")}, "rows": rows}


def write_export(path, req: dict | None = None) -> dict:
    """export() into `path` atomically (the bot may read it at any moment)."""
    from pathlib import Path

    out = export(req or {})
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(target)
    return out


def _ideal(res: dict, live: dict) -> dict:
    x = np.nan_to_num(np.asarray(res["x"]))
    eq = np.cumprod(1 + x)
    years = len(x) / WEEKS
    return {"cagr": float(eq[-1] ** (1 / years) - 1), "after_tax_cagr": None, "vol": float(x.std() * math.sqrt(WEEKS)),
            "dd": float((1 - eq / np.maximum.accumulate(eq)).max()), "capital": live["capital"], "years": years}


def _row(key: str, title: str, sim: dict, kind: str) -> dict:
    out = {"key": key, "title": title, "kind": kind}
    for k in ("capital", "cagr", "paid_tax_cagr", "after_tax_cagr", "ldv_cagr", "ideal_cagr", "vol", "dd", "tracking", "costs", "rounding",
              "margin_mean", "margin_max", "trades_year", "final_tax", "end", "end_after_tax"):
        if k in sim:
            out[k] = sim[k]
    return out


def _notes(s: Settings, live: dict, pl: dict) -> list[str]:
    out = []
    if live["mmf_min"] < -0.02 * s.capital:
        out.append("денег на счёте иногда не хватало: целые лоты докупались в долг (до "
                   f"{-live['mmf_min']:,.0f} ₽) - на живом счёте брокер возьмёт за это процент")
    if pl["margin"] > s.futures_money:
        out.append(f"ГО фьючерсов сегодня {pl['margin']:,.0f} ₽ - больше отведённых {s.futures_money:,.0f} ₽")
    return out
