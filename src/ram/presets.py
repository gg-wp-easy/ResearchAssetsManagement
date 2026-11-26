"""Ready baskets. The first two are the trade bot's main book as its research ran it (analogues of the perpetual futures
CNYRUBF, GLDRUBF, IMOEXF and of RB, 2006-2026), and the paper account main_guard with both protections."""
from __future__ import annotations

MAIN_BOOK = [
    {"id": "cbr:CNY", "label": "юань", "carry": "rub", "carry_offset": -0.025, "go": 0.08, "cbr": True},
    {"id": "yahoo:GLD", "label": "золото в рублях", "rub": True, "carry": "rub", "go": 0.10},
    {"id": "moex:index:MCFTR", "label": "индекс МосБиржи", "carry": "rub", "go": 0.10, "cbr": True},
    {"id": "moex:index:RGBITR", "label": "ОФЗ", "carry": "rub", "go": 0.118, "cbr": True},
]


def _usd(ids: list[tuple[str, str]], **extra) -> list[dict]:
    return [{"id": i, "label": label, **extra} for i, label in ids]


PRESETS = [
    {
        "key": "main",
        "title": "Основной счёт бота",
        "description": "Юань, золото в рублях, индекс МосБиржи и ОФЗ с 2006 года: аналоги вечных фьючерсов CNYRUBF, "
                       "GLDRUBF, IMOEXF и RB, как в исследовании бота (risk 10%, окно 20, стоп 25%).",
        "assets": MAIN_BOOK,
        "params": {"risk": 0.10, "lookbacks": [20]},
        "control": 1,
        "history_from": "2004-12-01",
    },
    {
        "key": "main_guard",
        "title": "Основной с защитой",
        "description": "Те же инструменты, шорт юаня и золота не больше половины полного размера и плавный контроль "
                       "просадки с 10% до 35% вместо стопа (бумажный счёт main_guard).",
        "assets": [{**a, "short_cap": 0.5} if a["id"] in ("cbr:CNY", "yahoo:GLD") else a for a in MAIN_BOOK],
        "params": {"risk": 0.10, "lookbacks": [20]},
        "control": 7,
        "history_from": "2004-12-01",
    },
    {
        "key": "metals",
        "title": "Металлы FORTS",
        "description": "Золото, серебро, платина и палладий: склейки фьючерсов Мосбиржи с поправкой на смену контракта "
                       "(котировки в долларах, фьючерс уже содержит стоимость удержания).",
        "assets": [{"id": f"moex:cont:{c}", "label": label, "go": 0.10}
                   for c, label in (("GOLD", "золото"), ("SILV", "серебро"), ("PLT", "платина"), ("PLD", "палладий"))],
        "params": {"risk": 0.10, "lookbacks": [20]},
    },
    {
        "key": "energy",
        "title": "Энергоносители",
        "description": "Brent (склейка FORTS с 2008) и фонды США на нефть WTI и газ: фонды платят реальную стоимость "
                       "перекладки контрактов.",
        "assets": [{"id": "moex:cont:BR", "label": "нефть Brent", "go": 0.15},
                   {"id": "yahoo:USO", "label": "нефть WTI (фонд)", "go": 0.15},
                   {"id": "yahoo:UNG", "label": "газ США (фонд)", "go": 0.20}],
        "params": {"risk": 0.10, "lookbacks": [20]},
    },
    {
        "key": "softs",
        "title": "Агро",
        "description": "Сахар FORTS и фонды Teucrium на сахар, пшеницу, кукурузу и сою (с 2011).",
        "assets": [{"id": "moex:cont:SUGR", "label": "сахар FORTS", "go": 0.10},
                   {"id": "yahoo:CANE", "label": "сахар (фонд)", "go": 0.10},
                   {"id": "yahoo:WEAT", "label": "пшеница (фонд)", "go": 0.10},
                   {"id": "yahoo:CORN", "label": "кукуруза (фонд)", "go": 0.10},
                   {"id": "yahoo:SOYB", "label": "соя (фонд)", "go": 0.10}],
        "params": {"risk": 0.10, "lookbacks": [20]},
    },
    {
        "key": "forts_macro",
        "title": "Фьючерсы Мосбиржи",
        "description": "Доллар/рубль, индекс РТС, Brent, золото и серебро: длинные склейки FORTS (с 2008).",
        "assets": [{"id": f"moex:cont:{c}", "label": label, "go": go}
                   for c, label, go in (("Si", "доллар/рубль", 0.08), ("RTS", "индекс РТС", 0.15), ("BR", "нефть Brent", 0.15),
                                        ("GOLD", "золото", 0.10), ("SILV", "серебро", 0.12))],
        "params": {"risk": 0.10, "lookbacks": [20]},
    },
    {
        "key": "world",
        "title": "Мировой портфель",
        "description": "Акции США, развитых и развивающихся стран, длинные трежерис, золото и сырьё через фонды "
                       "(с дивидендами, лонг платит ставку T-bill): каркас распределения капитала Анга.",
        "assets": _usd([("yahoo:SPY", "S&P 500"), ("yahoo:EFA", "развитые рынки"), ("yahoo:EEM", "развивающиеся"),
                        ("yahoo:TLT", "трежерис 20+"), ("yahoo:GLD", "золото"), ("yahoo:DBC", "сырьё")], go=0.10),
        "params": {"risk": 0.10, "lookbacks": [60]},
    },
    {
        "key": "us_indices",
        "title": "Индексы США",
        "description": "S&P 500, Nasdaq 100, Russell 2000, Dow Jones через фонды с дивидендами.",
        "assets": _usd([("yahoo:SPY", "S&P 500"), ("yahoo:QQQ", "Nasdaq 100"), ("yahoo:IWM", "Russell 2000"),
                        ("yahoo:DIA", "Dow Jones")], go=0.10),
        "params": {"risk": 0.10, "lookbacks": [120]},
    },
    {
        "key": "foreign_stocks",
        "title": "Иностранные акции бота",
        "description": "Базовые акции 14 ликвидных фьючерсов FORTS (счёт foreign_stocks): окно 120, риск 5% на акцию.",
        "assets": _usd([("yahoo:NBIS", "Nebius"), ("yahoo:AMD", "AMD"), ("yahoo:BABA", "Alibaba"),
                        ("yahoo:SNDK", "SanDisk"), ("yahoo:MSTR", "Strategy"), ("yahoo:TSLA", "Tesla"),
                        ("yahoo:AMZN", "Amazon"), ("yahoo:000660.KS", "SK Hynix"), ("yahoo:COHR", "Coherent"),
                        ("yahoo:1810.HK", "Xiaomi"), ("yahoo:LITE", "Lumentum"), ("yahoo:INTC", "Intel"),
                        ("yahoo:CRWD", "CrowdStrike"), ("yahoo:CRWV", "CoreWeave")], go=0.20),
        "params": {"risk": 0.05, "lookbacks": [120]},
        "period": "full",
    },
    {
        "key": "moex_shares",
        "title": "Акции Мосбиржи",
        "description": "Крупнейшие акции ISS (ценовая доходность: ISS не отдаёт дивиденды; поправка ставки −8% "
                       "приближённо учитывает их).",
        "assets": [{"id": f"moex:shares:{t}", "label": label, "carry": "rub", "carry_offset": -0.08, "go": 0.20}
                   for t, label in (("SBER", "Сбербанк"), ("GAZP", "Газпром"), ("LKOH", "Лукойл"),
                                    ("GMKN", "Норникель"), ("NVTK", "Новатэк"), ("ROSN", "Роснефть"),
                                    ("TATN", "Татнефть"), ("MGNT", "Магнит"), ("PLZL", "Полюс"), ("MTSS", "МТС"))],
        "params": {"risk": 0.10, "lookbacks": [20]},
    },
    {
        "key": "ruble",
        "title": "Рубль против валют",
        "description": "Доллар, евро и юань к рублю по курсу ЦБ; лонг доллара платит RUONIA минус ставку T-bill, "
                       "евро и юаня - RUONIA минус постоянную поправку.",
        "assets": [{"id": "cbr:USD", "label": "доллар", "carry": "rub-usd", "go": 0.08, "cbr": True},
                   {"id": "cbr:EUR", "label": "евро", "carry": "rub", "carry_offset": -0.015, "go": 0.08, "cbr": True},
                   {"id": "cbr:CNY", "label": "юань", "carry": "rub", "carry_offset": -0.025, "go": 0.08, "cbr": True}],
        "params": {"risk": 0.10, "lookbacks": [20]},
    },
    {
        "key": "crypto",
        "title": "Криптовалюты",
        "description": "Bitcoin, Ethereum, Solana (выходные складываются в понедельник).",
        "assets": _usd([("yahoo:BTC-USD", "Bitcoin"), ("yahoo:ETH-USD", "Ethereum"), ("yahoo:SOL-USD", "Solana")],
                       go=0.25),
        "params": {"risk": 0.10, "lookbacks": [20, 60]},
        "period": "full",
    },
]
