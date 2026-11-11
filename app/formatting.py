"""Indian-style number formatting for both on-screen text and speech hints."""

from __future__ import annotations


def format_inr(amount: float) -> str:
    """Format rupees with Indian digit grouping, e.g. 135000 -> '₹1,35,000'."""
    value = round(amount)
    sign = "-" if value < 0 else ""
    digits = str(abs(value))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    return f"{sign}₹{digits}"


def spoken_inr(amount: float) -> str:
    """How a person in India would say an amount, e.g. 135000 -> '1.35 lakh rupees'."""
    value = abs(round(amount))
    if value >= 1_00_000:
        lakhs = f"{value / 1_00_000:.2f}".rstrip("0").rstrip(".")
        text = f"{lakhs} lakh"
    elif value >= 10_000 and value % 1000 == 0:
        text = f"{value // 1000} thousand"
    else:
        text = f"{value:,}"
    return f"{text} rupees"


def pct_change(old: float, new: float) -> float:
    """Percentage change from old to new, rounded to one decimal."""
    if old == 0:
        return 0.0
    return round((new - old) / old * 100, 1)


def signed_pct(value: float) -> str:
    return f"{value:+.1f}%"
