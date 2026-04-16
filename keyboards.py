"""Telegram Reply and Inline keyboards for Personal Finance Bot."""

from telebot import types

# --- Reply keyboard labels (must match handler checks in main.py)
BTN_SET_BUDGET = "Установить бюджет"
BTN_ADD_EXPENSE = "Добавить расход"
BTN_ADD_INCOME = "Добавить доход"
BTN_GPT_ADVICE = "Совет от GPT"
BTN_CHARTS = "Отчёт в графиках"
BTN_CANCEL = "Отмена"


def main_reply_keyboard() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton(BTN_SET_BUDGET),
        types.KeyboardButton(BTN_ADD_EXPENSE),
    )
    kb.add(
        types.KeyboardButton(BTN_ADD_INCOME),
        types.KeyboardButton(BTN_GPT_ADVICE),
    )
    kb.add(types.KeyboardButton(BTN_CHARTS))
    return kb


def cancel_reply_keyboard() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton(BTN_CANCEL))
    return kb


# category_key -> Russian label for UX
EXPENSE_CATEGORIES: dict[str, str] = {
    "food": "Еда",
    "transport": "Транспорт",
    "entertainment": "Развлечения",
    "health": "Здоровье",
    "other": "Прочее",
}

INCOME_CATEGORIES: dict[str, str] = {
    "salary": "Зарплата",
    "gift": "Подарок / бонус",
    "other_income": "Прочий доход",
}


def category_inline_markup(
    tx_kind: str,
    prefix: str = "pick",
) -> types.InlineKeyboardMarkup:
    """tx_kind: 'expense' | 'income'. callback: {prefix}:{kind}:{category_key}"""
    mapping = EXPENSE_CATEGORIES if tx_kind == "expense" else INCOME_CATEGORIES
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton(
            text=label, callback_data=f"{prefix}:{tx_kind}:{key}"
        )
        for key, label in mapping.items()
    ]
    kb.add(*buttons)
    return kb


def receipt_confirm_markup() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("Подтвердить", callback_data="receipt:confirm"),
        types.InlineKeyboardButton("Отмена", callback_data="receipt:cancel"),
    )
    return kb
