# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 SanyLok
from __future__ import annotations
import ipaddress
import re
from dataclasses import dataclass
import math
import statistics
WINDOW = 60
CONTROL_ADDRESS = '1.1.1.1'
VERSION = '2.0'
def validate_target(text):
    text = text.strip().rstrip(".")
    try:
        ip = ipaddress.IPv4Address(text)
        if ip.is_unspecified or ip.is_multicast or str(ip) == "255.255.255.255":
            raise ValueError("Недопустимый IPv4")
        return str(ip)
    except ipaddress.AddressValueError:
        if re.fullmatch(r"[0-9.]+", text):
            raise ValueError("Некорректный IPv4")
    try:
        hostname = text.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("Некорректное имя узла") from exc
    labels = hostname.split(".")
    if len(hostname) > 253 or len(labels) < 2 or not all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise ValueError("Введите IPv4 или полное имя узла")
    return hostname



@dataclass(frozen=True)
class Sample:
    rtt: float | None
    error: str = ""



def summarize(samples):
    """One shared window. None = no reply; local errors aren't packet loss."""
    samples = tuple(samples)
    attempts = [s for s in samples if not s.error]
    diffs = [abs(b.rtt - a.rtt) for a, b in zip(samples, samples[1:])
             if not a.error and not b.error and a.rtt is not None and b.rtt is not None]
    values = [s.rtt for s in samples if not s.error and s.rtt is not None]
    return {
        "loss": 100 * sum(s.rtt is None for s in attempts) / len(attempts) if attempts else None,
        "jitter": sum(diffs) / len(diffs) if diffs else None,
        "count": len(attempts),
        "total": len(samples),
        "errors": sum(bool(s.error) for s in samples),
        "received": len(values),
        "avg": statistics.fmean(values) if values else None,
        "p50": percentile(values, .5),
        "p95": percentile(values, .95),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    rank = (len(values) - 1) * fraction
    lower, upper = math.floor(rank), math.ceil(rank)
    return values[lower] + (values[upper] - values[lower]) * (rank - lower)


def quality(sample, stats):
    """A display assessment, not a guarantee of in-game performance."""
    if sample.error:
        return 'error'
    if sample.rtt is None:
        return 'bad'
    loss, jitter = stats.get('loss') or 0, stats.get('jitter') or 0
    if loss >= 5 or jitter >= 30 or sample.rtt >= 150:
        return 'bad'
    if loss > 0 or jitter >= 15 or sample.rtt >= 90 or stats.get('errors', 0):
        return 'warning'
    return 'good' if stats.get('count', 0) >= 5 else 'collecting'


QUALITY_COLORS = {'error': '#ffc857', 'bad': '#ff6289', 'warning': '#ffc857',
                  'good': '#44e6c3', 'collecting': '#b5b0c8'}


class AlertTracker:
    def __init__(self, rtt=150, loss=5, jitter=30, cooldown=120):
        self.rtt, self.loss, self.jitter = rtt, loss, jitter
        self.cooldown = cooldown
        self.bad_run = self.good_run = 0
        self.degraded = False
        self.last_alert = -float('inf')

    def update(self, sample, stats, now):
        if stats.get('total', stats.get('count', 0)) < 5:
            return None
        bad = (bool(sample.error) or sample.rtt is None or sample.rtt >= self.rtt
               or (stats.get('loss') or 0) >= self.loss
               or (stats.get('jitter') or 0) >= self.jitter)
        self.bad_run = self.bad_run + 1 if bad else 0
        self.good_run = self.good_run + 1 if not bad else 0
        if self.bad_run >= 3 and not self.degraded and now - self.last_alert >= self.cooldown:
            self.degraded = True
            self.last_alert = now
            return 'degraded'
        if self.good_run >= 5 and self.degraded:
            self.degraded = False
            return 'recovered'
        return None



def diagnostic_hint(nodes):
    """Conservative comparison against each node's own preceding baseline."""
    if len(nodes) < 3:
        return "Накопление сравнительных измерений…"
    if any(node["sample"].error or node["sample"].rtt is None for node in nodes.values()):
        return "Есть ошибки или нет ответов. ICMP может фильтроваться; причину обрыва это не доказывает."
    elevated = {}
    for role, node in nodes.items():
        values = [s.rtt for s in node["samples"][:-1] if s.rtt is not None and not s.error]
        if len(values) < 5:
            return "Накопление базы: сравнение появится после 6 успешных измерений."
        baseline = percentile(values, .2)
        elevated[role] = node["sample"].rtt - baseline >= max(30, baseline * .2)
    if elevated["gateway"]:
        return "Задержка выросла уже до шлюза. Возможна проблема локального участка; это предположение."
    if elevated["control"] and elevated["target"]:
        return "Шлюз стабилен, обе внешние точки замедлились. Проверьте загрузку канала и внешнюю связь."
    if elevated["target"]:
        return "Замедлился только выбранный узел. Возможны особенности его маршрута или обработки запросов."
    if elevated["control"]:
        return "Замедлился только контрольный узел. Проверьте другую внешнюю точку; общий сбой интернета не подтверждён."
    return "Заметного роста относительно базы этих точек сейчас нет. Это не гарантия качества игры."

