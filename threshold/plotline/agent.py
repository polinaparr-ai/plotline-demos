"""The dashboard assistant loop.

Live mode   Claude (Messages API, client-side tools, streamed). Claude chooses the tools;
            plotline/tools.py runs them under plotline/policy.py.
Scripted    For recordings without an API key: the tool plan for the suggested questions is
            written down here, but every tool still runs for real against the warehouse and
            the answer text is filled in from what the tools returned.

Both modes emit the same events, so the page cannot tell them apart except for the badge.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time
from typing import Callable

import yaml

from plotline import personalisation, policy, tools

_ENV = yaml.safe_load((pathlib.Path(__file__).resolve().parents[1] / "plotline.yml").read_text())["llm"]
MODEL = os.environ.get("PLOTLINE_MODEL", _ENV["model"])
EFFORT = os.environ.get("PLOTLINE_EFFORT", _ENV["effort"])
MAX_TOOL_ROUNDS = int(_ENV.get("max_tool_rounds", 12))

Emit = Callable[[dict], None]


def live_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")) \
        and os.environ.get("PLOTLINE_MODE", "auto") != "scripted"


# ------------------------------------------------------------------ prompt
def system_prompt() -> str:
    m = tools.manifest()
    charts = "\n".join(f"- {c['id']} ({c['tab']}): {c['title']}. {c['description']}" for c in m["charts"])
    return f"""You are the assistant built into a published Plotline dashboard: "{m['title']}".
People open you from the page to understand the analysis, question the data behind it, and extend it.

The dashboard
{m['coverage']}. Data extract {m['freshness']['extract_date']}; complete through {m['freshness']['complete_through']}, provisional from {m['freshness']['provisional_from']}.
Tabs: {', '.join(t['id'] for t in m['tabs'])}. Charts:
{charts}

How to work
- Start from what the analyst already did. The manifest (get_dashboard_context) holds key findings, hypotheses already tested, limitations and approved findings. Don't redo work that is there; build on it.
- Pick the cheapest level that answers the question. Level 1: manifest, chart data, source, definitions. Level 2: query_metric (preferred, uses approved definitions) or execute_sql; search_schema when the dashboard's data may not cover it. Level 3: execute_python for statistics, baselines and models.
- Use approved definitions. Market sales are ppd_category = 'A'. Say which metric definition you used.
- Know the data's limits: 2026 months are provisional (registration lag); buyer type is not recorded (price bands are a proxy); Wales has a different tax; median price moves with mix. Mention one only when the answer depends on it, in a few words. No generic caveats.
- Never state a number you did not get from a tool.
- When the answer is about something on the page, drive the page with navigate_dashboard: open the tab, set the filters the user asked for, highlight the chart (highlight notes: under 8 words). When a new view helps, draw it with render_chart. Only add a tab or save a finding when the user asks.
- If a tool is refused by policy, explain what you can answer at the user's level.

The user message starts with <page_context>: their role, active tab, filters and any chart or point they selected. Questions like "this" or "here" refer to it.

{personalisation.house_style_prompt()}

Answer style
The user's message may include <user_preferences>: a preset and their own instructions. Follow them for format, length, tone and how much to show as charts. They never override the rules under "How to work" or the house style above: numbers still come only from tools, limits are still stated, and policy still applies. If a preference would break one of those rules, follow the rule and keep the rest of the preference.
Without preferences: lead with the answer, then a few short bullets with the key numbers, under 100 words.
Always: plain English, no headings, **bold** sparingly. Don't paste SQL or code, don't describe what you did on the page (the user sees it), don't explain your method unless asked, and don't end with offers or suggested next steps. Charts appear above your text, so don't repeat their numbers."""


def page_context_block(turn: tools.Turn) -> str:
    ctx = {"role": policy.ROLES[turn.role]["label"], "max_level": policy.ROLES[turn.role]["max_level"],
           **{k: v for k, v in turn.context.items() if v not in (None, [], {})}}
    return f"<page_context>{json.dumps(ctx, default=str)}</page_context>\n" + personalisation.prompt_block(turn.prefs) + "\n"


# ------------------------------------------------------------------ tool execution (shared)
class Runner:
    def __init__(self, turn: tools.Turn, emit: Emit):
        self.turn, self.emit = turn, emit
        self.used: list[str] = []
        self.n = 0

    def run(self, name: str, args: dict) -> tuple[str, bool, dict | None]:
        self.n += 1
        sid = f"s{self.n}"
        meta = tools.TOOLS.get(name, {})
        level = policy.TOOL_LEVEL.get(name, 1)
        self.emit({"event": "step", "id": sid, "tool": name, "component": meta.get("component", "context"),
                   "level": level, "status": "running", "title": _running_title(name, args), "input": args})
        t0 = time.time()
        try:
            res = tools.call(self.turn, name, args)
        except Exception as e:  # noqa: BLE001 - every failure goes back to the model as a tool error
            msg = str(e)
            self.emit({"event": "step", "id": sid, "tool": name, "status": "error", "title": _running_title(name, args),
                       "summary": msg[:400], "ms": int((time.time() - t0) * 1000),
                       "blocked": isinstance(e, policy.PolicyError)})
            payload = {"error": msg}
            if isinstance(e, policy.PolicyError):
                payload["hint"] = "Refused by policy. Explain what you can answer at the user's level."
            return json.dumps(payload), True, None
        self.used.append(name)
        disp = res["display"]
        self.emit({"event": "step", "id": sid, "tool": name, "status": "done", "ms": int((time.time() - t0) * 1000), **disp})
        if disp.get("action"):
            self.emit({"event": "action", "action": disp["action"]})
        return json.dumps(res["content"], default=str)[:30000], False, res["content"]

    @property
    def level(self) -> int:
        return max([policy.TOOL_LEVEL.get(t, 1) for t in self.used] or [1])


def _running_title(name: str, a: dict) -> str:
    return {
        "get_dashboard_context": "Reading the dashboard manifest",
        "get_metric_definition": f"Looking up “{a.get('name')}” in the semantic layer",
        "get_chart_data": f"Reading published data for {a.get('chart_id')}",
        "get_source_query": f"Inspecting how {a.get('chart_id')} was calculated",
        "search_schema": f"Asking Scout: “{a.get('query')}”",
        "describe_table": f"Scout is profiling {a.get('table')}",
        "query_metric": "Querying approved metrics: " + ", ".join(a.get("metrics") or []),
        "execute_sql": f"Running read-only SQL: {a.get('purpose', '')}",
        "execute_python": f"Running Python in the sandbox: {a.get('purpose', '')}",
        "render_chart": f"Drawing “{a.get('title')}”",
        "navigate_dashboard": f"Updating the dashboard: {a.get('action', '').replace('_', ' ')}",
        "save_finding": f"Saving finding “{a.get('title')}”",
    }.get(name, name)


# ------------------------------------------------------------------ live: Claude
def run_live(turn: tools.Turn, history: list, emit: Emit) -> tuple[list, dict]:
    import anthropic

    client = anthropic.Anthropic()
    runner = Runner(turn, emit)
    messages = list(history) + [{"role": "user", "content": page_context_block(turn) + turn.question}]
    defs = tools.definitions(turn.role)
    system = [{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}]
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}

    for _ in range(MAX_TOOL_ROUNDS):
        with client.beta.messages.stream(
            model=MODEL, max_tokens=16000, system=system, tools=defs, messages=messages,
            output_config={"effort": EFFORT},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        ) as stream:
            for ev in stream:
                if ev.type == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                    emit({"event": "text", "delta": ev.delta.text})
                elif ev.type == "content_block_start" and getattr(ev.content_block, "type", "") == "text":
                    emit({"event": "text_block"})
            msg = stream.get_final_message()

        for k in usage:
            usage[k] += getattr(msg.usage, k, 0) or 0
        content = [b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in msg.content]
        messages.append({"role": "assistant", "content": content})

        if msg.stop_reason == "refusal":
            emit({"event": "text", "delta": "\n\nI can't help with that request."})
            break
        if msg.stop_reason == "max_tokens":
            emit({"event": "text", "delta": "\n\n(The answer was cut off. Ask me to continue.)"})
            break
        if msg.stop_reason == "pause_turn":
            continue
        tool_uses = [b for b in msg.content if b.type == "tool_use"]
        if msg.stop_reason != "tool_use" or not tool_uses:
            break
        results = []
        for b in tool_uses:
            out, is_err, _ = runner.run(b.name, b.input if isinstance(b.input, dict) else {})
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, "is_error": is_err})
        messages.append({"role": "user", "content": results})  # all results in one message
    return messages, {"level": runner.level, "tools": runner.n, "usage": usage, "model": msg.model}


# ------------------------------------------------------------------ scripted: same tools, fixed plan
def _say(emit: Emit, text: str) -> None:
    emit({"event": "text_block"})
    for chunk in re.findall(r"\S+\s*", text):
        emit({"event": "text", "delta": chunk})
        time.sleep(0.018)


def _pct(v: float, d: int = 0) -> str:
    return f"{'+' if v >= 0 else '−'}{abs(v) * 100:.{d}f}%"


def _rows(content: dict) -> list[dict]:
    return [dict(zip(content["columns"], r)) for r in content["rows"]]


BAND_NAMES = {"01": "under £125k", "02": "£125k–250k", "03": "£250k–300k", "04": "£300k–425k",
              "05": "£425k–500k", "06": "£500k–625k", "07": "£625k–925k", "08": "£925k+"}


def script_overview(t, say):
    ctx = t("get_dashboard_context", section="overview")
    t("get_metric_definition", name="sales_count")
    rows = ctx["data_sources"][0]["rows"]
    say(f"**Threshold follows every residential sale in England and Wales registered with HM Land Registry since January 2023: "
        f"{rows:,} market sales.** It has three views: Market (volumes, prices, regional change), Stamp duty (the April 2025 "
        f"tax change) and Places (local authorities and the new-build premium).\n\n"
        f"A “sale” is the semantic layer’s `sales_count`: completed sales at full market value, so rows with `ppd_category = 'A'`. "
        f"That leaves out repossessions, sales to companies and other non-market transfers. "
        f"It counts completions, not agreed sales.")


def script_march(t, say):
    t("get_chart_data", chart_id="sales_monthly")
    t("get_metric_definition", name="sales_count")
    q = t("query_metric", metrics=["sales_count"], dimensions=["sale_month", "price_band"],
          filters={"country": "England", "sale_month": ["2024-03-01", "2025-03-01", "2025-04-01"]})
    r = _rows(q)
    get = lambda m, b: next((x["sales_count"] for x in r if x["sale_month"].startswith(m) and x["price_band"] == b), 0)
    bands = sorted({x["price_band"] for x in r})
    change = {b: get("2025-03", b) / get("2024-03", b) - 1 for b in bands}
    tot = lambda m: sum(x["sales_count"] for x in r if x["sale_month"].startswith(m))
    t("render_chart", title="March 2025 vs March 2024 completions, by price band (England)", chart_type="bar",
      x=[BAND_NAMES[b[:2]] for b in bands], series=[{"name": "Change on March 2024", "values": [round(change[b], 3) for b in bands]}],
      y_format="percent")
    t("navigate_dashboard", action="open_tab", tab="stamp_duty")
    t("navigate_dashboard", action="highlight_chart", chart_id="band_vs_expected",
      note="March 2025: far above normal")
    say(f"**Buyers were racing a tax deadline.** England had {tot('2025-03'):,} completions in March 2025, "
        f"{_pct(tot('2025-03') / tot('2024-03') - 1)} on March 2024, then {tot('2025-04'):,} in April after relief shrank.\n\n"
        f"The rush tracked the tax change by price band:\n"
        f"- **Under £125k:** {_pct(change['01 Under £125k'])} (no tax change)\n"
        f"- **£125k–250k:** {_pct(change['02 £125k–250k'])} (new 2% slice)\n"
        f"- **£300k–425k:** {_pct(change['04 £300k–425k'])} (first-time buyer relief cut)\n"
        f"- **£500k–625k:** {_pct(change['06 £500k–625k'])} (first-time buyer relief removed)")


def script_london(t, say):
    t("navigate_dashboard", action="open_tab", tab="market")
    t("navigate_dashboard", action="set_filters", filters={"region": "London", "property_type": "Flat/maisonette"})
    f = {"region": "London", "property_type": "Flat/maisonette"}
    y = _rows(t("query_metric", metrics=["sales_count", "median_price"], dimensions=["sale_year"], filters=f,
                start="2024-01-01", end="2025-12-01"))
    mo = _rows(t("query_metric", metrics=["sales_count"], dimensions=["sale_month"], filters=f,
                 start="2024-03-01", end="2025-04-01"))
    s = {r["sale_year"]: r for r in y}
    m = {r["sale_month"][:7]: r["sales_count"] for r in mo}
    say(f"**London flats:**\n"
        f"- **Sales:** {s[2025]['sales_count']:,} in 2025 against {s[2024]['sales_count']:,} in 2024 ({_pct(s[2025]['sales_count'] / s[2024]['sales_count'] - 1, 1)}).\n"
        f"- **Median price:** £{s[2025]['median_price']:,.0f}, {_pct(s[2025]['median_price'] / s[2024]['median_price'] - 1, 1)} on 2024. London flats were flat while most of the country rose.\n"
        f"- **The March spike** was {_pct(m['2025-03'] / m['2024-03'] - 1)} on March 2024 ({m['2025-03']:,} sales), then {m['2025-04']:,} in April.")


PYTHON_PULLFORWARD = '''
# Same baseline as analysis/stamp_duty_pullforward.py, extended to December 2025.
df["sale_month"] = pd.to_datetime(df.sale_month)
df["year"], df["month"] = df.sale_month.dt.year, df.sale_month.dt.month
w = df.pivot_table(index=["price_band", "month"], columns="year", values="sales").reset_index()
q3 = df[df.month.isin([7, 8, 9])].groupby(["price_band", "year"]).sales.sum().unstack()
w = w.merge((q3[2024] / q3[2023]).rename("g"), left_on="price_band", right_index=True)
w["expected"] = (w[2023] + w[2024]) / 2 * w["g"]
w["gap"] = w[2025] - w["expected"]
monthly = w.groupby("month")[["gap", 2025, "expected"]].sum()
cum = monthly.gap.cumsum()
excess = monthly.loc[1:3, "gap"].sum()
payback = {f"to_{m}": float(-monthly.loc[4:m, "gap"].sum() / excess) for m in (6, 9, 12)}

# How unusual was March 2025? Compare with every 2023-24 month's deviation from a leave-one-year-out baseline.
w["e23"], w["e24"] = w[2024] / w["g"], w[2023] * w["g"]
noise = np.log(pd.concat([w[2023] / w["e23"], w[2024] / w["e24"]]))
z_march = float(np.log(monthly.loc[3, 2025] / monthly.loc[3, "expected"]) / noise.std())
p_value = float(2 * stats.norm.sf(abs(z_march)))
print(f"excess Jan-Mar {excess:,.0f}; payback {payback}; z={z_march:.1f}, p={p_value:.1e}")
result = {"excess_jan_mar": float(excess), "payback": payback, "z_march": z_march, "p_value": p_value,
          "net_by_december": float(cum.loc[12]), "cumulative": [round(float(v)) for v in cum.values]}
'''


def script_pullforward(t, say):
    t("get_source_query", chart_id="pullforward_by_band", include="methodology")
    py = t("execute_python", purpose="extend the payback window to December 2025 and test March",
           input_sql=("SELECT sale_month, price_band, COUNT(*) AS sales FROM analytics.sales "
                      "WHERE ppd_category = 'A' AND country = 'England' "
                      "AND sale_month BETWEEN DATE '2023-01-01' AND DATE '2025-12-01' GROUP BY ALL"),
           code=PYTHON_PULLFORWARD.strip())
    r = py["result"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    t("render_chart", title="Cumulative sales above expected since January 2025 (England)", chart_type="line",
      x=[f"{m} 2025" for m in months], series=[{"name": "Cumulative extra sales", "values": r["cumulative"]}],
      y_format="number")
    p = r["payback"]
    verdict = ("mostly timing" if p["to_12"] >= 0.8 else "partly timing" if p["to_12"] >= 0.4 else "mostly not timing")
    say(f"**It was {verdict}, and the spike is far beyond normal noise.** Extending the analyst’s June window to December 2025:\n\n"
        f"- **About {r['excess_jan_mar']:,.0f} extra completions** in January–March 2025.\n"
        f"- **{p['to_6']:.0%} paid back by June**, {p['to_9']:.0%} by September, **{p['to_12']:.0%} by December**.\n"

        f"- March 2025 was **{r['z_march']:.0f} standard deviations** above normal (p ≈ {r['p_value']:.0e}).")


def script_ftb(t, say):
    s = t("search_schema", query="first time buyers buyer type")
    t("describe_table", table="ref.sdlt_bands")
    q = _rows(t("query_metric", metrics=["sales_count"], dimensions=["price_band"],
                filters={"country": "England", "sale_month": ["2024-03-01", "2025-03-01"],
                         "price_band": ["04 £300k–425k", "05 £425k–500k", "06 £500k–625k"]}))
    q2 = _rows(t("query_metric", metrics=["sales_count"], dimensions=["sale_month"],
                 filters={"country": "England", "price_band": ["04 £300k–425k", "05 £425k–500k", "06 £500k–625k"]},
                 start="2024-03-01", end="2025-03-01"))
    mar24 = next(r["sales_count"] for r in q2 if r["sale_month"].startswith("2024-03"))
    mar25 = next(r["sales_count"] for r in q2 if r["sale_month"].startswith("2025-03"))
    top = s["results"][0]["table"] if s["results"] else "none"
    say(f"**Not directly: buyer type isn’t recorded.** Scout found no buyer field; its closest match was `{top}`, the Stamp Duty bands.\n\n"
        f"The nearest proxy is £300k–625k, where first-time buyers’ tax rose most. Those bands went from {mar24:,} completions in "
        f"March 2024 to {mar25:,} in March 2025 (**{_pct(mar25 / mar24 - 1)}**), an upper bound since other buyers there paid more too.")


def script_2026(t, say):
    t("get_metric_definition", name="sales_count")
    q = _rows(t("query_metric", metrics=["sales_count"], dimensions=["sale_month"], start="2024-01-01", end="2026-08-01"))
    by = {r["sale_month"][:7]: r["sales_count"] for r in q}
    months = ["01", "02", "03", "04", "05", "06", "07", "08"]
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
    t("render_chart", title="Sales by completion month: 2024, 2025 and 2026 (registered so far)", chart_type="line",
      x=names, series=[{"name": y, "values": [by.get(f"{y}-{m}") for m in months]} for y in ("2024", "2025", "2026")],
)
    early = sum(by[f"2026-{m}"] for m in ("01", "02")) / sum(by[f"2024-{m}"] for m in ("01", "02")) - 1
    late = sum(by[f"2026-{m}"] for m in ("06", "07", "08")) / sum(by[f"2024-{m}"] for m in ("06", "07", "08")) - 1
    say(f"**No. Most of the drop is sales not yet registered.** Land Registry adds sales months after completion, so the gap "
        f"grows the more recent the month:\n"
        f"- January–February 2026 vs 2024: **{_pct(early)}**\n"
        f"- June–August 2026 vs 2024: **{_pct(late)}**\n\n"
        f"Early 2026, which has had time to fill in, is close to 2024.")


def script_save_tab(t, say, turn=None):
    fig = turn.last_chart if turn else None
    title = "Stamp duty rush: how much was timing"
    summary = ("Extending the pull-forward baseline to December 2025 shows how much of the Jan–Mar 2025 excess "
               "was paid back by later months.")
    if fig and fig.get("title", "").startswith("Cumulative"):
        vals = fig["data"][0]["y"]
        peak, dec = max(vals), vals[-1]
        title = f"Stamp duty rush: about {1 - dec / peak:.0%} was timing"
        summary = (f"About {peak:,} more completions than expected had built up in England by March 2025, ahead of the "
                   f"1 April Stamp Duty change. By December 2025 the cumulative excess was down to {dec:,}: roughly "
                   f"{1 - dec / peak:.0%} of the rush was sales brought forward, the rest extra 2025 activity. "
                   f"Baseline: seasonal 2023–24 average, trend-adjusted (analysis/stamp_duty_pullforward.py, extended).")
    t("navigate_dashboard", action="add_tab", title="Stamp duty payback")
    t("save_finding", title=title, summary=summary)
    say("**Saved** as a new tab and as a draft finding with its evidence. Once approved, it informs every future answer on this dashboard.")


SCRIPTS = {
    "overview": (script_overview, ["what does", "dashboard show", "how is a sale", "counted", "defined", "overview"]),
    "march": (script_march, ["march", "spike", "why did sales", "price band", "jump"]),
    "london": (script_london, ["london", "flats", "show me this for"]),
    "pullforward": (script_pullforward, ["timing", "pulled forward", "pull-forward", "significant", "rush", "payback"]),
    "ftb": (script_ftb, ["first-time", "first time", "buyer type", "ftb"]),
    "collapse": (script_2026, ["2026", "collapse", "crash", "falling"]),
    "save_tab": (script_save_tab, ["new tab", "save this", "save the analysis", "add a tab", "as a tab"]),
}


def match_script(question: str, script_id: str | None, context: dict | None = None) -> str | None:
    if script_id in SCRIPTS:
        return script_id
    q = question.lower()
    scores = {k: sum(kw in q for kw in kws) for k, (_, kws) in SCRIPTS.items()}
    best = max(scores, key=scores.get)
    if scores[best]:
        return best
    # A question about a clicked point ("why is this so high?") on the volume charts.
    chart = (context or {}).get("selected_chart")
    if chart in ("sales_monthly", "band_vs_expected", "band_monthly", "pullforward_by_band"):
        return "march"
    return None


def run_scripted(turn: tools.Turn, script_id: str | None, emit: Emit) -> dict:
    runner = Runner(turn, emit)
    sid = match_script(turn.question, script_id, turn.context)
    if not sid:
        _say(emit, "This recording is running in **scripted mode** (no API key configured), so I can only answer the suggested "
                   "questions. Their tools still run live against the warehouse. Set `ANTHROPIC_API_KEY` and restart the server "
                   "to ask anything.")
        return {"level": 1, "tools": 0, "usage": None, "model": None}

    class Blocked(Exception):
        pass

    def t(_tool, **args):
        out, is_err, content = runner.run(_tool, args)
        if is_err:
            raise Blocked(json.loads(out)["error"])
        return content

    try:
        fn = SCRIPTS[sid][0]
        say = lambda text: _say(emit, text)  # noqa: E731
        fn(t, say, turn) if fn is script_save_tab else fn(t, say)
    except Blocked as e:
        _say(emit, f"I can’t go further with your current role. {e}\n\nAt your level I can still explain the charts, "
                   f"definitions and method behind this dashboard.")
    return {"level": runner.level, "tools": runner.n, "usage": None, "model": None, "script": sid}
