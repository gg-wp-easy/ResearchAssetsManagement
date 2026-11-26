import { useMemo, type ReactNode } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";

function Tex({ children, block = false }: { children: string; block?: boolean }) {
  const html = useMemo(() => katex.renderToString(children, { displayMode: block, throwOnError: false, strict: "ignore", output: "htmlAndMathml" }), [children, block]);
  return block ? <div className="tex-block" dangerouslySetInnerHTML={{ __html: html }} /> : <span dangerouslySetInnerHTML={{ __html: html }} />;
}

interface Sec { id: string; title: string; lead: ReactNode; formulas: string[]; where: [string, ReactNode][]; book?: ReactNode; site: string;
  bookLabel?: string }

const SECTIONS: Sec[] = [
  {
    id: "s1", title: "Доходность, волатильность, Шарп", site: "Обзор, Правило",
    lead: <>Всё считается в доходностях сверх стоимости удержания: что зарабатывает лонг, профинансированный по ставке. Волатильность — экспоненциальное среднее, в котором свежие дни весят больше.</>,
    formulas: [String.raw`r_t = \frac{E_t}{E_{t-1}} - 1, \qquad E_t = E_{t-1}\left(1 + \frac{P_t}{P_{t-1}} - 1 - c_{t-1}\frac{\Delta d}{365}\right)`,
      String.raw`\sigma_t^2 = (1-\lambda)\,\sigma_{t-1}^2 + \lambda\, r_t^2, \qquad \lambda = \frac{2}{N+1}, \qquad \sigma_{\text{год}} = \sigma_{\text{день}}\sqrt{252}`,
      String.raw`\mathrm{SR} = \frac{\bar r}{s}\,\sqrt{252}`],
    where: [["c", "ставка, которую платит лонг: RUONIA, ставка T-bill, их разница или ничего (фьючерс уже содержит её)"],
      ["Δd", "календарных дней между закрытиями: выходные оплачиваются"], ["N", "окно EWMA: 60 дней и быстрое 20; размер берётся от большей оценки"]],
    book: <>Основной счёт бота 2006–2026 при риске 10%: +17,1% в год, волатильность 16,3%, Шарп 1,05 (на данных бота; с курсом ЦБ вместо Yahoo — около 1,18).</>,
  },
  {
    id: "s2", title: "Размер позиции и сила тренда", site: "Правило, Сценарии",
    lead: <>Полная позиция выбирается так, чтобы её годовая волатильность была долей τ капитала. Сила тренда z — во сколько сигм ушла цена за L дней; позиция равна clip(z) от полной.</>,
    formulas: [String.raw`N = \frac{\tau\, C}{\sigma_{\text{год}}}, \qquad z_L = \frac{\ln(E_t/E_{t-L})}{\sigma_{\text{день}}\sqrt{L}}`,
      String.raw`w = \operatorname{clip}\!\Big(\tfrac{1}{|\mathcal L|}\textstyle\sum_{L} \operatorname{clip}(z_L,-1,1),\; -k,\; 1\Big)`,
      String.raw`\text{сделка, если } |wN - x| > \tfrac14 N \text{ или знак другой}, \qquad \sum_i |x_i|\, m_i \le 0{,}5\, C`],
    where: [["τ, C", "риск на актив и капитал"], ["k", "предел шорта: 1 — без ограничения, 0,5 — половина, 0 — только лонг"],
      ["m_i", "гарантийное обеспечение (ГО) на единицу номинала"], ["𝓛", "окна тренда; несколько — среднее их сил"]],
    book: <>Спокойный инструмент получает большую позицию: ОФЗ с волатильностью 5% при риске 10% — два капитала номинала. Поэтому важен предел ГО и сценарии гэпа.</>,
  },
  {
    id: "s3", title: "Толстые хвосты", site: "Хвосты",
    lead: <>У нормального распределения движение в 6 сигм — раз в миллионы лет. У рыночных цен хвост убывает как степень. Насколько он толстый, говорит индекс хвоста ξ.</>,
    formulas: [String.raw`P(X > x) \sim C\,x^{-1/\xi}, \qquad \mathbb{E}\,|X|^k < \infty \iff k < \frac{1}{\xi}`,
      String.raw`\hat\xi_{\text{Хилл}} = \frac{1}{k}\sum_{i=1}^{k}\ln X_{(i)} - \ln X_{(k+1)}`],
    where: [["ξ", "0 — как у нормального по форме; 0,25 и больше — нет четвёртого момента; 0,5 и больше — нет дисперсии"],
      ["X₍ᵢ₎", "убытки по убыванию; k — сколько худших взять (смотрите на устойчивый участок графика Хилла)"],
      ["Стьюдент", "с ν степенями свободы имеет ξ = 1/ν"]],
    book: <>У юаня и золота в рублях хвост роста толще хвоста падения (ξ 0,39 и 0,36 против 0,20 и 0,19): девальвация приходит гэпом, шорт юаня — короткая позиция на обвал рубля.</>,
  },
  {
    id: "s4", title: "Теория экстремальных значений", site: "Хвосты",
    lead: <>По теореме Пикандса — Балкемы — де Хаана превышения над высоким порогом u почти у любого распределения описываются обобщённым распределением Парето. Хвост оценивают отдельно от центра: берут 5% худших дней и экстраполируют.</>,
    formulas: [String.raw`G_{\xi,\beta}(y) = 1 - \left(1 + \frac{\xi y}{\beta}\right)^{-1/\xi}, \qquad y = X - u > 0`,
      String.raw`\mathrm{VaR}_q = u + \frac{\beta}{\xi}\left[\left(\frac{1-q}{p_u}\right)^{-\xi} - 1\right], \qquad \mathrm{ES}_q = \frac{\mathrm{VaR}_q + \beta - \xi u}{1-\xi}, \qquad q_N = 1 - \frac{1}{252\,N}`],
    where: [["p_u", "доля дней с убытком выше порога (5%)"], ["β", "масштаб превышений; ξ и β — максимальным правдоподобием"], ["q_N", "убыток, превышаемый раз в N лет"]],
    book: <>Книга бота почти нормальная (ξ = 0,10 для дней): размер по волатильности и сам тренд срезают хвосты. День раз в 20 лет — −5,8% против −3,6% у нормального.</>,
  },
  {
    id: "s5", title: "VaR, ES и оптимизация", site: "Хвосты, Распределение",
    lead: <>VaR — граница хвоста, ES (CVaR) — средний убыток за ней. ES субаддитивна, это когерентная мера риска. Портфель с минимальным ES находится линейным программированием по сценариям.</>,
    formulas: [String.raw`\mathrm{ES}_\alpha(L) = \mathbb{E}\big[L \mid L \ge \mathrm{VaR}_\alpha\big], \qquad \mathrm{ES}(L_1 + L_2) \le \mathrm{ES}(L_1) + \mathrm{ES}(L_2)`,
      String.raw`\min_{w,\,\zeta,\,u}\; \zeta + \frac{1}{(1-\alpha)S}\sum_{s=1}^{S} u_s \quad\text{при}\quad u_s \ge -w^{\top} r_s - \zeta,\;\; u_s \ge 0`],
    where: [["r_s", "доходности активов в сценарии s (недели окна оценки)"], ["ζ", "в оптимуме равна VaR (Rockafellar, Uryasev, 2000)"]],
  },
  {
    id: "s6", title: "Стресс-сценарии", site: "Кризисы, Сценарии",
    lead: <>Вероятность чёрного лебедя оценить нельзя, но можно перечислить сценарии и потребовать, чтобы ни один не убил счёт. Смотрят на два набора позиций: те, что держит правило, и самый неудачный знак каждой.</>,
    formulas: [String.raw`\Delta V_s = \sum_i w_i N_i\, r_{i,s}, \qquad \Delta V_s^{\text{худш}} = -\sum_i N_i\,|r_{i,s}|, \qquad \frac{\Delta V_s}{\rho}`,
      String.raw`\max_{w}\ \mu^{\top} w \quad\text{при}\quad \Delta V_s(w) \ge -L_{\max}\quad \forall\, s \in \mathcal{S}`],
    where: [["ρ", "доля суммы для торговли, лежащая деньгами на брокерском счёте"], ["𝒮", "список сценариев; ограничения линейны по w — робастная оптимизация"]],
    book: <>Неделя 24.02.2022 на позициях правила — −34% суммы (−67% денег на счёте), худший знак −59%. «Санкции и девальвация, биржа закрыта» — −62% суммы. Дефолт как в 1998 обнуляет счёт при любом риске.</>,
  },
  {
    id: "s7", title: "Режимы экономики", site: "Режимы",
    lead: <>Скрытая марковская модель (Hamilton, 1989): экономика переключается между состояниями, доходности в каждом свои. Фильтр каждый день пересчитывает вероятность режима. У Анга это «плохие времена»: премию платят за готовность их пережить.</>,
    formulas: [String.raw`P(s_t = j \mid s_{t-1} = i) = p_{ij}, \qquad r_t \mid s_t = k \sim \mathcal{N}(\mu_k, \sigma_k^2)`,
      String.raw`\hat\xi_{t\mid t} = \frac{\hat\xi_{t\mid t-1} \odot \eta_t}{\mathbf{1}^{\top}(\hat\xi_{t\mid t-1} \odot \eta_t)}, \qquad \hat\xi_{t+1\mid t} = P^{\top}\hat\xi_{t\mid t}, \qquad \mathbb{E}[\text{длительность}] = \frac{1}{1 - p_{kk}}`],
    where: [["ξ̂", "вероятности режимов (здесь вектор, а не индекс хвоста)"], ["η_t", "плотность сегодняшней доходности в каждом режиме"]],
    book: <>Кризисов в данных 3–5: параметры кризисного режима оцениваются по горстке точек. Режим — множитель риска, а не сигнал направления.</>,
  },
  {
    id: "s8", title: "Критерий Келли", site: "Келли и Шарп",
    lead: <>Келли максимизирует ожидаемый логарифм капитала. Штраф за разброс растёт квадратично: при доле вдвое больше Келли рост падает до нуля.</>,
    formulas: [String.raw`g(f) = \mu f - \tfrac12\sigma^2 f^2, \qquad f^* = \frac{\mu}{\sigma^2}, \qquad g^* = \tfrac12\mathrm{SR}^2, \qquad \frac{g(c f^*)}{g^*} = 2c - c^2`,
      String.raw`\mathbb{E}\, g(c\hat f) = \mathrm{SR}^2\Big(c - \frac{c^2}{2}\Big) - \frac{c^2}{2T}, \qquad c^* = \frac{T\,\mathrm{SR}^2}{T\,\mathrm{SR}^2 + 1}`],
    where: [["c", "доля Келли: половина даёт 3/4 роста при половине волатильности"], ["T", "лет данных, по которым оценено μ"]],
    book: <>Книга бота держит около 1/6 Келли и получает 29% максимального роста при 16% его волатильности.</>,
  },
  {
    id: "s9", title: "Контроль просадки", site: "Просадка",
    lead: <>Гроссман и Чжоу (1993): если запрещено падать ниже доли α от пика, в риске держат величину, пропорциональную запасу над полом. На практике — множитель размера, падающий с просадкой, с нижней границей.</>,
    formulas: [String.raw`\mathrm{DD}_t = 1 - \frac{W_t}{M_t}, \qquad m_t^{\text{ГЧ}} = \frac{D_{\max} - \mathrm{DD}_t}{D_{\max}(1 - \mathrm{DD}_t)}`,
      String.raw`m_t = \begin{cases} 1, & \mathrm{DD}_t \le a \\ \max\!\left(m_{\min},\ 1 - \dfrac{\mathrm{DD}_t - a}{b - a}\right), & \mathrm{DD}_t > a \end{cases}`],
    where: [["W_t, M_t", "капитал и его пик"], ["a, b", "с какой просадки резать и где выйти на пол m_min"]],
    book: <>21 год, риск 10%: стоп 25% увеличил просадку с 27,5% до 34,8% (фиксирует убыток и пропускает восстановление). «С 10% линейно до 35%» стоит 0,5–0,9% в год и снижает вероятность просадки 25% за три года с 17% до 7%.</>,
  },
  {
    id: "s10", title: "Сколько ждать вывода", site: "Келли и Шарп",
    lead: <>Оценка Шарпа шумная, разница двух стратегий — ещё шумнее. Если перебрать много вариантов, лучший выглядит хорошо просто от удачи.</>,
    formulas: [String.raw`\mathrm{SE}(\widehat{\mathrm{SR}}) \approx \sqrt{\frac{1 + \mathrm{SR}^2/2}{T}}, \qquad \mathrm{SE}(\widehat{\mathrm{SR}}_1 - \widehat{\mathrm{SR}}_2) \approx \sqrt{\frac{2(1-\rho)}{T}}, \qquad T_{t=2} = \frac{8(1-\rho)}{\Delta\mathrm{SR}^2}`,
      String.raw`\mathbb{E}\Big[\max_{k \le K}\widehat{\mathrm{SR}}_k\Big] \approx \mathrm{SE}\cdot\Big((1-\gamma)\,\Phi^{-1}\big(1 - \tfrac1K\big) + \gamma\,\Phi^{-1}\big(1 - \tfrac{1}{K e}\big)\Big)`],
    where: [["ρ", "корреляция доходностей двух стратегий"], ["K", "сколько вариантов перебрали; γ — постоянная Эйлера (Bailey, López de Prado, 2014)"]],
    book: <>«Основной с защитой» против основного: ρ = 0,93, ΔSR = 0,17 — для t = 2 нужно 19 лет. Бумага проверит механику, решение о защите опирается на хвосты и просадки.</>,
  },
  {
    id: "s11", title: "Полная доходность акции", site: "любая акция Мосбиржи, Факторы акций",
    lead: <>ISS отдаёт цены как были: в день сплита GMKN «падает» на 99%. Цены приводятся к сегодняшнему числу акций, а дивиденды T-Invest (тоже на сегодняшнее число акций) возвращаются в доходность в день, когда цена их теряет.</>,
    formulas: [String.raw`\tilde P_t = \frac{P_t}{k_t}, \qquad k_t = \prod_{s > t} \frac{\text{после}_s}{\text{до}_s}`,
      String.raw`1 + r_t = \frac{\tilde P_t + D_t}{\tilde P_{t-1}}, \qquad V_t = \tilde P_t \prod_{u \le t}\Big(1 + \frac{D_u}{\tilde P_u}\Big)`],
    where: [["k_t", "сколько сегодняшних акций стала одна акция дня t: сплиты ISS, а до 2018 года — скачки цены в круглое число раз (консолидация Интер РАО 2015)"],
      ["D_t", "дивиденды, отсечка которых пришлась на день t (первый торговый день после последнего дня покупки с правом), до налога — как в MCFTR"],
      ["V_t", "индекс полной доходности; последний его день равен сегодняшней цене"]],
    bookLabel: "Данные", book: <>Дивиденды — из server-analytic-system (T-Invest, с 2019 года, около 1 190 выплат по 173 акциям). Раньше 2019 года дивидендов в данных нет: там доходность ценовая.</>,
  },
  {
    id: "s12", title: "Сжатие ковариации и иерархический паритет риска", site: "Распределение",
    lead: <>Из 156 недель нельзя точно оценить корреляции 20 бумаг: оптимизатор, обращающий такую матрицу, ставит на шум. Два ответа: сжать корреляции к общему среднему или не обращать матрицу вовсе.</>,
    formulas: [String.raw`\hat\Sigma = \delta F + (1-\delta) S, \qquad F_{ij} = \bar\rho\, s_i s_j,\; F_{ii} = s_i^2, \qquad \delta^* = \max\!\Big(0, \min\!\Big(1, \frac{\hat\pi - \hat\varrho}{\hat\gamma\, T}\Big)\Big)`,
      String.raw`d_{ij} = \sqrt{\tfrac12 (1 - \rho_{ij})}, \qquad \alpha = 1 - \frac{V_1}{V_1 + V_2}, \qquad V = \tilde w^\top \Sigma\, \tilde w,\; \tilde w \propto \operatorname{diag}(\Sigma)^{-1}`],
    where: [["S, ρ̄", "выборочная ковариация и средняя корреляция"], ["π̂, ϱ̂, γ̂", "оценки ошибки выборочной матрицы, связи с целью и расстояния до цели (Ledoit, Wolf, 2004)"],
      ["HRP", "бумаги упорядочены деревом одиночной связи по расстоянию d, вес делится между половинами обратно их дисперсии V (López de Prado, 2016)"]],
  },
  {
    id: "s13", title: "Факторы: IC, квинтили, Фама–Макбет", site: "Факторы акций",
    lead: <>Вопрос факторного анализа — не «вырастет ли бумага», а «упорядочивает ли признак бумаги по будущей доходности». Мера — ранговая корреляция в каждом месяце; премия при прочих равных — регрессия Фамы–Макбета.</>,
    formulas: [String.raw`\mathrm{IC}_m = \operatorname{corr}\big(\operatorname{rank} f_{i,m},\; \operatorname{rank} r_{i,m+1}\big), \qquad t = \frac{\overline{\mathrm{IC}}}{s_{\mathrm{IC}}}\sqrt{M}`,
      String.raw`r_{i,m+1} = a_m + \sum_j b_{j,m}\, z_{ij,m} + \varepsilon_{i,m}, \qquad \hat b_j = \frac1M \sum_m b_{j,m}, \qquad t_j = \frac{\hat b_j}{s_{b_j}}\sqrt{M}`,
      String.raw`t^{*}_{K} = \Phi^{-1}\Big(1 - \frac{0{,}025}{K}\Big), \qquad \operatorname{med}\max_{k\le K} |t_k| = \Phi^{-1}\Big(\frac{1 + 2^{-1/K}}{2}\Big)`],
    where: [["f, z", "значение фактора на конец месяца и его ранг, приведённый к единичной дисперсии"], ["M", "месяцев"],
      ["K", "сколько факторов проверено: при 13 факторах порог Бонферрони 2,89, а лучший из 13 чистых шумов в среднем даёт |t| ≈ 1,9"],
      ["Q5 − Q1", "верхняя пятая часть бумаг по фактору минус нижняя; Q5 − все — то, что доступно без шортов"]],
    bookLabel: "На акциях Мосбиржи, 2015–2026", book: <>100 самых ликвидных бумаг, издержки 0,2% за сторону: моментум 12−1 (t = 3,8) и низкая волатильность (t = 4,1) проходят порог на 142 месяцах; доходность последнего месяца продолжается, а не разворачивается (t = −3,2), но оборот 77% в месяц съедает её. FCF/P и E/P проходят порог на 55–57 месяцах 2022–2026 годов — коротко и только на выживших бумагах.</>,
  },
];

const READING: [string, string][] = [
  ["Wasserman, «All of Statistics»", "вероятность, оценки, бутстреп — фундамент остального"],
  ["Ang, «Asset Management: A Systematic Approach to Factor Investing»", "«плохие времена», факторы, mean-variance, ребалансировка как продажа волатильности"],
  ["Basile, Ferrari (ред.), «Asset Management and Institutional Investors»", "стратегическое и тактическое распределение, бюджет риска"],
  ["McNeil, Frey, Embrechts, «Quantitative Risk Management»", "EVT, копулы, ES — к §3–§5"],
  ["Hamilton, «Time Series Analysis»", "смена режимов (§7)"],
  ["MacLean, Thorp, Ziemba, «The Kelly Capital Growth Investment Criterion»", "§8 и дробный Келли"],
  ["López de Prado, «Advances in Financial Machine Learning»", "переобучение бэктестов, дефлированный Шарп (§10), HRP (§12)"],
  ["Grinold, Kahn, «Active Portfolio Management»", "IC, фундаментальный закон активного управления — к §13"],
  ["Taleb, «Statistical Consequences of Fat Tails»", "что ломается в статистике при ξ > 0"],
  ["Статьи", "Grossman, Zhou (1993); Rockafellar, Uryasev (2000); Brunnermeier, Nagel, Pedersen (2008); Lo (2002); Welch, Goyal (2008); Fama, MacBeth (1973); Ledoit, Wolf (2004); Harvey, Liu, Zhu (2016)"],
];

export function Theory() {
  return (
    <div className="doc">
      <header className="doc-head">
        <div className="eyebrow">Конспект для изучения</div>
        <h1>Математика чёрных лебедей</h1>
        <p className="lede">Формулы, на которых стоят стресс-тест, контроль просадки и размер позиции. Заметки «В исследовании бота» — цифры основного счёта торгового бота (юань, золото, индекс МосБиржи, ОФЗ, 2006–2026, риск 10%); на сайте те же формулы считаются для любой корзины.</p>
      </header>
      <div className="doc-body">
        <nav className="toc" aria-label="Содержание">
          <ol>{SECTIONS.map((s, i) => <li key={s.id}><a href={`#/theory/${s.id}`} onClick={(e) => { e.preventDefault(); document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth" }); }}>§{i + 1} {s.title}</a></li>)}
            <li><a href="#/theory/read" onClick={(e) => { e.preventDefault(); document.getElementById("read")?.scrollIntoView({ behavior: "smooth" }); }}>Что читать</a></li></ol>
        </nav>
        <main className="doc-main">
          {SECTIONS.map((s, i) => (
            <section key={s.id} id={s.id} className="doc-sec">
              <h2><span className="n">§{i + 1}</span>{s.title}</h2>
              <p>{s.lead}</p>
              <div className="f">
                {s.formulas.map((f) => <Tex key={f} block>{f}</Tex>)}
                <dl className="where">{s.where.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>
              </div>
              {s.book && <div className="book"><div className="label">{s.bookLabel ?? "В исследовании бота"}</div><p>{s.book}</p></div>}
              <p className="site-link">На сайте: {s.site}.</p>
            </section>
          ))}
          <section id="read" className="doc-sec">
            <h2>Что читать, по порядку</h2>
            <ol className="path">{READING.map(([b, d]) => <li key={b}><b>{b}.</b> {d}</li>)}</ol>
          </section>
        </main>
      </div>
    </div>
  );
}
