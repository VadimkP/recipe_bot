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

INGREDIENT_HELP = (
    "Введи ингредиенты *каждый с новой строки* в формате:\n"
    "`Количество Название`\n\n"
    "Примеры:\n"
    "`500г Куриное филе`\n"
    "`2 шт Яйцо`\n"
    "`1 ст.л. Растительное масло`\n"
    "`по вкусу Соль`\n\n"
    "Категория будет определена автоматически 🤖"
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
        parts = line.split(None, 1)
        if len(parts) == 2:
            amount, ing_name = parts[0], parts[1]
        else:
            amount, ing_name = "—", parts[0]
        category = classify_ingredient(ing_name)
        ingredients.append({"name": ing_name, "amount": amount, "category": category})

    context.user_data["ingredients"] = ingredients

    # Show parsed result
    preview_lines = [f"  • {i['amount']} {i['name']} _({i['category']})_" for i in ingredients]
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

    ings_text = "\n".join(
        f"  • {i['amount']} {i['name']}"
        for i in dish["ingredients"]
    ) or "  (не указаны)"

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
            lines.append(f"  • {ing['amount']} {ing['name']}")

    # Any categories not in our order list
    for cat, ings in grouped.items():
        if cat not in category_order:
            lines.append(f"\n*{cat}*")
            for ing in ings:
                lines.append(f"  • {ing['amount']} {ing['name']}")

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
