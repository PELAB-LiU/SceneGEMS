"""Plain text tables and summaries for the campaign CLI."""

from typing import Any, Dict, List, Sequence


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """Left aligned columns separated by two spaces; numbers are right aligned."""
    cells = [[_text(value) for value in row] for row in rows]
    widths = [max([len(header)] + [len(row[column]) for row in cells]) for column, header in enumerate(headers)]
    numeric = [bool(rows) and all(isinstance(row[column], (int, float)) and not isinstance(row[column], bool) for row in rows) for column in range(len(headers))]

    def line(values: Sequence[str]) -> str:
        return "  ".join(value.rjust(width) if right else value.ljust(width) for value, width, right in zip(values, widths, numeric)).rstrip()

    return "\n".join([line(list(headers))] + [line(row) for row in cells])


def _text(value: Any) -> str:
    return "-" if value is None else str(value)


def verdicts_of(entry: Dict[str, Any]) -> Dict[str, int]:
    """A class's verdict counts per state, summed over its runs."""
    counts: Dict[str, int] = {}
    for states in entry["verdicts"].values():
        for state, count in states.items():
            counts[state] = counts.get(state, 0) + count
    return counts


def campaign_summary(campaign: Dict[str, Any]) -> str:
    lines = [
        f"campaign {campaign['name']} ({campaign['campaign_id']})",
        f"desired {campaign['desired_state']}, actual {campaign['actual_state']}" + (f" ({campaign['state_reason']})" if campaign.get("state_reason") else ""),
        f"config version {campaign['config_version']}, created {campaign['created_at']}"
        + (f", started {campaign['started_at']}" if campaign.get("started_at") else "")
        + (f", finished {campaign['finished_at']}" if campaign.get("finished_at") else ""),
    ]
    totals = campaign.get("totals")
    if totals:
        verdicts = ", ".join(f"{state} {count}" for state, count in sorted(totals["verdicts"].items())) or "none yet"
        lines.append(f"classes {totals['classes']}: open {totals['classes_open']}, complete {totals['classes_complete']}, abandoned {totals['classes_abandoned']}")
        lines.append(f"cases: {totals['complete']} complete of quota {totals['quota']}, {totals['dropped']} dropped, {totals['in_flight']} in flight")
        lines.append(f"verdicts: {verdicts}")
    return "\n".join(lines)


def coverage_table(classes: List[Dict[str, Any]]) -> str:
    states = sorted({state for entry in classes for state in verdicts_of(entry)})
    headers = ["class", "state", "quota", "complete", "dropped", "in flight", "budget left"] + states
    rows = []
    for entry in classes:
        counts = verdicts_of(entry)
        rows.append(
            [entry["class_id"], entry["state"], entry["quota"], entry["complete"], entry["dropped"], entry["in_flight"], entry["failure_budget_left"]] + [counts.get(state, 0) for state in states]
        )
    return table(headers, rows)
