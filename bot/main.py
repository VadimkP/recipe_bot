import logging
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from database import init_db
from handlers import (
    start, help_command,
    add_dish_start, add_dish_name, add_dish_ingredients, add_dish_recipe, add_dish_cancel,
    list_dishes, get_recipe_start, get_recipe_select,
    shopping_cart_start, shopping_cart_select,
    delete_dish_start, delete_dish_select,
    WAITING_DISH_NAME, WAITING_INGREDIENTS, WAITING_RECIPE,
    WAITING_RECIPE_SELECTION, WAITING_CART_SELECTION, WAITING_DELETE_SELECTION,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable is not set!")

    init_db()
    logger.info("Database initialized.")

    app = Application.builder().token(token).build()

    # Conversation: add new dish
    add_dish_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_dish_start)],
        states={
            WAITING_DISH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dish_name)],
            WAITING_INGREDIENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dish_ingredients)],
            WAITING_RECIPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dish_recipe)],
        },
        fallbacks=[CommandHandler("cancel", add_dish_cancel)],
    )

    # Conversation: get recipe
    recipe_conv = ConversationHandler(
        entry_points=[CommandHandler("recipe", get_recipe_start)],
        states={
            WAITING_RECIPE_SELECTION: [CallbackQueryHandler(get_recipe_select)],
        },
        fallbacks=[CommandHandler("cancel", add_dish_cancel)],
    )

    # Conversation: shopping cart
    cart_conv = ConversationHandler(
        entry_points=[CommandHandler("cart", shopping_cart_start)],
        states={
            WAITING_CART_SELECTION: [CallbackQueryHandler(shopping_cart_select)],
        },
        fallbacks=[CommandHandler("cancel", add_dish_cancel)],
    )

    # Conversation: delete dish
    delete_conv = ConversationHandler(
        entry_points=[CommandHandler("delete", delete_dish_start)],
        states={
            WAITING_DELETE_SELECTION: [CallbackQueryHandler(delete_dish_select)],
        },
        fallbacks=[CommandHandler("cancel", add_dish_cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_dishes))
    app.add_handler(add_dish_conv)
    app.add_handler(recipe_conv)
    app.add_handler(cart_conv)
    app.add_handler(delete_conv)

    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
