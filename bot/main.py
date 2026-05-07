import logging
import os
import traceback
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

import handlers
import admin

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error("Käsittelemätön poikkeus:", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ Tapahtui odottamaton virhe.")
        except Exception:
            pass


def main():
    token = os.environ["BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()

    # User commands
    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("help", handlers.help_command))
    app.add_handler(CommandHandler("saldo", handlers.saldo))
    app.add_handler(CommandHandler("kohteet", handlers.kohteet))
    app.add_handler(CommandHandler("vetoa", handlers.vetoa))
    app.add_handler(CommandHandler("uusiveto", handlers.uusiveto))
    app.add_handler(CommandHandler("poistakohde", handlers.poistakohde))
    app.add_handler(CommandHandler("omat", handlers.omat))
    app.add_handler(CommandHandler("tulokset", handlers.tulokset))

    # Admin commands
    app.add_handler(CommandHandler("admin", admin.register))
    app.add_handler(CommandHandler("lukitse", admin.lukitse))
    app.add_handler(CommandHandler("ratkaise", admin.ratkaise))
    app.add_handler(CommandHandler("lopeta", admin.lopeta_confirm))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(admin.admin_callback, pattern=r"^adm:"))
    app.add_handler(CallbackQueryHandler(handlers.nav_callback, pattern=r"^nav:"))
    app.add_handler(CallbackQueryHandler(handlers.bet_type_callback, pattern=r"^bet_type:"))
    app.add_handler(CallbackQueryHandler(handlers.bet_side_callback, pattern=r"^bet:"))
    app.add_handler(CallbackQueryHandler(handlers.winner_opt_callback, pattern=r"^opt:"))
    app.add_handler(CallbackQueryHandler(handlers.cancel_wager_callback, pattern=r"^wager:cancel:"))

    # ForceReply / free-text input (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text_message))

    app.add_error_handler(error_handler)

    logger.info("boogieBet käynnissä...")
    app.run_polling()


if __name__ == "__main__":
    main()
