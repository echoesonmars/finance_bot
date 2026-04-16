"""Интеграция с облачным ИИ: персональные советы и разбор фото чеков (только для разработчика в коде)."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from openai import OpenAI

import config
import keyboards

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=config.OPENAI_API_KEY,
            timeout=60.0,
            max_retries=1,
        )
    return _client


def _category_ru(cat_key: str, tx_type: str) -> str:
    if tx_type == "income":
        return keyboards.INCOME_CATEGORIES.get(cat_key, cat_key)
    return keyboards.EXPENSE_CATEGORIES.get(cat_key, cat_key)


def get_financial_advice(user_data: dict[str, Any]) -> str:
    """
    Короткий персональный совет на русском по агрегированной статистике.
    user_data: period_days, currency, budget, total_expense, total_income,
    remaining, expenses_by_category, recent_transactions.
    """
    if not config.OPENAI_API_KEY:
        return (
            "Персональные подсказки сейчас недоступны. "
            "Запись трат, доходов, лимит и графики по-прежнему работают."
        )

    period = int(user_data.get("period_days", 7))
    currency = user_data.get("currency", "USD")
    budget = user_data.get("budget")
    total_expense = user_data.get("total_expense", 0.0)
    total_income = user_data.get("total_income", 0.0)
    remaining = user_data.get("remaining")
    by_cat = user_data.get("expenses_by_category") or {}
    recent = user_data.get("recent_transactions") or []

    stats_lines = [
        f"Период: последние {period} дней.",
        f"Валюта: {currency}.",
        f"Расходы за период: {total_expense:.2f}.",
        f"Доходы за период: {total_income:.2f}.",
    ]
    if budget is not None:
        stats_lines.append(f"Заданный лимит (бюджет): {float(budget):.2f}.")
    if remaining is not None:
        stats_lines.append(
            f"Остаток от лимита (лимит минус все учтённые траты): {float(remaining):.2f}."
        )
    if by_cat:
        stats_lines.append("Расходы по категориям:")
        for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
            stats_lines.append(f"  - {_category_ru(k, 'expense')}: {v:.2f}")
    if recent:
        stats_lines.append("Последние операции:")
        for t in recent[:8]:
            ttype = t.get("type", "")
            cat = _category_ru(str(t.get("category", "")), str(ttype))
            stats_lines.append(
                f"  - {ttype} {t.get('amount')} {cat} ({t.get('created_at', '')[:10]})"
            )

    user_content = "\n".join(stats_lines)

    system = (
        "Ты опытный личный финансовый советник. Пиши по-русски, кратко (до 1200 символов), "
        "2–5 абзацев. Используй ТОЛЬКО цифры и факты из предоставленной статистики; "
        "не выдумывай траты или доходы. Дай персональные рекомендации: что сократить, "
        "на что обратить внимание, как улучшить остаток. Без markdown-заголовков #. "
        "Не упоминай названия моделей, API и разработческие термины — пиши для обычного человека."
    )

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            max_tokens=600,
            temperature=0.6,
        )
        choice = resp.choices[0].message.content
        return (choice or "").strip() or "Ассистент не вернул текст. Попробуйте чуть позже."
    except Exception as exc:  # noqa: BLE001
        logger.exception("Advice request failed: %s", exc)
        return "Сейчас не удалось получить ответ ассистента. Попробуйте позже."


def parse_receipt_image(image_bytes: bytes, mime: str = "image/jpeg") -> dict[str, Any] | None:
    """
    По байтам изображения чека извлекает сумму и категорию (внутренние ключи категорий).
    """
    if not config.OPENAI_API_KEY:
        return None

    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    schema_hint = (
        'Ответь строго JSON: {"amount": number, "category_key": one of '
        '[food,transport,entertainment,health,other], "merchant": string or null}'
    )

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты помощник по чекам. По фото чека определи итоговую сумму покупки "
                        "и подбери category_key на английском из списка. "
                        + schema_hint
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Извлеки данные для учёта расхода."},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            max_tokens=300,
            temperature=0.2,
        )
        raw = (resp.choices[0].message.content or "").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            return None
        data = json.loads(raw[start : end + 1])
        amount = float(data.get("amount"))
        if amount <= 0:
            return None
        cat = str(data.get("category_key", "other"))
        if cat not in ("food", "transport", "entertainment", "health", "other"):
            cat = "other"
        merchant = data.get("merchant")
        return {"amount": amount, "category_key": cat, "merchant": merchant}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Receipt parse failed: %s", exc)
        return None
