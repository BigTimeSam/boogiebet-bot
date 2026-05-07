import os
import functools

_HEADER_TEMPLATE = (
    "🎰 boogieBet {version} – On aika selvittää, kuka tietää ja kuka ei "
    "(vaikka proffahan sen tietää). Sinulla on 1000 €, jotka tulee panostaa eri kohteisiin. "
    "Minimipanos on 1 € ja maksimipanos 200 € per kohde. Kaikkia rahoja ei ole pakko panostaa, "
    "ja voit vaihtaa mielipidettäsi, mutta jo lyödyn vedon cashout palauttaa vain 95 % rahoista "
    "takaisin saldoon. Onnea matkaan! 🍀"
)


@functools.lru_cache(maxsize=1)
def _header() -> str:
    version = os.environ.get("APP_VERSION", "v1.0.0")
    return _HEADER_TEMPLATE.format(version=version)


def H(text: str) -> str:
    return _header() + "\n\n" + text


WELCOME_NEW = "Tervetuloa, {name}!\n\nSaldo: {balance:.2f} €"

WELCOME_BACK = "Saldo: {balance:.2f} €"

WAGER_STATS = "Avoimissa vedoissa: {wagered:.2f} €. Jos kaikki vetosi osuvat, voit voittaa {potential:.2f} €."

BALANCE = "💰 Saldosi: {balance:.2f} €"

NO_BETS = "Ei vetokohteita vielä. Tee valitus orgalle."

BET_LIST_HEADER = "📋 Vetokohteet\n\n"

BET_ROW_OPEN = "#{id} {title}\n   Kyllä @ {yes_odds:.2f}  |  Ei @ {no_odds:.2f}\n\n"

BET_ROW_OPEN_WITH_WAGER = "#{id} {title}\n   Kyllä @ {yes_odds:.2f}  |  Ei @ {no_odds:.2f}\n   ✅ Vetosi: {side} {amount:.2f} €\n\n"

BET_ROW_LOCKED = "#{id} 🔒 {title}\n   Kyllä @ {yes_odds:.2f}  |  Ei @ {no_odds:.2f}  · lukittu\n\n"

BET_ROW_LOCKED_WITH_WAGER = "#{id} 🔒 {title}\n   Kyllä @ {yes_odds:.2f}  |  Ei @ {no_odds:.2f}\n   ✅ Vetosi: {side} {amount:.2f} €  · lukittu\n\n"

ASK_BET_TITLE = (
    "Uusi vetokohde — vaihe 1/2\n\n"
    "Syötä kohteen nimi:"
)

ASK_BET_ODDS = (
    "Uusi vetokohde — vaihe 2/2\n\n"
    "Kohde: {title}\n\n"
    "Syötä kertoimet välilyönnillä erotettuna:\n"
    "<kyllä_kerroin> <ei_kerroin>\n\n"
    "esim.  3.50 1.25"
)

ASK_AMOUNT = (
    "#{bet_id} {title}\n"
    "Valitsit: {side} @ {odds:.2f}\n"
    "Saldosi: {balance:.2f} €{existing}\n\n"
    "Syötä vetosumma euroissa ({min:.0f}–{max:.0f} €):"
)

WAGER_PLACED = "✅ Veto tehty!\n#{bet_id} {side} {amount:.2f} € @ {odds:.2f}\nVoitat: {payout:.2f} €\n\nSaldosi nyt: {balance:.2f} €"

WAGER_UPDATED = "🔄 Veto päivitetty!\n#{bet_id} {side} {amount:.2f} € @ {odds:.2f}\nVoitat: {payout:.2f} €\n\nSaldosi nyt: {balance:.2f} €"

NOT_ENOUGH_BALANCE = "❌ Ei tarpeeksi saldoa! Saldosi: {balance:.2f} €"

MAX_WAGER_EXCEEDED = "❌ Vetosumman täytyy olla {min:.0f}–{max:.0f} €."

BET_CREATED = "✅ Vetokohde luotu!\n\n#{id}: {title}\nKyllä @ {yes_odds:.2f}  |  Ei @ {no_odds:.2f}"

BET_DELETED = "🗑️ Vetokohde #{id} poistettu. Mahdolliset vedot palautettu."

BET_DELETE_FORBIDDEN = "❌ Vain avoimia kohteita voi poistaa."

BET_NOT_FOUND = "Vetokohdetta #{id} ei löydy."

BET_LOCKED = "🔒 Vetokohde #{id} on lukittu, uusia vetoja ei oteta."

BET_RESOLVED = "🏁 Vetokohde #{id} on jo ratkaistu."

BET_LOCKED_OK = "🔒 Vetokohde #{id} lukittu. Ei enää muutoksia tai vetoja."

BET_ALREADY_LOCKED = "Vetokohde on jo lukittu tai ratkaistu."

INVALID_SIDE = "Valitse 'kyllä' tai 'ei'."

INVALID_AMOUNT = "❌ Syötä kokonaisluku euroissa (esim. 50 tai 200)."

INVALID_ODDS = "❌ Kertoimien täytyy olla lukuja suurempia kuin 1.0 (esim. 3.50 1.25)."

INVALID_COMMAND = "Väärä komento. Käytä: {usage}"

NO_WAGERS = "Sinulla ei ole aktiivisia vetoja."

MY_WAGERS_HEADER = "🎯 Omat vetosi\n\n"

WAGER_ROW = "#{bet_id} {title}\n   {side} {amount:.2f} € @ {odds:.2f} · {status}\n\n"

LEADERBOARD_HEADER = "🏆 Tulostaulu\n\n"

LEADERBOARD_ROW = "{rank}. {username}: {balance:.2f} €\n"

GAME_FINISHED_HEADER = "🏆 Lopulliset tulokset\n\n"

GAME_FINISHED_NOTICE = "\n🔒 Peli on päättynyt. Muutoksia ei enää sallita."

GAME_OVER_BLOCK = "❌ Peli on päättynyt, muutoksia ei sallita."

ADMIN_WELCOME = "✅ Sinut on rekisteröity adminiksi!"

ADMIN_ALREADY = "Olet jo admin."

WRONG_PASSWORD = "❌ Väärä salasana."

ADMIN_HELP = (
    "🔧 Admin-komennot\n\n"
    "/lukitse <id>\n"
    "  → lukitse vetokohde (ei enää vetoja tai muutoksia)\n\n"
    "/ratkaise <id> <kyllä|ei>\n"
    "  → ratkaise lukittu kohde ja maksa voitot\n\n"
    "/lopeta\n"
    "  → lopeta peli ja julkaise lopulliset tulokset\n\n"
    "/admin <salasana>\n"
    "  → rekisteröidy adminiksi"
)

BET_RESOLVED_MSG = (
    "🏁 Vetokohde #{id} ratkaistu!\n\n"
    "{title}\n"
    "Tulos: {result}\n\n"
    "Voittajat:\n{winners}"
)

NO_WINNERS = "  Ei voittajia tässä kohteessa."

WINNER_ROW = "  {username}: +{profit:.2f} € → {balance:.2f} €\n"

NOT_ADMIN = "❌ Tämä komento on vain admineille."

CANCEL_CREATION = "Luonti peruttu."

ASK_BET_TYPE = (
    "Uusi vetokohde\n\n"
    "Nimi: {title}\n\n"
    "Valitse vetotyyppi:"
)

ASK_WINNER_OPTIONS = (
    "Voittajaveto — vaihe 2/2\n\n"
    "Kohde: {title}\n\n"
    "Syötä vaihtoehdot putkimerkillä erotettuna muodossa:\n"
    "Nimi @ kerroin | Nimi @ kerroin | ...\n\n"
    "esim.\n"
    "Suomi @ 3.50 | Ruotsi @ 2.00 | Saksa @ 4.50"
)

INVALID_WINNER_OPTIONS = (
    "❌ Tarkista muoto. Vähintään 2 vaihtoehtoa putkella erotettuna:\n"
    "Nimi @ kerroin | Nimi @ kerroin  (kerroin > 1.0)\n\n"
    "esim.\n"
    "Suomi @ 3.50 | Ruotsi @ 2.00 | Saksa @ 4.50"
)

WINNER_BET_CREATED = "✅ Voittajaveto luotu!\n\n#{id}: {title}\n\n{options}"

HELP_TEXT = (
    "📖 Komennot\n\n"
    "/start — rekisteröidy ja avaa päävalikko\n"
    "/kohteet — selaa vetokohteita ja tee vetoja\n"
    "/omat — näytä omat aktiiviset vetosi\n"
    "/tulokset — tulostaulu ja saldot\n"
    "/saldo — tarkista oma saldosi\n"
    "/help — näytä tämä ohje\n\n"
    "Voit myös käyttää nappeja päävalikossa 👇"
)

ADMIN_PANEL = "🔧 Admin-paneeli"

ADMIN_LOCK_LIST = "🔒 Valitse lukittava kohde:"

ADMIN_RESOLVE_LIST = "✅ Valitse ratkaistava kohde:"

ADMIN_RESOLVE_SIDE = "#{id} {title}\n\nMikä oli tulos?"

ADMIN_FINISH_CONFIRM = "⚠️ Haluatko varmasti lopettaa pelin?\n\nTätä ei voi peruuttaa."

ADMIN_NO_OPEN_BETS = "Ei avoimia kohteita lukittavaksi."

ADMIN_NO_LOCKED_BETS = "Ei lukittuja kohteita ratkaistaksi."

ADMIN_RESET_CONFIRM = (
    "⚠️ Haluatko varmasti nollata pelin?\n\n"
    "Tämä poistaa kaikki käyttäjät, vetokohteet ja vedot — myös adminit. "
    "Toimintoa ei voi peruuttaa."
)

ADMIN_RESET_DONE = "✅ Peli nollattu! Kaikki käyttäjät, vetokohteet ja vedot poistettu."
