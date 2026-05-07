import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import (
    add_dish, get_all_dishes, get_dish_by_id,
    get_ingredients_for_dishes, delete_dish, dish_exists
)
from classifier import classify_ingredient, get_all_categories, DEFAULT_CATEGORY

logger = logging.getLogger(__name__)

# ConversationHandler states
WAITING_DISH_NAME = 1
WAITING_INGREDIENTS = 2
WAITING_RECIPE = 3
WAITING_RECIPE_SELECTION = 4
WAITING_CART_SELECTION = 5
WAITING_DELETE_SELECTION = 6

import re

_UNITS = {
    "г", "гр", "кг",
    "мл", "л", "литр", "литра", "литров",
    "шт", "шт.",
    "ст.л", "ст.л.", "стл", "ч.л", "ч.л.", "чл",
    "ст", "стак", "стакан", "стакана", "стаканов",
    "щепотка", "щепотки", "щепоток", "щепотк", "щепот",
    "пучок", "пучка", "пучков", "пуч",
    "зубчик", "зубчика", "зубчиков", "зубч",
    "долька", "дольки", "долек", "долк",
    "кусок", "куска", "кусков", "кус",
    "пачка", "пачки", "пачек", "пач",
    "банка", "банки", "банок", "бан",
    "горсть", "горсти", "горст",
    "ломтик", "ломтика", "ломтиков", "ломт",
    "веточка", "веточки", "веточек", "ветк",
    "щепотк", "щепот",
}


def _norm(s: str) -> str:
    """Нижний регистр без точек для сравнения с _UNITS."""
    return s.lower().replace(".", "")


def _is_amount_token(s: str) -> bool:
    """Токен выглядит как число или единица измерения?"""
    s = s.strip(".,")
    if re.match(r'^\d', s):
        return True
    if _norm(s) in _UNITS:
        return True
    return False


def _extract_amount_tokens(parts: list[str]) -> tuple[str, str]:
    """
    Из списка токенов жадно забирает с начала всё что похоже на количество.
    Возвращает (amount_str, name_str).
    """
    i = 0
    while i < len(parts) and (i < 3) and _is_amount_token(parts[i]):
        i += 1
    if i == 0:
        return "—", " ".join(parts)
    return " ".join(parts[:i]), " ".join(parts[i:])


def _parse_ingredient_line(line: str) -> tuple[str, str]:
    """
    Поддерживает форматы:
      'Лук – 2 шт.'         -> ('2 шт.', 'Лук')
      'Тортилья 6 шт'       -> ('6 шт', 'Тортилья')
      '500г Куриное филе'   -> ('500г', 'Куриное филе')
      '2 шт Яйцо'           -> ('2 шт', 'Яйцо')
      'по вкусу Соль'       -> ('по вкусу', 'Соль')
      'Соль'                -> ('', 'Соль')
    """
    line = line.strip()
    if not line:
        return "", ""

    # ── Формат 1: "Название – количество единица" (тире-разделитель) ──
    sep_match = re.split(r'\s*[–—]\s*', line, maxsplit=1)
    if len(sep_match) == 2:
        left, right = sep_match[0].strip(), sep_match[1].strip()
        right_parts = right.split()
        if right_parts and _is_amount_token(right_parts[0]):
            amount, _ = _extract_amount_tokens(right_parts)
            return amount, left

    parts = line.split()
    if not parts:
        return "", line

    # ── Формат 2: "по вкусу / на глаз Название" ──
    if parts[0].lower() in {"по", "на"} and len(parts) >= 2:
        amount = " ".join(parts[:2])
        ing_name = " ".join(parts[2:]) if len(parts) > 2 else ""
        return amount, ing_name

    # ── Формат 3: "количество [единица] Название" — число первым ──
    if _is_amount_token(parts[0]):
        return _extract_amount_tokens(parts)

    # ── Формат 4: "Название количество [единица]" — число в конце ──
    # Ищем с конца: берём токены пока они похожи на количество (макс 2)
    i = len(parts) - 1
    tail = 0
    while i >= 0 and tail < 2 and _is_amount_token(parts[i]):
        tail += 1
        i -= 1
    if tail > 0 and i >= 0:
        ing_name = " ".join(parts[:i + 1])
        amount = " ".join(parts[i + 1:])
        return amount, ing_name

    # Ничего не распознали — всё название, количество пустое
    return "", line


INGREDIENT_HELP = (
    "Введи ингредиенты *каждый с новой строки*.\n\n"
    "Поддерживаются оба формата:\n\n"
    "*Название – количество:*\n"
    "`Лук – 2 шт.`\n"
    "`Куриное филе – 500г`\n"
    "`Томатная паста – 4 ст.л`\n\n"
    "*Количество Название:*\n"
    "`500г Куриное филе`\n"
    "`2 шт Яйцо`\n"
    "`по вкусу Соль`\n\n"
    "Категория определяется автоматически 🤖"
)


# ─────────────────────────────────────────
# /start  /help
# ─────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👨‍🍳 *Привет! Я бот-рецептник.*\n\n"
        "Я помогу хранить рецепты и составлять продуктовую корзину.\n\n"
        "Команды:\n"
        "/add — добавить новое блюдо\n"
        "/list — список всех блюд\n"
        "/recipe — получить рецепт блюда\n"
        "/cart — составить продуктовую корзину\n"
        "/delete — удалить блюдо\n"
        "/help — справка"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


# ─────────────────────────────────────────
# /list
# ─────────────────────────────────────────

async def list_dishes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dishes = get_all_dishes()
    if not dishes:
        await update.message.reply_text("📭 Блюд пока нет. Добавь первое с помощью /add")
        return
    lines = "\n".join(f"• {d['name']}" for d in dishes)
    await update.message.reply_text(f"📋 *Все блюда:*\n\n{lines}", parse_mode="Markdown")


# ─────────────────────────────────────────
# /add — добавление блюда (conversation)
# ─────────────────────────────────────────

async def add_dish_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🍽 *Добавляем новое блюдо!*\n\nКак называется блюдо?",
        parse_mode="Markdown"
    )
    return WAITING_DISH_NAME


async def add_dish_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Название слишком короткое. Попробуй ещё раз:")
        return WAITING_DISH_NAME
    if dish_exists(name):
        await update.message.reply_text(
            f"❌ Блюдо *{name}* уже есть в базе. Введи другое название или /cancel для отмены.",
            parse_mode="Markdown"
        )
        return WAITING_DISH_NAME
    context.user_data["dish_name"] = name
    await update.message.reply_text(INGREDIENT_HELP, parse_mode="Markdown")
    return WAITING_INGREDIENTS


async def add_dish_ingredients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        await update.message.reply_text("Список пустой. Введи хотя бы один ингредиент.")
        return WAITING_INGREDIENTS

    ingredients = []
    for line in lines:
        amount, ing_name = _parse_ingredient_line(line)
        category = classify_ingredient(ing_name)
        ingredients.append({"name": ing_name, "amount": amount, "category": category})

    context.user_data["ingredients"] = ingredients

    # Show parsed result
    preview_lines = []
    for i in ingredients:
        amt = i['amount']
        amt_str = f" – {amt}" if amt else ""
        preview_lines.append(f"  • {i['name']}{amt_str} _({i['category']})_")
    preview = "\n".join(preview_lines)
    await update.message.reply_text(
        f"✅ Ингредиенты распознаны:\n{preview}\n\nТеперь введи *рецепт приготовления* (пошагово или текстом):",
        parse_mode="Markdown"
    )
    return WAITING_RECIPE


async def add_dish_recipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    recipe_text = update.message.text.strip()
    if len(recipe_text) < 10:
        await update.message.reply_text("Рецепт слишком короткий. Опиши подробнее:")
        return WAITING_RECIPE

    name = context.user_data["dish_name"]
    ingredients = context.user_data["ingredients"]

    try:
        dish_id = add_dish(name, recipe_text, ingredients)
        await update.message.reply_text(
            f"🎉 Блюдо *{name}* успешно добавлено! (ID: {dish_id})\n\n"
            f"Используй /recipe чтобы найти его, или /add чтобы добавить ещё.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error adding dish: {e}")
        await update.message.reply_text("❌ Ошибка при сохранении. Попробуй ещё раз.")

    context.user_data.clear()
    return ConversationHandler.END


async def add_dish_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END


# ─────────────────────────────────────────
# /recipe — получить рецепт
# ─────────────────────────────────────────

async def get_recipe_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dishes = get_all_dishes()
    if not dishes:
        await update.message.reply_text("📭 Блюд пока нет. Добавь первое с помощью /add")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(d["name"], callback_data=f"recipe_{d['id']}")] for d in dishes]
    await update.message.reply_text(
        "🔍 Выбери блюдо:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAITING_RECIPE_SELECTION


async def get_recipe_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    dish_id = int(query.data.split("_")[1])
    dish = get_dish_by_id(dish_id)
    if not dish:
        await query.edit_message_text("❌ Блюдо не найдено.")
        return ConversationHandler.END

    def _fmt(i):
        amt_str = f" – {i['amount']}" if i['amount'] else ""
        return f"  • {i['name']}{amt_str}"

    ings_text = "\n".join(_fmt(i) for i in dish["ingredients"]) or "  (не указаны)"

    text = (
        f"🍽 *{dish['name']}*\n\n"
        f"📦 *Ингредиенты:*\n{ings_text}\n\n"
        f"👨‍🍳 *Рецепт:*\n{dish['recipe']}"
    )
    await query.edit_message_text(text, parse_mode="Markdown")
    return ConversationHandler.END


# ─────────────────────────────────────────
# /cart — продуктовая корзина
# ─────────────────────────────────────────

async def shopping_cart_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dishes = get_all_dishes()
    if not dishes:
        await update.message.reply_text("📭 Блюд пока нет. Добавь первое с помощью /add")
        return ConversationHandler.END

    context.user_data["cart_selected"] = set()
    context.user_data["cart_dishes"] = {d["id"]: d["name"] for d in dishes}

    keyboard = _build_cart_keyboard(dishes, set())
    await update.message.reply_text(
        "🛒 *Составляем корзину!*\n\nВыбери блюда (можно несколько), затем нажми *«Показать корзину»*:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return WAITING_CART_SELECTION


def _build_cart_keyboard(dishes: list, selected: set) -> list:
    keyboard = []
    for d in dishes:
        label = f"✅ {d['name']}" if d["id"] in selected else d["name"]
        keyboard.append([InlineKeyboardButton(label, callback_data=f"cart_{d['id']}")])
    keyboard.append([InlineKeyboardButton("🛒 Показать корзину", callback_data="show_cart")])
    return keyboard


async def shopping_cart_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    # "Показать корзину" нажата внутри состояния — передаём в show
    if query.data == "show_cart":
        return await shopping_cart_show(update, context)

    await query.answer()

    dish_id = int(query.data.split("_")[1])
    selected: set = context.user_data.get("cart_selected", set())
    if dish_id in selected:
        selected.discard(dish_id)
    else:
        selected.add(dish_id)
    context.user_data["cart_selected"] = selected

    dishes = [{"id": did, "name": name} for did, name in context.user_data["cart_dishes"].items()]
    keyboard = _build_cart_keyboard(dishes, selected)
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    return WAITING_CART_SELECTION


async def shopping_cart_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected: set = context.user_data.get("cart_selected", set())
    if not selected:
        await query.answer("Выбери хотя бы одно блюдо!", show_alert=True)
        return WAITING_CART_SELECTION

    dish_ids = list(selected)
    ingredients = get_ingredients_for_dishes(dish_ids)

    # Group by category
    grouped: dict[str, list] = {}
    for ing in ingredients:
        cat = ing["category"]
        grouped.setdefault(cat, []).append(ing)

    # Sort categories in a nice order
    category_order = list(get_all_categories())

    lines = ["🛒 *Продуктовая корзина:*\n"]
    dish_names = context.user_data.get("cart_dishes", {})
    selected_names = [dish_names[did] for did in dish_ids if did in dish_names]
    lines.append(f"_Блюда: {', '.join(selected_names)}_\n")

    for cat in category_order:
        if cat not in grouped:
            continue
        lines.append(f"\n*{cat}*")
        for ing in grouped[cat]:
            amt = ing['amount']
            amt_str = f" – {amt}" if amt else ""
            lines.append(f"  • {ing['name']}{amt_str}")

    # Any categories not in our order list
    for cat, ings in grouped.items():
        if cat not in category_order:
            lines.append(f"\n*{cat}*")
            for ing in ings:
                amt = ing['amount']
                amt_str = f" – {amt}" if amt else ""
                lines.append(f"  • {ing['name']}{amt_str}")

    await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
    context.user_data.clear()
    return ConversationHandler.END


# ─────────────────────────────────────────
# /delete — удалить блюдо
# ─────────────────────────────────────────

async def delete_dish_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dishes = get_all_dishes()
    if not dishes:
        await update.message.reply_text("📭 Нет блюд для удаления.")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(f"🗑 {d['name']}", callback_data=f"del_{d['id']}")] for d in dishes]
    await update.message.reply_text(
        "🗑 Выбери блюдо для удаления:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAITING_DELETE_SELECTION


async def delete_dish_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    dish_id = int(query.data.split("_")[1])
    dish = get_dish_by_id(dish_id)
    name = dish["name"] if dish else "Блюдо"

    success = delete_dish(dish_id)
    if success:
        await query.edit_message_text(f"✅ Блюдо *{name}* удалено.", parse_mode="Markdown")
    else:
        await query.edit_message_text("❌ Не удалось найти блюдо.")
    return ConversationHandler.END
