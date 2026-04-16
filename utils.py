"""Parsing, formatting, and chart generation helpers."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import BinaryIO, Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import database
import keyboards


@dataclass
class ParsedTransaction:
    """Result of free-text expense/income parsing."""

    tx_type: str  # 'expense' | 'income'
    amount: float
    category_key: str
    raw_note: str


# Keywords hinting income vs expense (Russian)
_INCOME_HINTS = re.compile(
    r"\b(зарплат|премия|доход|перевод\s+на|получил|подарок|бонус)\b",
    re.IGNORECASE,
)

# "Обед 500", "500 такси", "кофе — 120"
_AMOUNT_RE = re.compile(
    r"(?P<a>[+-]?\d+(?:[.,]\d+)?)\s*(?:₽|руб|usd|\$)?|(?P<b>(?:₽|\$)?\s*\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def _normalize_amount(raw: str) -> float | None:
    s = raw.strip().replace(" ", "").replace(",", ".")
    s = s.lstrip("₽$").strip()
    try:
        v = float(s)
    except ValueError:
        return None
    if v <= 0:
        return None
    return v


def _first_amount_in_text(text: str) -> tuple[float | None, str]:
    """Return (amount, text_without_amount_fragment) best-effort."""
    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not m:
        return None, text
    amt = _normalize_amount(m.group(1))
    stripped = (text[: m.start()] + " " + text[m.end() :]).strip()
    return amt, stripped


def parse_expense_text(text: str) -> ParsedTransaction | None:
    """
    Parse messages like 'Такси 200', '500 обед', 'кофе 120'.
    Defaults to expense; uses income hints for tx_type.
    """
    cleaned = text.strip()
    if not cleaned or cleaned.startswith("/"):
        return None

    amount, rest = _first_amount_in_text(cleaned)
    if amount is None:
        return None

    label = rest.strip("—–-:,. ") or "прочее"
    tx_type = "income" if _INCOME_HINTS.search(cleaned) else "expense"

    category_key = _category_from_label(label, tx_type)
    return ParsedTransaction(
        tx_type=tx_type,
        amount=amount,
        category_key=category_key,
        raw_note=cleaned,
    )


def _category_from_label(label: str, tx_type: str) -> str:
    low = label.lower()
    if tx_type == "income":
        if any(x in low for x in ("зарплат", "работ")):
            return "salary"
        if any(x in low for x in ("подар", "бонус", "премия")):
            return "gift"
        return "other_income"

    if any(x in low for x in ("еда", "обед", "ужин", "кофе", "рестор", "продукт")):
        return "food"
    if any(x in low for x in ("такси", "транспорт", "метро", "автобус", "бензин")):
        return "transport"
    if any(x in low for x in ("кино", "игр", "развлеч", "концерт")):
        return "entertainment"
    if any(x in low for x in ("врач", "аптек", "здоров", "спортзал")):
        return "health"
    return "other"


def format_money(amount: float, currency: str = "USD") -> str:
    return f"{amount:,.2f} {currency}".replace(",", " ")


def build_spending_chart_png(
    user_id: int,
    days: int,
    expenses_fetcher: Callable[[int, int], dict[str, float]] | None = None,
) -> BinaryIO:
    """
    Build a PNG bar chart of expenses by category for the last `days` days.
    Returns a binary stream positioned at start (BytesIO).
    """
    fetcher = expenses_fetcher or database.get_expenses_by_category
    data = fetcher(user_id, days)
    buffer = io.BytesIO()

    if not data:
        fig, ax = plt.subplots(figsize=(6, 3.5))
        ax.text(0.5, 0.5, "Нет расходов за выбранный период", ha="center", va="center")
        ax.axis("off")
        fig.savefig(buffer, format="png", bbox_inches="tight", dpi=120)
        plt.close(fig)
        buffer.seek(0)
        return buffer

    labels_ru = [keyboards.EXPENSE_CATEGORIES.get(key, key) for key in data]

    amounts = list(data.values())
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(labels_ru, amounts, color="#2d6a4f")
    ax.set_ylabel("Сумма")
    ax.set_title(f"Расходы по категориям ({days} дн.)")
    plt.xticks(rotation=25, ha="right")
    fig.tight_layout()
    fig.savefig(buffer, format="png", bbox_inches="tight", dpi=120)
    plt.close(fig)
    buffer.seek(0)
    return buffer


# Expose regex pieces for optional advanced use / tests
def match_amount_pattern(text: str) -> re.Match[str] | None:
    """Uses _AMOUNT_RE; keeps symbol referenced for lint/consistency."""
    return _AMOUNT_RE.search(text)
