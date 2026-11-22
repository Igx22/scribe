"""Turn the current report run's API usage into a local price estimate."""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import escape
import json
import math
from pathlib import Path
import re


PRICING_FILE = Path(__file__).resolve().parent / "resources" / "api-pricing.json"
TIER_FACTOR = {"default": Decimal(1), "fast": Decimal(2), "priority": Decimal(2)}


@dataclass
class StageUsage:
    requests: int = 0
    priced: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    input_cost: Decimal = Decimal(0)
    output_cost: Decimal = Decimal(0)
    audio_seconds: Decimal = Decimal(0)
    audio_cost: Decimal = Decimal(0)

    @property
    def cost(self):
        return self.input_cost + self.output_cost + self.audio_cost


def token_count(value):
    return value if type(value) is int and value >= 0 else None


def object_fields(value):
    return value if isinstance(value, dict) else {}


def text_cost(row, counts, pricing):
    model = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", str(row.get("model") or ""))
    tier = TIER_FACTOR.get(str(row.get("service_tier")))
    rates = pricing.get("text_usd_per_million", {}).get(model)
    if tier is None or rates is None or None in counts:
        return None
    detail = object_fields(row["usage"].get("input_tokens_details"))
    writes = object_fields(detail.get("cache_write_tokens_details"))
    cached = token_count(detail.get("cached_tokens", 0))
    written = token_count(detail.get("cache_write_tokens", 0))
    short = token_count(writes.get("ttl_30m_tokens", 0))
    long = token_count(writes.get("ttl_12h_tokens", 0))
    if None in (cached, written, short, long) or written != short + long or cached + written > counts[0]:
        return None
    input_rate = Decimal(rates["input"]) * tier
    cached_rate = Decimal(rates["cached_input"]) * tier
    output_rate = Decimal(rates["output"]) * tier
    if counts[0] > 272_000:
        input_rate *= 2
        cached_rate *= 2
        output_rate *= Decimal("1.5")
    input_cost = ((counts[0] - cached - written) * input_rate + cached * cached_rate
                  + short * input_rate * Decimal("1.25") + long * input_rate * Decimal("2.5"))
    return input_cost / 1_000_000, counts[1] * output_rate / 1_000_000


def stage_name(stage):
    if stage.startswith("summary level "):
        return "Video summaries"
    if stage.startswith("youtube comment-summary"):
        return "Comment summaries"
    return {"reconciliation": "Transcript reconciliation", "report header": "Report header",
            "YouTube comment filter": "Comment filtering",
            "youtube best-comments": "Smartest comments"}.get(stage, "Other API requests")


def summarize_usage(run, pricing):
    groups = defaultdict(StageUsage)
    for row in run.get("audio_usage", []):
        group = groups["Cloud transcription"]
        group.requests += 1
        seconds = object_fields(row.get("usage")).get("seconds")
        rate = pricing.get("audio_usd_per_minute", {}).get(str(row.get("model") or "gpt-transcribe"))
        if type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0:
            duration = Decimal(str(seconds))
            group.audio_seconds += duration
            if rate is not None:
                group.priced += 1
                group.audio_cost += duration * Decimal(rate) / 60
    for row in run.get("text_usage", []):
        group = groups[stage_name(str(row.get("stage") or ""))]
        group.requests += 1
        usage = object_fields(row.get("usage"))
        counts = token_count(usage.get("input_tokens")), token_count(usage.get("output_tokens"))
        group.input_tokens += counts[0] or 0
        group.output_tokens += counts[1] or 0
        if (cost := text_cost(row, counts, pricing)) is not None:
            group.priced += 1
            group.input_cost += cost[0]
            group.output_cost += cost[1]
    return groups


def render_usage(run):
    if run is None:
        return ""
    try:
        pricing = json.loads(PRICING_FILE.read_text(encoding="utf-8"))
        groups = summarize_usage(run, pricing)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
        pricing = {}
        groups = summarize_usage(run, pricing)
    requests = sum(group.requests for group in groups.values())
    priced = sum(group.priced for group in groups.values())
    if not requests:
        return ('<section class="api-usage" aria-label="API usage for this run">'
                '<div class="api-usage-line"><strong>API usage</strong>'
                '<span>No new API usage recorded</span></div></section>')
    audio = groups.get("Cloud transcription", StageUsage())
    inputs = sum(group.input_tokens for group in groups.values())
    outputs = sum(group.output_tokens for group in groups.values())
    input_cost = sum(group.input_cost for group in groups.values())
    output_cost = sum(group.output_cost for group in groups.values())
    cost = input_cost + output_cost + audio.audio_cost
    request_label = "request" if requests == 1 else "requests"
    price_label = "est." if priced == requests else "partial est."
    total = (f'<span class="api-usage-amount" aria-hidden="true">$</span>'
             f'<strong aria-label="Approximately {cost:.3f} US dollars">≈ {cost:.3f}</strong> {price_label}'
             if priced else "Cost unavailable")
    input_label = f' <small>· ${input_cost:.3f}</small>' if priced > audio.priced else ""
    output_label = f' <small>· ${output_cost:.3f}</small>' if priced > audio.priced else ""
    rows = []
    for stage, row in groups.items():
        row_total = f"${row.cost:.4f}" if row.priced else "Unavailable"
        if 0 < row.priced < row.requests:
            row_total += " (partial)"
        if stage == "Cloud transcription":
            metrics = f'<td colspan="2">{row.audio_seconds:g} s reported</td>'
        else:
            metrics = "".join(f'<td>{tokens:,}' + (f'<small>${cost:.4f}</small>' if row.priced else "") + '</td>'
                              for tokens, cost in ((row.input_tokens, row.input_cost),
                                                   (row.output_tokens, row.output_cost)))
        rows.append(f'<tr><th scope="row">{escape(stage)} <small>· {row.requests}</small></th>'
                    f'{metrics}<td>{row_total}</td></tr>')
    limited = (" Usage or pricing is unavailable for some requests. Totals include reported tokens and priced requests."
               if priced < requests else "")
    date = f' Rates checked {escape(pricing["checked"])}.' if pricing.get("checked") else ""
    return (
        '<section class="api-usage" aria-label="API usage for this run"><div class="api-usage-line">'
        f'<span class="api-usage-heading"><strong>API usage</strong> · {requests} {request_label}</span>'
        f'<span><strong>{inputs:,}</strong> input{input_label}</span>'
        f'<span><strong>{outputs:,}</strong> output{output_label}</span>'
        f'<span class="api-usage-total">{total}</span></div>'
        '<details><summary>Cost breakdown</summary><div class="api-usage-table" tabindex="0" '
        'role="region" aria-label="Usage by stage"><table>'
        '<thead><tr><th scope="col">Stage</th><th scope="col">Input tokens</th>'
        '<th scope="col">Output tokens</th><th scope="col">Estimated cost</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
        '<p>Estimates use recorded API responses from this run. Reused Scribe checkpoints carry no new cost.'
        f' Output includes reasoning tokens.{limited}{date} '
        '<a href="https://developers.openai.com/api/docs/pricing">OpenAI API pricing</a></p>'
        '</details></section>')
