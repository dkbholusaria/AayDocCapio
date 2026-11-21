from __future__ import annotations

import asyncio
import math
import random
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Optional

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "run_time": "21:00",
    "active_days": [0, 1, 2, 3, 4, 5, 6],
    "scope": "all",
    "scope_groups": [],
    "scope_pans": [],
    "distribution": "every_day",
    "distribute_days": 1,
    "split_boundary": "client_count",
    "alternate_cases": True,
    "clients_per_day": 20,
    "client_cooldown_sec": 90,
    "doc_cooldown_sec": 10,
    "jitter_sec": 20,
    "run_budget_min": 60,
    "backoff_min": 120,
    "on_backoff_action": "resume_same_evening",
    "timeout_retries": 2,
    "stop_keeps_remainder": True,
    "last_run_finished": "",
    "last_run_summary": {},
    "next_run_at": "",
    "rotation_cursor": 0,
    "split_phase": 0,
    "queue_remaining": [],
    "backoff_until": "",
}

def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
    return default


def _as_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _as_choice(value: Any, choices: tuple[str, ...], default: str) -> str:
    if isinstance(value, str) and value.strip().lower() in choices:
        return value.strip().lower()
    return default


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _parse_hhmm(value: Any) -> time:
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) == 2:
            try:
                hour = int(parts[0])
                minute = int(parts[1])
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    return time(hour, minute)
            except ValueError:
                pass
    return time(21, 0)


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def _combine(day: date, at: time) -> datetime:
    return datetime.combine(day, at)


def normalise_config(raw: dict | None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    cfg = dict(DEFAULT_CONFIG)

    cfg["enabled"] = _as_bool(source.get("enabled"), DEFAULT_CONFIG["enabled"])
    cfg["run_time"] = _parse_hhmm(source.get("run_time", DEFAULT_CONFIG["run_time"])).strftime("%H:%M")

    days = source.get("active_days", DEFAULT_CONFIG["active_days"])
    clean_days: list[int] = []
    if isinstance(days, (list, tuple, set)):
        for item in days:
            try:
                day = int(item)
            except (TypeError, ValueError):
                continue
            if 0 <= day <= 6 and day not in clean_days:
                clean_days.append(day)
    cfg["active_days"] = sorted(clean_days) if "active_days" in source else list(DEFAULT_CONFIG["active_days"])

    cfg["scope"] = _as_choice(source.get("scope"), ("all", "group", "pan"), "all")
    cfg["scope_groups"] = _as_str_list(source.get("scope_groups"))
    cfg["scope_pans"] = [p.upper() for p in _as_str_list(source.get("scope_pans"))]

    cfg["distribution"] = _as_choice(source.get("distribution"), ("every_day", "distribute"), "every_day")
    try:
        distribute_days = int(source.get("distribute_days", 1))
    except (TypeError, ValueError):
        distribute_days = 1
    cfg["distribute_days"] = distribute_days if distribute_days in (1, 2, 3) else 1
    cfg["split_boundary"] = _as_choice(source.get("split_boundary"), ("client_count", "group"), "client_count")
    cfg["alternate_cases"] = _as_bool(source.get("alternate_cases"), True)
    cfg["clients_per_day"] = _as_int(source.get("clients_per_day"), 20, 1, 500)

    cfg["client_cooldown_sec"] = _as_int(source.get("client_cooldown_sec"), 90, 0, 86400)
    cfg["doc_cooldown_sec"] = _as_int(source.get("doc_cooldown_sec"), 10, 0, 3600)
    cfg["jitter_sec"] = _as_int(source.get("jitter_sec"), 20, 0, 600)
    cfg["run_budget_min"] = _as_int(source.get("run_budget_min"), 60, 1, 1440)
    cfg["backoff_min"] = _as_int(source.get("backoff_min"), 120, 1, 1440)
    cfg["on_backoff_action"] = _as_choice(
        source.get("on_backoff_action"), ("resume_same_evening", "next_day"), "resume_same_evening")
    cfg["timeout_retries"] = _as_int(source.get("timeout_retries"), 2, 0, 5)
    cfg["stop_keeps_remainder"] = _as_bool(source.get("stop_keeps_remainder"), True)

    cfg["last_run_finished"] = str(source.get("last_run_finished", "") or "")
    summary = source.get("last_run_summary", {})
    cfg["last_run_summary"] = dict(summary) if isinstance(summary, dict) else {}

    next_run = _parse_datetime(source.get("next_run_at"))
    cfg["next_run_at"] = next_run.isoformat(timespec="seconds") if next_run else ""
    backoff = _parse_datetime(source.get("backoff_until"))
    cfg["backoff_until"] = backoff.isoformat(timespec="seconds") if backoff else ""

    cfg["rotation_cursor"] = _as_int(source.get("rotation_cursor"), 0, 0, 10_000_000)
    cfg["split_phase"] = _as_int(source.get("split_phase"), 0, 0, 2)
    cfg["queue_remaining"] = [p.upper() for p in _as_str_list(source.get("queue_remaining"))]
    return cfg


def compute_next_run(now: datetime, cfg: dict) -> Optional[datetime]:
    config = normalise_config(cfg)
    run_at = _parse_hhmm(config["run_time"])
    days = set(config["active_days"])
    if not days:
        return None
    candidate = _combine(now.date(), run_at)
    if now.weekday() in days and candidate > now:
        return candidate
    for offset in range(1, 15):
        day = now.date() + timedelta(days=offset)
        if day.weekday() in days:
            return _combine(day, run_at)
    return None


def is_due(now: datetime, cfg: dict) -> bool:
    config = normalise_config(cfg)
    if not config["enabled"]:
        return False
    backoff_until = _parse_datetime(config["backoff_until"])
    if backoff_until is not None and now < backoff_until:
        return False
    next_run = _parse_datetime(config["next_run_at"])
    if next_run is not None:
        return now >= next_run and now.weekday() in config["active_days"]
    run_at = _parse_hhmm(config["run_time"])
    if now.weekday() not in config["active_days"]:
        return False
    return now >= _combine(now.date(), run_at)


def in_scope(clients: list[dict], cfg: dict) -> list[dict]:
    config = normalise_config(cfg)
    result = [c for c in clients if not c.get("credential_invalid")]
    if config["scope"] == "group":
        groups = {g.strip().lower() for g in config["scope_groups"] if g.strip()}
        if not groups:
            return []
        return [c for c in result if str(c.get("group", "")).strip().lower() in groups]
    if config["scope"] == "pan":
        pans = {p.upper() for p in config["scope_pans"]}
        if not pans:
            return []
        return [c for c in result if str(c.get("pan", "")).upper() in pans]
    return result


def _split_sizes(total: int, parts: int) -> list[int]:
    base, extra = divmod(total, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


def _split_by_client_count(clients: list[dict], parts: int, phase: int) -> list[dict]:
    sizes = _split_sizes(len(clients), parts)
    start = sum(sizes[:phase])
    return clients[start:start + sizes[phase]]


def _split_by_group(clients: list[dict], parts: int, phase: int) -> list[dict]:
    groups: dict[str, list[int]] = {}
    blank_counter = 0
    for index, client in enumerate(clients):
        name = str(client.get("group", "")).strip()
        if not name:
            name = f"\x00{blank_counter}"
            blank_counter += 1
        groups.setdefault(name, []).append(index)

    buckets: list[list[int]] = [[] for _ in range(parts)]
    totals = [0] * parts
    ordered_groups = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[1][0]))
    for _name, indexes in ordered_groups:
        target = min(range(parts), key=lambda i: (totals[i], i))
        buckets[target].extend(indexes)
        totals[target] += len(indexes)

    chosen = sorted(buckets[phase]) if phase < len(buckets) else []
    return [clients[i] for i in chosen]


def _split_phase(cfg: dict) -> int:
    parts = _as_int(cfg.get("distribute_days"), 1, 1, 3)
    return _as_int(cfg.get("split_phase"), 0, 0, 2) % parts


def assign_split(clients: list[dict], cfg: dict, run_date: date | None = None) -> list[dict]:
    config = normalise_config(cfg)
    parts = max(1, min(3, config["distribute_days"]))
    phase = _split_phase(config)
    if parts <= 1:
        return list(clients)
    if config["split_boundary"] == "group":
        return _split_by_group(clients, parts, phase)
    return _split_by_client_count(clients, parts, phase)


def _rotated(clients: list[dict], cursor: int) -> list[dict]:
    if not clients:
        return []
    start = cursor % len(clients)
    return clients[start:] + clients[:start]


def assign_rotation(clients: list[dict], cursor: int, n: int) -> tuple[list[dict], int]:
    if not clients or n <= 0:
        return [], cursor
    take = min(n, len(clients))
    ordered = _rotated(clients, cursor)
    selected = ordered[:take]
    return selected, (cursor + take) % len(clients)


def _pans(clients: list[dict]) -> list[str]:
    return [str(c.get("pan", "")).upper() for c in clients if str(c.get("pan", "")).strip()]


def build_queue(clients: list[dict], cfg: dict, today: date | None = None) -> tuple[list[dict], dict]:
    config = normalise_config(cfg)
    cap = config["clients_per_day"]
    scoped = in_scope(clients, config)
    by_pan = {str(c.get("pan", "")).upper(): c for c in scoped if str(c.get("pan", "")).strip()}

    pending = []
    for pan in config["queue_remaining"]:
        client = by_pan.get(pan.upper())
        if client is not None and client not in pending:
            pending.append(client)

    if pending:
        selected = pending[:cap]
        config["queue_remaining"] = _pans(pending[cap:])
        return selected, config

    if not scoped:
        config["queue_remaining"] = []
        return [], config

    if config["distribution"] == "distribute":
        parts = config["distribute_days"]
        phase = _split_phase(config)
        slice_clients = assign_split(scoped, config, today)
        order = _rotated(slice_clients, config["rotation_cursor"]) if config["alternate_cases"] else slice_clients
        selected = order[:cap]
        remainder = order[cap:]
        config["split_phase"] = (phase + 1) % parts
        if config["alternate_cases"] and selected:
            config["rotation_cursor"] = (config["rotation_cursor"] + 1) % max(1, len(scoped))
        config["queue_remaining"] = _pans(remainder)
        return selected, config

    order = _rotated(scoped, config["rotation_cursor"]) if config["alternate_cases"] else scoped
    selected = order[:cap]
    remainder = order[cap:]
    if config["alternate_cases"] and selected:
        config["rotation_cursor"] = (config["rotation_cursor"] + 1) % len(scoped)
    config["queue_remaining"] = _pans(remainder)
    return selected, config


def estimate_nights(clients: list[dict], cfg: dict) -> int:
    config = normalise_config(cfg)
    scoped = in_scope(clients, config)
    cap = config["clients_per_day"]
    if not scoped:
        return 0
    if config["distribution"] == "every_day":
        return max(1, math.ceil(len(scoped) / cap))
    parts = config["distribute_days"]
    if config["split_boundary"] == "group":
        sizes = [len(_split_by_group(scoped, parts, i)) for i in range(parts)]
    else:
        sizes = _split_sizes(len(scoped), parts)
    return max(1, sum(math.ceil(size / cap) for size in sizes if size))


def cooldown_for(base_sec: int, jitter_sec: int, rng: random.Random | None = None) -> int:
    base = max(0, int(base_sec))
    jitter = max(0, int(jitter_sec))
    if jitter == 0:
        return base
    generator = rng or random.Random()
    return base + generator.randint(0, jitter)


def should_backoff(err_text: str) -> bool:
    text = str(err_text).lower()
    markers = (
        "rate limit", "rate-limit", "too many requests", "too many attempts",
        "error 429", " 429", "status 429", "blocked", "access denied",
        "unusual traffic", "ip has been", "temporarily restricted",
    )
    return any(marker in text for marker in markers)


def is_timeout(err_text: str) -> bool:
    text = str(err_text).lower()
    markers = ("timeout", "timed out", "time out", "err_timed_out", "net::err_timed_out")
    return any(marker in text for marker in markers)


async def interruptible_sleep(
    seconds: float,
    should_continue: Callable[[], bool] | None = None,
    is_paused: Callable[[], bool] | None = None,
    on_tick: Callable[[int, bool], None] | None = None,
    tick_sec: float = 1.0,
) -> bool:
    remaining = max(0.0, float(seconds))
    keep_going = should_continue or (lambda: True)
    paused = is_paused or (lambda: False)
    tick = max(0.1, float(tick_sec))
    while remaining > 0:
        if not keep_going():
            return False
        if paused():
            if on_tick:
                on_tick(int(math.ceil(remaining)), True)
            await asyncio.sleep(min(tick, remaining))
            continue
        step = min(tick, remaining)
        await asyncio.sleep(step)
        remaining -= step
        if on_tick:
            on_tick(int(math.ceil(max(0.0, remaining))), False)
    return keep_going()


def format_countdown(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
