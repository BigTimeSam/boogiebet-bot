import os
import functools

_HEADER_TEMPLATE = (
    "🎰 boogieBet {version} – On aika selvittää, kuka tietää ja kuka ei (vaikka proffahan sen tietää).\n"
    "Sinulla on käytössäsi 1000 €, jotka tulee panostaa eri kohteisiin. Minimipanos on 20 € ja maksimipanos 200 € per kohde. Kaikkia rahoja ei ole pakko panostaa, ja voit vaihtaa mielipidettäsi, mutta jo lyödyn vedon cashout palauttaa vain 95 % rahoista takaisin saldoon. Onnea matkaan ja kepulein voittakoon! 🍀\n\n"
    "⚠️ Lanien aikana julkaistaan uusia kohteita ja mm. kaikista CS2- ja Dota-matseista on tarkoitus tulla omat vetokohteensa. Muistathan siis jättää myös vapaata saldoa, jotta voit osallistua näihin eivätkä kaikki rahasi ole jumissa koko lanien pituisissa vedoissa."
)


@functools.lru_cache(maxsize=1)
def _header() -> str:
    version = os.environ.get("APP_VERSION", "v1.0.0")
    return _HEADER_TEMPLATE.format(version=version)


def H(text: str) -> str:
    return _header() + "\n\n" + text


WELCOME_NEW = "Tervetuloa, {name}!\n\nSaldo: {balance:.0f} €"

WELCOME_BACK = "Saldo: {balance:.0f} €"

WAGER_STATS = "Avoimissa vedoissa: {wagered:.0f} €. Jos kaikki vetosi osuvat, voit voittaa {potential:.0f} €."

BALANCE = "💰 Saldosi: {balance:.0f} €"

NO_BETS = "Ei vetokohteita vielä. Tee valitus orgalle."

ALL_BETS_LOCKED = "Kaikki vetokohteet ovat lukittuja eikä niihin voi enää asettaa vetoja. Seuraa tiedotuksia, kun uusia vetokohteita avataan."

BET_LIST_HEADER = "🎯 = Olet panostanut kyseiseen kohteeseen tätä valintaa.\n\n📋 Vetokohteet\n\n"

BET_ROW_OPEN = "#{id} {title}\n   Kyllä @ {yes_odds:.2f}  |  Ei @ {no_odds:.2f}\n\n"

BET_ROW_OPEN_WITH_WAGER = "#{id} {title}\n   Kyllä @ {yes_odds:.2f}  |  Ei @ {no_odds:.2f}\n   ✅ Vetosi: {side} {amount:.0f} €\n\n"

BET_ROW_LOCKED = "#{id} 🔒 {title}\n   Kyllä @ {yes_odds:.2f}  |  Ei @ {no_odds:.2f}  · lukittu\n\n"

BET_ROW_LOCKED_WITH_WAGER = "#{id} 🔒 {title}\n   Kyllä @ {yes_odds:.2f}  |  Ei @ {no_odds:.2f}\n   ✅ Vetosi: {side} {amount:.0f} €  · lukittu\n\n"

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
    "Saldosi: {balance:.0f} €{existing}\n\n"
    "Syötä vetosumma euroissa ({amount_hint}):"
)

WAGER_PLACED = "✅ Veto lyöty!\n#{bet_id} {title} {side_icon} {side}\nPanos: {amount:.0f} € @ {odds:.2f} | Voit voittaa: {payout:.0f} €\n\nSaldosi nyt: {balance:.0f} €"

WAGER_UPDATED = "🔄 Veto päivitetty!\n#{bet_id} {title} {side_icon} {side}\nPanos: {amount:.0f} € @ {odds:.2f} | Voit voittaa: {payout:.0f} €\n\nSaldosi nyt: {balance:.0f} €"

NOT_ENOUGH_BALANCE = "❌ Ei tarpeeksi saldoa! Saldosi: {balance:.0f} €"

MAX_WAGER_EXCEEDED = "❌ Vetosumman täytyy olla {min:.0f}–{max:.0f} €."

BET_CREATED = "✅ Vetokohde luotu (lukittuna)!\n\n#{id}: {title}\n✅ Kyllä @ {yes_odds:.2f} | ❌ Ei @ {no_odds:.2f}\n\n🔒 Kohde on lukittu — avaa se admin-paneelista kun haluat sallia vedot. Pelaajille lähetetään ilmoitus kun kohde avataan ensimmäistä kertaa."

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

MY_WAGERS_HEADER = "🎲 Omat vetosi\n\n"

WAGER_ROW = "#{bet_id} {title}\n{icon} {side} – {amount:.0f} € @ {odds:.2f}{extra}\n\n"

LEADERBOARD_HEADER = "🏆 Tulostaulu\n\n"

LEADERBOARD_ROW_NO_WAGERS = "{rank}. {username}: {balance:.0f} € (0 vetoa)\n"
LEADERBOARD_ROW_ONE_WAGER = "{rank}. {username}: {balance:.0f} € (1 veto, maksimivoitto {potential:.0f} €)\n"
LEADERBOARD_ROW_MANY_WAGERS = "{rank}. {username}: {balance:.0f} € ({count} vetoa, maksimivoitto {potential:.0f} €)\n"

GAME_FINISHED_HEADER = "🏆 Lopulliset tulokset\n\n"

GAME_FINISHED_ROW = "{rank}. {username}: {balance:.0f} €\n"

GAME_FINISHED_NOTICE = "\n🔒 Peli on päättynyt."

GAME_OVER_BLOCK = "❌ Peli on päättynyt, muutoksia ei sallita."

GAME_FINISHED_PERSONAL = "🔒 Peli on päättynyt.\n\nLopullinen saldosi: {balance:.0f} €.\nSija: {rank}/{total}."

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

WINNER_ROW = "🏆 {username}: +{profit:.0f} €\n"

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
    "Vähintään 2, enintään 6 vaihtoehtoa.\n\n"
    "esim.\n"
    "Osmo & Markulov @ 2.80 | Zyrk & Kipe @ 2.50 | Damu & Koala @ 3.00 | Johkis & Winkzi @ 2.75"
)

INVALID_WINNER_OPTIONS = (
    "❌ Tarkista muoto. Vähintään 2 vaihtoehtoa putkella erotettuna:\n"
    "Nimi @ kerroin | Nimi @ kerroin  (kerroin > 1.0)\n\n"
    "esim.\n"
    "Osmo & Markulov @ 2.80 | Zyrk & Kipe @ 2.50 | Damu & Koala @ 3.00 | Johkis & Winkzi @ 2.75"
)

TOO_MANY_WINNER_OPTIONS = "❌ Voittajavedossa voi olla enintään {max} vaihtoehtoa."

WINNER_BET_CREATED = "✅ Voittajaveto luotu (lukittuna)!\n\n#{id}: {title}\n\n{options}\n🔒 Kohde on lukittu — avaa se admin-paneelista kun haluat sallia vedot. Pelaajille lähetetään ilmoitus kun kohde avataan ensimmäistä kertaa."

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

WINNERS_HEADER = "🏆 Voittajat\n\n"

WINNERS_BET_SECTION = "#{id} {title}\nTulos: {result}\n"

WINNERS_NO_PLAYERS = "🚫 Ei voittajia.\n"

WINNERS_NO_RESOLVED = "Ei ratkaistuja kohteita vielä."

ADMIN_PANEL = (
    "🔧 Admin-paneeli\n\n"
    "Kohteiden järjestystä voit vaihtaa asettamalla kohteille painoarvon. "
    "Komennolla /weights näet kaikkien kohteiden nykyiset painot. "
    "Komennolla /weight <id> <paino> asetat yksittäiselle kohteelle painon — "
    "suurempi luku nostaa kohteen korkeammalle Vetokohteet-listalla."
)

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

ASK_WAGER_LIMITS = (
    "#{id} {title}\n\n"
    "Nykyiset panosrajat: min {min:.0f} € – max {max:.0f} €\n\n"
    "Syötä uudet rajat välilyönnillä erotettuna:\n"
    "<min> <max>\n\n"
    "esim.  50 150"
)

WAGER_LIMITS_SET = "✅ Panosrajat asetettu!\n#{id} {title}\nMin: {min:.0f} € – Max: {max:.0f} €"

INVALID_WAGER_LIMITS = (
    "❌ Tarkista panosrajat.\n"
    "Min täytyy olla vähintään 20 € ja max enintään 200 €, ja min ≤ max.\n\n"
    "esim.  50 150  tai  20 20 (kiinteä panos)"
)

ADMIN_ODDS_LIST = "✏️ Valitse kohde jonka kertoimia haluat muuttaa:\n\n(Vain lukitut kohteet ilman vetoja)"

ADMIN_NO_ODDS_BETS = "Ei lukittuja kohteita ilman vetoja."

ODDS_COPY_PASTE_SIMPLE = (
    "✏️ Muokkaa kertoimia — #{id} {title}\n\n"
    "Kopioi alla oleva komento, muokkaa kertoimia ja lähetä takaisin:\n\n"
    "<code>/kertoimet {id} {yes_odds} {no_odds}</code>"
)

ODDS_COPY_PASTE_WINNER = (
    "✏️ Muokkaa kertoimia — #{id} {title}\n\n"
    "Kopioi alla oleva komento, muokkaa kertoimia ja lähetä takaisin:\n\n"
    "<code>/kertoimet {id} {options}</code>"
)

ODDS_UPDATED_SIMPLE = "✅ Kertoimet päivitetty!\n#{id} {title}\nKyllä @ {yes_odds:.2f}  |  Ei @ {no_odds:.2f}"

ODDS_UPDATED_WINNER = "✅ Kertoimet päivitetty!\n#{id} {title}\n\n{options}"

ODDS_UPDATE_FORBIDDEN = "❌ Kertoimia voi muuttaa vain lukituille kohteille joissa ei ole vetoja."

ODDS_UPDATE_BET_NOT_FOUND = "❌ Kohdetta #{id} ei löydy tai se ei ole lukittu ilman vetoja."

NEW_BET_NOTIFICATION_SIMPLE = (
    "🎰 Uusi vetokohde avattu!\n\n"
    "#{id} {title}\n\n"
    "✅ Kyllä @ {yes_odds:.2f}  |  ❌ Ei @ {no_odds:.2f}\n\n"
    "Muista tehdä vetosi ajoissa! 👉 /kohteet"
)

NEW_BET_NOTIFICATION_WINNER = (
    "🎰 Uusi vetokohde avattu!\n\n"
    "#{id} {title}\n\n"
    "{options}\n"
    "Muista tehdä vetosi ajoissa! 👉 /kohteet"
)

INVALID_ODDS_CMD_SIMPLE = (
    "❌ Tarkista muoto: /kertoimet <id> <kyllä_kerroin> <ei_kerroin>\n\n"
    "esim.  /kertoimet 3 2.50 1.40"
)

INVALID_ODDS_CMD_WINNER = (
    "❌ Tarkista muoto: /kertoimet <id> Vaihtoehto @ kerroin | Vaihtoehto @ kerroin | ...\n\n"
    "esim.  /kertoimet 3 Osmo @ 2.80 | Zyrk @ 2.50 | Damu @ 3.00"
)

WEIGHT_LIST_HEADER = "⚖️ Kohteiden painot (suurempi paino = korkeammalle listalla)\n\n"

WEIGHT_ROW = "#{id} {title} — paino: {weight}\n"

WEIGHT_SET = "✅ Paino asetettu!\n#{id} {title} — paino: {weight}"

WEIGHT_SET_FORBIDDEN = "❌ Painon voi asettaa vain aktiivisille kohteille (avoin tai lukittu)."

WEIGHT_NO_BETS = "Ei aktiivisia kohteita."
