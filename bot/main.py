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
    app.add_handler(CommandHandler("saldo", handlers.cmd_balance))
    app.add_handler(CommandHandler("kohteet", handlers.cmd_bets))
    app.add_handler(CommandHandler("vetoa", handlers.cmd_place_bet))
    app.add_handler(CommandHandler("uusiveto", handlers.cmd_new_bet))
    app.add_handler(CommandHandler("poistakohde", handlers.cmd_delete_bet))
    app.add_handler(CommandHandler("omat", handlers.cmd_my_bets))
    app.add_handler(CommandHandler("tulokset", handlers.cmd_results))

    # Admin commands
    app.add_handler(CommandHandler("admin", admin.register))
    app.add_handler(CommandHandler("lukitse", admin.cmd_lock))
    app.add_handler(CommandHandler("ratkaise", admin.cmd_resolve))
    app.add_handler(CommandHandler("lopeta", admin.cmd_finish_confirm))
    app.add_handler(CommandHandler("kertoimet", admin.cmd_update_odds))
    app.add_handler(CommandHandler("weights", admin.cmd_list_weights))
    app.add_handler(CommandHandler("weight", admin.cmd_set_weight))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(admin.admin_callback, pattern=r"^adm:"))
    app.add_handler(CallbackQueryHandler(handlers.noop_callback, pattern=r"^noop:"))
    app.add_handler(CallbackQueryHandler(handlers.nav_callback, pattern=r"^nav:"))
    app.add_handler(CallbackQueryHandler(handlers.bet_type_callback, pattern=r"^bet_type:"))
    app.add_handler(CallbackQueryHandler(handlers.bet_side_callback, pattern=r"^bet:"))
    app.add_handler(CallbackQueryHandler(handlers.winner_opt_callback, pattern=r"^opt:"))
    app.add_handler(CallbackQueryHandler(handlers.cancel_input_callback, pattern=r"^input:cancel"))
    app.add_handler(CallbackQueryHandler(handlers.cancel_wager_callback, pattern=r"^wager:cancel:"))

    # ForceReply / free-text input (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text_message))

    app.add_error_handler(error_handler)

    logger.info("boogieBet käynnissä...")
    app.run_polling()


if __name__ == "__main__":
    main()
