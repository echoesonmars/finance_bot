"""OpenAI integration: financial advice and receipt understanding."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from openai import OpenAI

import config

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


def get_financial_advice(user_data: dict[str, Any]) -> str:
    """
    Produce a short personalized advice text in Russian from aggregated stats.
    user_data keys: period_days, currency, budget, total_expense, total_income,
    remaining, expenses_by_category (dict str->float), recent_notes (optional list).
    """
    if not config.OPENAI_API_KEY:
        return (
            "Советы GPT недоступны: не задан OPENAI_API_KEY в .env. "
            "Добавь ключ и перезапусти бота."
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
        f"Период анализа: последние {period} дней.",
        f"Валюта отображения: {currency}.",
        f"Суммарные расходы за период: {total_expense:.2f}.",
        f"Суммарные доходы за период: {total_income:.2f}.",
    ]
    if budget is not None:
        stats_lines.append(f"Установленный бюджет (на период учёта расходов): {float(budget):.2f}.")
    if remaining is not None:
        stats_lines.append(f"Остаток относительно бюджета (бюджет минус расходы за период): {float(remaining):.2f}.")
    if by_cat:
        stats_lines.append("Расходы по категориям:")
        for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
            stats_lines.append(f"  - {k}: {v:.2f}")
    if recent:
        stats_lines.append("Последние операции (кратко):")
        for t in recent[:8]:
            stats_lines.append(
                f"  - {t.get('type')} {t.get('amount')} {t.get('category')} {t.get('created_at', '')[:10]}"
            )

    user_content = "\n".join(stats_lines)

    system = (
        "Ты опытный личный финансовый советник. Пиши по-русски, кратко (до 1200 символов), "
        "2–5 абзацев. Используй ТОЛЬКО цифры и факты из предоставленной статистики; "
        "не выдумывай траты или доходы. Дай персональные рекомендации: что сократить, "
        "на что обратить внимание, как улучшить остаток. Без markdown-заголовков #."
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
        return (choice or "").strip() or "Пустой ответ от модели. Попробуйте позже."
    except Exception as exc:  # noqa: BLE001
        logger.exception("OpenAI advice failed: %s", exc)
        return "Не удалось получить совет от GPT (ошибка API). Попробуйте позже."


def parse_receipt_image(image_bytes: bytes, mime: str = "image/jpeg") -> dict[str, Any] | None:
    """
    Use vision model to extract amount and category from a receipt photo.
    Returns dict with keys: amount (float), category_key (str), merchant (str optional).
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
        logger.exception("OpenAI receipt parse failed: %s", exc)
        return None
