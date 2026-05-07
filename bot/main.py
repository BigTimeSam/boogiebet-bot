import os
from dotenv import load_dotenv
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

load_dotenv()

import handlers
import admin


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
    app.add_handler(CallbackQueryHandler(handlers.delete_bet_callback, pattern=r"^del:"))
    app.add_handler(CallbackQueryHandler(handlers.cancel_wager_callback, pattern=r"^wager:cancel:"))

    # ForceReply / free-text input (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text_message))

    print("boogieBet käynnissä...")
    app.run_polling()


if __name__ == "__main__":
    main()
