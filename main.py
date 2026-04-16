"""
Personal Finance Bot — Telegram entrypoint and message handlers.
"""

from __future__ import annotations

import logging
import re
import sys

import telebot
from telebot import types

import config
import database
import gpt_service
import keyboards
import utils

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# user_id -> FSM dict: step, optional pending amount / receipt data
user_fsm: dict[int, dict] = {}
pending_receipt: dict[int, dict] = {}


def _bot() -> telebot.TeleBot:
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set")
        sys.exit(1)
    return telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, parse_mode=None)


bot = _bot()


def _parse_amount(text: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)", text.replace(" ", ""))
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return v if v > 0 else None


def _welcome_text() -> str:
    return (
        "Привет! Я твой AI-финансист.\n\n"
        "Что я умею:\n"
        "— хранить бюджет и операции в SQLite;\n"
        "— понимать короткие фразы вроде «Такси 200» или «обед 500»;\n"
        "— давать совет по тратам через GPT;\n"
        "— строить график расходов;\n"
        "— принимать фото чека (распознавание через vision, если задан API-ключ).\n\n"
        "Начни с «Установить бюджет» или просто опиши трату текстом."
    )


def _remainder_line(user_id: int) -> str:
    row = database.get_user_row(user_id)
    if not row or row["budget"] is None:
        return "Бюджет ещё не задан — нажми «Установить бюджет»."
    budget = float(row["budget"])
    spent = database.sum_expenses_all_time(user_id)
    cur = str(row["currency"])
    left = budget - spent
    return (
        f"Ок! Остаток: {utils.format_money(left, cur)} "
        f"(бюджет {utils.format_money(budget, cur)}, потрачено всего {utils.format_money(spent, cur)})."
    )


@bot.message_handler(commands=["start"])
def cmd_start(message: types.Message) -> None:
    uid = message.from_user.id
    database.get_or_create_user(uid)
    user_fsm.pop(uid, None)
    pending_receipt.pop(uid, None)
    bot.send_message(
        message.chat.id,
        _welcome_text(),
        reply_markup=keyboards.main_reply_keyboard(),
    )


@bot.message_handler(commands=["help"])
def cmd_help(message: types.Message) -> None:
    bot.send_message(message.chat.id, _welcome_text(), reply_markup=keyboards.main_reply_keyboard())


@bot.message_handler(content_types=["photo"])
def on_photo(message: types.Message) -> None:
    uid = message.from_user.id
    database.get_or_create_user(uid)
    bot.reply_to(message, "Получил фото. Сканирую чек…")

    try:
        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        data = bot.download_file(file_info.file_path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Photo download failed: %s", exc)
        bot.send_message(message.chat.id, "Не удалось скачать изображение. Попробуйте ещё раз.")
        return

    path = file_info.file_path or ""
    mime = "image/jpeg"
    if path.lower().endswith(".png"):
        mime = "image/png"
    elif path.lower().endswith(".webp"):
        mime = "image/webp"

    parsed = gpt_service.parse_receipt_image(data, mime=mime)
    if not parsed:
        bot.send_message(
            message.chat.id,
            "Не удалось распознать чек автоматически. Добавь расход текстом, например: «Магазин 850».",
            reply_markup=keyboards.main_reply_keyboard(),
        )
        return

    amount = float(parsed["amount"])
    cat = str(parsed["category_key"])
    merchant = parsed.get("merchant")
    pending_receipt[uid] = {"amount": amount, "category_key": cat, "merchant": merchant}
    ru = keyboards.EXPENSE_CATEGORIES.get(cat, cat)
    extra = f"\nМагазин: {merchant}" if merchant else ""
    urow = database.get_user_row(uid)
    cur = str(urow["currency"]) if urow else "USD"
    bot.send_message(
        message.chat.id,
        f"Распознано: {utils.format_money(amount, cur)} — {ru}.{extra}\n"
        "Подтвердите запись расхода:",
        reply_markup=keyboards.receipt_confirm_markup(),
    )


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("receipt:"))
def on_receipt_callback(call: types.CallbackQuery) -> None:
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    if call.data == "receipt:cancel":
        pending_receipt.pop(uid, None)
        bot.send_message(
            call.message.chat.id,
            "Запись отменена.",
            reply_markup=keyboards.main_reply_keyboard(),
        )
        return
    if call.data != "receipt:confirm":
        return
    pr = pending_receipt.pop(uid, None)
    if not pr:
        bot.send_message(call.message.chat.id, "Нет данных чека. Пришлите фото снова.")
        return
    note = None
    if pr.get("merchant"):
        note = str(pr["merchant"])
    database.add_transaction(
        uid,
        "expense",
        float(pr["amount"]),
        str(pr["category_key"]),
        note=note,
    )
    bot.send_message(
        call.message.chat.id,
        _remainder_line(uid),
        reply_markup=keyboards.main_reply_keyboard(),
    )


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("pick:"))
def on_pick_category(call: types.CallbackQuery) -> None:
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    parts = call.data.split(":")
    if len(parts) != 3:
        return
    _, kind, cat_key = parts
    st = user_fsm.get(uid) or {}
    if st.get("step") != "pick_category":
        return
    if st.get("tx_kind") != kind:
        return
    amount = float(st["amount"])
    database.add_transaction(uid, kind, amount, cat_key, note=None)
    user_fsm.pop(uid, None)
    bot.send_message(
        call.message.chat.id,
        _remainder_line(uid),
        reply_markup=keyboards.main_reply_keyboard(),
    )


@bot.message_handler(content_types=["text"])
def on_text(message: types.Message) -> None:
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return

    uid = message.from_user.id
    database.get_or_create_user(uid)
    st = user_fsm.get(uid)

    if text == keyboards.BTN_CANCEL:
        user_fsm.pop(uid, None)
        bot.send_message(
            message.chat.id,
            "Ок, отменено.",
            reply_markup=keyboards.main_reply_keyboard(),
        )
        return

    if text == keyboards.BTN_SET_BUDGET:
        user_fsm[uid] = {"step": "budget"}
        bot.send_message(
            message.chat.id,
            "Введите сумму бюджета числом (например 1000):",
            reply_markup=keyboards.cancel_reply_keyboard(),
        )
        return

    if text == keyboards.BTN_ADD_EXPENSE:
        user_fsm[uid] = {"step": "expense_amount"}
        bot.send_message(
            message.chat.id,
            "Введите сумму расхода:",
            reply_markup=keyboards.cancel_reply_keyboard(),
        )
        return

    if text == keyboards.BTN_ADD_INCOME:
        user_fsm[uid] = {"step": "income_amount"}
        bot.send_message(
            message.chat.id,
            "Введите сумму дохода:",
            reply_markup=keyboards.cancel_reply_keyboard(),
        )
        return

    if text == keyboards.BTN_GPT_ADVICE:
        snap = database.get_balance_snapshot(uid, config.DEFAULT_STATS_DAYS)
        row = database.get_user_row(uid)
        budget = float(row["budget"]) if row and row["budget"] is not None else None
        spent_all = database.sum_expenses_all_time(uid)
        remaining = None
        if budget is not None:
            remaining = budget - spent_all
        payload = {
            "period_days": config.DEFAULT_STATS_DAYS,
            "currency": snap["currency"],
            "budget": budget,
            "total_expense": snap["total_expense_period"],
            "total_income": snap["total_income_period"],
            "remaining": remaining,
            "expenses_by_category": snap["expenses_by_category"],
            "recent_transactions": database.get_recent_transactions(uid, 12),
        }
        advice = gpt_service.get_financial_advice(payload)
        bot.send_message(message.chat.id, advice, reply_markup=keyboards.main_reply_keyboard())
        return

    if text == keyboards.BTN_CHARTS:
        buf = utils.build_spending_chart_png(uid, config.DEFAULT_STATS_DAYS)
        bot.send_photo(
            message.chat.id,
            buf,
            caption=f"Расходы по категориям за {config.DEFAULT_STATS_DAYS} дн.",
            reply_markup=keyboards.main_reply_keyboard(),
        )
        return

    if st and st.get("step") == "pick_category":
        bot.send_message(
            message.chat.id,
            "Выберите категорию кнопкой под предыдущим сообщением или нажмите «Отмена».",
            reply_markup=keyboards.cancel_reply_keyboard(),
        )
        return

    if st and st.get("step") == "budget":
        amt = _parse_amount(text)
        if amt is None:
            bot.send_message(message.chat.id, "Нужно положительное число. Пример: 1000")
            return
        row = database.get_user_row(uid)
        cur = str(row["currency"]) if row else "USD"
        database.set_budget(uid, amt, cur)
        user_fsm.pop(uid, None)
        bot.send_message(
            message.chat.id,
            f"Бюджет сохранён: {utils.format_money(amt, cur)}",
            reply_markup=keyboards.main_reply_keyboard(),
        )
        return

    if st and st.get("step") == "expense_amount":
        amt = _parse_amount(text)
        if amt is None:
            bot.send_message(message.chat.id, "Введите сумму числом, например 250")
            return
        user_fsm[uid] = {
            "step": "pick_category",
            "tx_kind": "expense",
            "amount": amt,
        }
        bot.send_message(
            message.chat.id,
            "Выберите категорию расхода:",
            reply_markup=keyboards.category_inline_markup("expense"),
        )
        return

    if st and st.get("step") == "income_amount":
        amt = _parse_amount(text)
        if amt is None:
            bot.send_message(message.chat.id, "Введите сумму числом, например 5000")
            return
        user_fsm[uid] = {
            "step": "pick_category",
            "tx_kind": "income",
            "amount": amt,
        }
        bot.send_message(
            message.chat.id,
            "Выберите категорию дохода:",
            reply_markup=keyboards.category_inline_markup("income"),
        )
        return

    # Free-form: «Такси 200»
    match = utils.match_amount_pattern(text)
    if match:
        logger.debug("Amount pattern matched in: %s", text)
    parsed = utils.parse_expense_text(text)
    if parsed:
        database.add_transaction(
            uid,
            parsed.tx_type,
            parsed.amount,
            parsed.category_key,
            note=parsed.raw_note,
        )
        bot.send_message(
            message.chat.id,
            _remainder_line(uid),
            reply_markup=keyboards.main_reply_keyboard(),
        )
        return

    bot.send_message(
        message.chat.id,
        "Не понял сообщение. Используй кнопки меню или формат «Категория 500».",
        reply_markup=keyboards.main_reply_keyboard(),
    )


def main() -> None:
    database.init_db()
    logger.info("Bot starting…")
    bot.infinity_polling(skip_pending=True, interval=0, timeout=20)


if __name__ == "__main__":
    main()
