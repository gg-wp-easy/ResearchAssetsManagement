"""Exchange events (events.py): parsing the exchange's decisions, issuer-wide reach, point-in-time exits, and the
portfolio's exit in a study and in the book's equity sleeve. The texts are shortened copies of real MOEX news."""
from datetime import date, timedelta

import numpy as np

from ram import events

BANKRUPT = ("В соответствии с Правилами листинга ПАО Московская Биржа Председателем Правления 16.11.2026 приняты следующие "
            "решения: 1. Исключить с торгового дня 30.12.2026 : 1. 1 . Наименование эмитента/организации Публичное "
            "акционерное общество \"ЕвроТранс\" Наименование ценной бумаги Биржевые облигации серии БО-001Р-03 "
            "Идентификационный/Регистрационный номер выпуска 4B02-03-80110-H-001P от 29.03.2023 Торговый код RU000A1061K1 "
            "ISIN код RU000A1061K1 Раздел Списка Третий уровень Основание принятия решения Введение в отношении "
            "организации процедуры, применяемой в деле о банкротстве (наблюдение) 1. 2 . Наименование эмитента/организации "
            "Публичное акционерное общество \"ЕвроТранс\" Наименование ценной бумаги акции обыкновенные "
            "Идентификационный/Регистрационный номер выпуска 1-01-80110-H Торговый код EUTR ISIN код RU000A1002V2 "
            "Основание принятия решения Введение в отношении организации процедуры, применяемой в деле о банкротстве "
            "(наблюдение) 1. 3 . Наименование эмитента/организации Публичное акционерное общество \"ЕвроТранс\" "
            "Наименование ценной бумаги облигации серии БО-001Р-08 Торговый код RU000A10CZB9 ISIN к")
REDEEMED = ("Председателем Правления 26.11.2026 приняты следующие решения: исключить 26.11.2026 : Наименование "
            "эмитента/организации публичное акционерное общество \"Нефтяная компания \"Роснефть\" Наименование ценной "
            "бумаги биржевые облигации серии 001P-01 Торговый код RU000A0JX132 ISIN код RU000A0JX132 Раздел Списка Первый "
            "уровень Основание принятия решения Погашение выпуска ценных бумаг Контактная информация для СМИ")
DEFAULTED = ("Участникам торгов Извещаем Вас, что ... в связи с допущенным ПАО \"ЕвроТранс\" дефолтом установлено, что с 06 "
             "августа 2026 года для ценных бумаг ПАО \"ЕвроТранс\": № п/п Торговый код Наименование 1 RU000A1061K1 "
             "Облигация биржевая БО-001Р-03 ПАО \"ЕвроТранс\" 2 RU000A1082G5 Облигация ... \"Облигации Д\"")
BUYOUT = ("приостановить торги ценными бумагами с торгового дня 20.10.2026 в отношении следующих ценных бумаг: "
          "Наименование эмитента/организации Публичное акционерное общество \"ПИК-специализированный застройщик\" "
          "Наименование ценной бумаги Акции обыкновенные Торговый код PIKK ISIN код RU000A0JP7J7 Раздел Списка Первый "
          "уровень Основание принятия решения Наступление иных существенных событий (поступившее организации требование "
          "о выкупе эмиссионных ценных бумаг) В торговый день, следующий за выходными")
AUCTION = ("LSRG ЛСР ао По состоянию на 11:58:00 текущая цена составила 842.6 руб. (Отклонение – 27.47 %). Произошло "
           "повышение на 20.00 % и более в течение 5 минут подряд")


def test_bankruptcy_items_and_the_cut_item():
    evs = events.parse(106080, "Об исключении ценных бумаг из Списка ценных бумаг, допущенных к торгам", "2026-11-16 10:59:17",
                       BANKRUPT)
    assert len(evs) == 1  # both full items of one issuer and kind merge; the cut third item (no reason) is skipped
    e = evs[0]
    assert e.kind == "bankruptcy" and e.level == "exclude" and e.scope == "issuer"
    assert set(e.codes) == {"RU000A1061K1", "EUTR", "RU000A1002V2"} and "RU000A10CZB9" not in e.codes
    assert e.issuer_key == "евротранс" and e.effective == "2026-12-30" and e.date == "2026-11-16"


def test_redemption_is_benign():
    assert events.parse(1, "О внесении изменений в Список ценных бумаг, допущенных к торгам", "2026-11-26 17:56:15",
                        REDEEMED) == []


def test_default_regime_and_buyout_and_auction():
    d = events.parse(2, "Дополнительные условия проведения торгов отдельными облигациями ПАО \"ЕвроТранс\" с 06 августа 2026 года",
                     "2026-08-05 18:55:59", DEFAULTED)
    assert [x.kind for x in d] == ["default"] and d[0].scope == "issuer"
    assert d[0].codes == ["RU000A1061K1", "RU000A1082G5"] and d[0].issuer_key == "евротранс"
    b = events.parse(3, "О приостановке торгов ценными бумагами", "2026-10-13 18:00:00", BUYOUT)
    assert [x.kind for x in b] == ["buyout"] and b[0].codes == ["PIKK", "RU000A0JP7J7"] and b[0].level == "exclude"
    a = events.parse(4, "По ценным бумагам LSRG проводится дискретный аукцион", "2026-10-28 11:58:00", AUCTION)
    assert a[0].kind == "jump" and a[0].level == "warn" and a[0].codes == ["LSRG"] and a[0].detail.startswith("+27,47%")


def test_issuer_key():
    assert events.issuer_key('Публичное акционерное общество "Группа ЛСР"') == "группа лср"
    assert events.issuer_key('ПАО "ЕвроТранс"') == events.issuer_key('Публичное акционерное общество "ЕвроТранс"')
    assert events.core_name('публичное акционерное общество "Нефтяная компания "Роснефть"') == "Роснефть"


def ev(kind: str, day: str, codes: list[str], issuer: str = "", eid: int = 9) -> events.Event:
    _, level, scope = events.KINDS[kind]
    return events.Event(id=eid, date=day, kind=kind, level=level, scope=scope, title="t", issuer=issuer,
                        issuer_key=events.issuer_key(issuer), codes=codes)


def test_exits_reach_the_issuers_shares_and_are_point_in_time(monkeypatch):
    monkeypatch.setattr(events, "issuer_securities", lambda name, save=True: [
        {"secid": "EUTR", "type": "common_share"}, {"secid": "RU000A1061K1", "type": "exchange_bond"}])
    ex = events.exits([ev("default", "2026-08-05", ["RU000A1061K1"], 'ПАО "ЕвроТранс"'),
                       ev("jump", "2026-10-28", ["LSRG"])])
    assert set(ex) == {"EUTR", "RU000A1061K1"}  # the bond's default takes the shares out; a warning takes nothing
    spans = ex["EUTR"]
    assert events.excluded(spans, "2026-08-05") is None  # the news day itself: still held
    assert events.excluded(spans, "2026-08-06").kind == "default"
    later = (date(2026, 8, 5) + timedelta(days=events.EXCLUDE_DAYS + 1)).isoformat()
    assert events.excluded(spans, later) is None


def test_check_matches_code_and_issuer(monkeypatch):
    info = {"EUTR": {"secid": "EUTR", "isin": "RU000A1002V2", "issuer": 'ПАО "ЕвроТранс"', "issuer_key": "евротранс",
                     "is_traded": 1, "shortname": "ЕвроТранс"},
            "SBER": {"secid": "SBER", "isin": "RU0009029540", "issuer": 'ПАО "Сбербанк России"',
                     "issuer_key": "сбербанк россии", "is_traded": 1, "shortname": "Сбербанк"},
            "OLD": {"secid": "OLD", "isin": "", "issuer": "", "issuer_key": "", "is_traded": 0, "shortname": ""}}
    monkeypatch.setattr(events, "security", lambda code, save=True: info[code])
    monkeypatch.setattr(events, "prefetch", lambda codes: None)
    evs = [ev("default", "2026-08-05", ["RU000A1061K1"], 'ПАО "ЕвроТранс"'), ev("crash", "2026-11-09", ["EUTR"])]
    r = events.check(["EUTR", "SBER", "OLD"], evs, today="2026-11-26")
    assert r["EUTR"]["status"] == "exclude" and [e["kind"] for e in r["EUTR"]["events"]] == ["default", "crash"]
    assert r["SBER"]["status"] == "ok"
    assert r["OLD"]["status"] == "exclude" and r["OLD"]["events"][0]["kind"] == "not_traded"


def test_study_exit_sells_the_next_day_and_spreads_the_weight(monkeypatch):
    from ram import study
    from ram.assets import AssetSpec, Basket
    from ram.rule import Params, portfolio_weights
    T = 10
    dates = [(date(2026, 8, 3) + timedelta(days=i)).isoformat() for i in range(T)]
    specs = [AssetSpec(id="moex:shares:EUTR", weight=0.5), AssetSpec(id="moex:shares:SBER", weight=0.5)]
    b = Basket(specs=specs, labels=["ЕвроТранс", "Сбербанк"], names=["", ""], dates=dates, E=np.ones((T, 2)),
               R=np.zeros((T, 2)), P=np.ones((T, 2)), alive=np.ones((T, 2), bool), ppy=252)
    e = ev("default", "2026-08-05", ["EUTR"], 'ПАО "ЕвроТранс"')
    monkeypatch.setattr(events, "all_events", lambda refresh=True: ([e], {"from": "2024-11-13"}))
    monkeypatch.setattr(events, "check", lambda codes, evs=None, today=None: {
        c: {"status": "exclude" if c == "EUTR" else "ok", "issuer": "", "events": []} for c in codes})
    monkeypatch.setattr(events, "exits", lambda evs=None, shares_only=True: {"EUTR": [("2026-08-05", "2028-08-04", e)]})
    out = study.apply_events(b, "exit")
    k = dates.index("2026-08-06")  # the first trading day after the news: held through its close
    assert out["assets"][0]["sold"] == "2026-08-06" and out["masked"]
    assert b.alive[:k + 1, 0].all() and not b.alive[k + 1:, 0].any() and b.alive[:, 1].all()
    w = portfolio_weights(b, Params(signal="weights"))
    assert w[k, 0] == 0.5 and w[k + 1, 1] == 1.0  # its weight goes to the rest
