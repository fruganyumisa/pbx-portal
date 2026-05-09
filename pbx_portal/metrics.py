from collections import defaultdict
from datetime import datetime, timedelta


def build_dashboard(cdr_repo, queue_repo, start, end, queue=None, agent=None):
    calls = cdr_repo.fetch_calls(start=start, end=end, queue=queue, agent=agent)
    queue_events = queue_repo.fetch_events(start=start, end=end, queue=queue, agent=agent)

    agents = _agent_metrics(calls, queue_events)
    totals = _totals(calls, agents)
    summary = _call_summary(calls)

    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "source": cdr_repo.source_name,
        "filters": {"queue": queue, "agent": agent},
        "totals": totals,
        "summary": summary,
        "agents": sorted(agents, key=lambda row: row["efficiency_score"], reverse=True),
        "agent_activity": _agent_activity(agents),
        "trend": _daily_trend(calls, start, end),
        "duration_bands": _duration_bands(calls),
        "top_sources": _top_values(calls, "src"),
        "top_destinations": _top_values(calls, "dst"),
        "recent_calls": [_call_register_row(call) for call in calls[:200]],
    }


def _agent_metrics(calls, queue_events):
    grouped = defaultdict(list)
    for call in calls:
        if call["agent"] == "unassigned":
            continue
        grouped[call["agent"]].append(call)

    queue_stats = _queue_event_stats(queue_events)
    rows = []
    for agent, agent_calls in grouped.items():
        total = len(agent_calls)
        answered_calls = [call for call in agent_calls if call["answered"]]
        missed = total - len(answered_calls)
        talk_seconds = sum(call["billsec"] for call in answered_calls)
        ring_seconds = sum(call["ring_seconds"] for call in agent_calls)
        inbound = sum(1 for call in agent_calls if call["direction"] == "inbound")
        outbound = sum(1 for call in agent_calls if call["direction"] == "outbound")
        avg_talk = talk_seconds / len(answered_calls) if answered_calls else 0
        answer_rate = (len(answered_calls) / total) * 100 if total else 0
        avg_ring = ring_seconds / total if total else 0
        queue_stat = queue_stats.get(agent, {})
        available_seconds = queue_stat.get("available_seconds") or _estimated_available_seconds(agent_calls)
        occupancy = (talk_seconds / available_seconds) * 100 if available_seconds else 0

        rows.append(
            {
                "agent": agent,
                "total_calls": total,
                "answered_calls": len(answered_calls),
                "missed_calls": missed,
                "inbound_calls": inbound,
                "outbound_calls": outbound,
                "talk_seconds": int(talk_seconds),
                "avg_talk_seconds": int(avg_talk),
                "avg_ring_seconds": int(avg_ring),
                "answer_rate": round(answer_rate, 1),
                "occupancy": round(min(occupancy, 100), 1),
                "login_seconds": int(available_seconds),
                "pauses": queue_stat.get("pauses", 0),
                "efficiency_score": _efficiency_score(answer_rate, occupancy, avg_ring),
            }
        )
    return rows


def _queue_event_stats(events):
    stats = defaultdict(lambda: {"pauses": 0, "available_seconds": 0})
    sessions = {}

    for event in sorted(events, key=lambda item: item["timestamp"]):
        agent = event["agent"]
        name = event["event"]
        if name in {"ADDMEMBER", "CONNECT", "UNPAUSE"}:
            sessions.setdefault(agent, event["timestamp"])
        elif name in {"REMOVEMEMBER", "PAUSE", "PAUSEALL"}:
            if name.startswith("PAUSE"):
                stats[agent]["pauses"] += 1
            started = sessions.pop(agent, None)
            if started:
                stats[agent]["available_seconds"] += max((event["timestamp"] - started).total_seconds(), 0)

    now = datetime.utcnow()
    for agent, started in sessions.items():
        stats[agent]["available_seconds"] += max((now - started).total_seconds(), 0)

    return stats


def _estimated_available_seconds(calls):
    if not calls:
        return 0
    first = min(call["calldate"] for call in calls)
    last = max(call["calldate"] + timedelta(seconds=call["duration"]) for call in calls)
    return max((last - first).total_seconds(), 1)


def _efficiency_score(answer_rate, occupancy, avg_ring):
    ring_penalty = min(avg_ring, 30) / 30 * 15
    return round(max(0, (answer_rate * 0.55) + (min(occupancy, 90) * 0.5) - ring_penalty), 1)


def _totals(calls, agents):
    total_calls = len(calls)
    answered = sum(1 for call in calls if call["answered"])
    talk_seconds = sum(call["billsec"] for call in calls if call["answered"])
    return {
        "agents": len(agents),
        "total_calls": total_calls,
        "answered_calls": answered,
        "missed_calls": max(total_calls - answered, 0),
        "answer_rate": round((answered / total_calls) * 100, 1) if total_calls else 0,
        "talk_seconds": talk_seconds,
        "avg_talk_seconds": int(talk_seconds / answered) if answered else 0,
    }


def _call_summary(calls):
    total = len(calls)
    answered = sum(1 for call in calls if call["answered"])
    abandoned = sum(1 for call in calls if not call["answered"] and call["duration"] > 0)
    failed = sum(1 for call in calls if _status(call) in {"Failed", "Busy", "Congestion"})
    inbound = sum(1 for call in calls if call["direction"] == "inbound")
    outbound = sum(1 for call in calls if call["direction"] == "outbound")
    talk_seconds = sum(call["billsec"] for call in calls)
    total_duration = sum(call["duration"] for call in calls)
    return {
        "received_calls": inbound,
        "placed_calls": outbound,
        "answered_calls": answered,
        "hanged_before_received": abandoned,
        "failed_calls": failed,
        "unanswered_calls": max(total - answered, 0),
        "avg_duration_seconds": int(total_duration / total) if total else 0,
        "avg_talk_seconds": int(talk_seconds / answered) if answered else 0,
        "total_duration_seconds": total_duration,
    }


def _agent_activity(agents):
    return [
        {
            "agent": row["agent"],
            "active_seconds": row["login_seconds"],
            "talk_seconds": row["talk_seconds"],
            "idle_seconds": max(row["login_seconds"] - row["talk_seconds"], 0),
            "occupancy": row["occupancy"],
            "pauses": row["pauses"],
            "calls": row["total_calls"],
        }
        for row in sorted(agents, key=lambda item: item["login_seconds"], reverse=True)
    ]


def _duration_bands(calls):
    bands = [
        ("Under 30s", lambda value: value < 30),
        ("30s-2m", lambda value: 30 <= value < 120),
        ("2m-5m", lambda value: 120 <= value < 300),
        ("5m-10m", lambda value: 300 <= value < 600),
        ("10m+", lambda value: value >= 600),
    ]
    return [
        {"label": label, "calls": sum(1 for call in calls if predicate(call["duration"]))}
        for label, predicate in bands
    ]


def _top_values(calls, key, limit=8):
    counts = defaultdict(int)
    for call in calls:
        value = call.get(key) or "unknown"
        counts[value] += 1
    return [
        {"value": value, "calls": count}
        for value, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def _call_register_row(call):
    return {
        "time": call["calldate"].isoformat(),
        "source": call["src"],
        "destination": call["dst"],
        "agent": call["agent"],
        "direction": call["direction"],
        "status": _status(call),
        "duration_seconds": call["duration"],
        "talk_seconds": call["billsec"],
        "ring_seconds": call["ring_seconds"],
        "queue": call.get("queue"),
    }


def _status(call):
    disposition = (call.get("disposition") or "").upper()
    if call["answered"]:
        return "Answered"
    if disposition == "NO ANSWER":
        return "Hung Before Answer"
    if disposition == "BUSY":
        return "Busy"
    if disposition == "FAILED":
        return "Failed"
    if disposition == "CONGESTION":
        return "Congestion"
    return disposition.title() if disposition else "Unanswered"


def _daily_trend(calls, start, end):
    days = {}
    current = start.date()
    while current <= end.date():
        days[current.isoformat()] = {"date": current.isoformat(), "calls": 0, "answered": 0}
        current += timedelta(days=1)

    for call in calls:
        key = call["calldate"].date().isoformat()
        days.setdefault(key, {"date": key, "calls": 0, "answered": 0})
        days[key]["calls"] += 1
        if call["answered"]:
            days[key]["answered"] += 1
    return list(days.values())
