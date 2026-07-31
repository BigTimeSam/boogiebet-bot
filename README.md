# boogieBet

Telegram-veikkausbotti kaveriporukoille. Jokainen pelaaja aloittaa 1 000 €:n virtuaalisaldolla, tekee vetoja adminien luomiin kohteisiin ja paras saldo voittaa.

## Ominaisuudet

- Virtuaalisaldot ja kerroinpohjaiset vedot (min 20 €, max 200 € per kohde, säädettävissä per kohde)
- Kaksi vetotyyppiä: **Kyllä/Ei** ja **Voittajaveto** (useampi vaihtoehto, max 6)
- Adminit luovat, lukitsevat/avaavat ja ratkaisevat vetokohteita — ja voivat **peruuttaa ratkaisun** (voitot peritään takaisin)
- Voitot maksetaan automaattisesti ratkaisun yhteydessä
- Cashout ennen lukitsemista — palauttaa 95 % panoksesta (kokonaisina euroina), kaksivaiheisella vahvistuksella
- Kohteiden järjestys säädettävissä painoarvoilla
- Kertoimien muuttaminen lukituille kohteille joihin ei ole vielä vedetty
- Tulostaulu, **PnL-näkymä** (nettovoitto/-tappio) ja lopulliset tulokset pelin päätyttyä
- Voittajat-näkymä listaa ratkaistujen kohteiden voittajat
- Admin voi lisätä/vähentää saldoa (`/lisaasaldo`) ja merkitä pelaajan kilpailun ulkopuolelle (`/kepuli`)
- Kaikki rahaliikenne kirjataan `balance_events`-tapahtumalokiin (kuka, mitä, milloin)
- Inline-napit kaikkiin keskeisiin toimintoihin

## Vaatimukset

- Docker ja Docker Compose
- Telegram-botti (BotFather)

## Asennus

### 1. Luo Telegram-botti

1. Avaa Telegram ja hae `@BotFather`
2. Lähetä `/newbot` ja seuraa ohjeita
3. Tallenna saatu API-token

### 2. Kloonaa repositorio

```bash
git clone git@github.com:PoggersOy/boogiebet-bot.git
cd boogiebet-bot
```

### 3. Luo ympäristömuuttujat

```bash
cp .env.example .env
```

Täytä `.env`:

```env
BOT_TOKEN=123456789:AAF...       # BotFatherilta saatu token
DATABASE_URL=postgresql://boogiebet:boogiebet@db:5432/boogiebet
ADMIN_PASSWORD=oma_salasana      # Adminirekisteröinnin salasana
APP_VERSION=v1.0.0               # Näytetään botin headerissa
```

> **Huom:** `ADMIN_PASSWORD` on asetettava ei-tyhjäksi. Jos se jätetään tyhjäksi tai pois, adminiksi rekisteröityminen (`/admin <salasana>`) ei onnistu millään salasanalla.

### 4. Käynnistä

```bash
docker compose up -d
```

Tarkista lokit:

```bash
docker compose logs -f bot
```

## Käyttö

> 💡 **Vinkki:** Jos botti tuntuu jumittuneen tai valikko ei vastaa, lähetä `/start` — se päivittää session ja palauttaa sinut päävalikkoon.

### Pelaajana

Aloita lähettämällä `/start` botille. Saat 1 000 €:n virtuaalisaldon ja pääset päävalikkoon.

| Komento | Kuvaus |
|---|---|
| `/start` | Rekisteröidy ja avaa päävalikko (toimii myös session päivitykseen) |
| `/help` | Näytä kaikki komennot |
| `/kohteet` | Selaa vetokohteita ja tee vetoja |
| `/omat` | Näytä omat aktiiviset vetosi |
| `/tulokset` | Tulostaulu |
| `/saldo` | Tarkista oma saldosi |

Vetoja voi tehdä inline-napeilla kohdelistasta. Kohteeseen, johon olet jo panostanut, näkyy 🎯-ikoni valintasi vieressä.

Veto voidaan päivittää ennen kohteen lukitsemista — uusi summa lisätään vanhan päälle (max 200 € yhteensä). Vedon voi peruuttaa **Omat vedot** -sivulta cashoutilla, joka palauttaa 95 % panoksesta.

### Päävalikko

| Nappi | Kuvaus |
|---|---|
| 📋 Kohteet | Avoimet ja lukitut vetokohteet (piilotettu pelin päätyttyä) |
| 🎯 Omat vedot | Omat vedot tiloineen ja voitto/tappio-tiedot; cashout-napit avoimille vedoille |
| 🏆 Tulostaulu | Pelaajat järjestyksessä saldoineen ja maksimivoittoineen |
| 🥇 Voittajat | Ratkaistujen kohteiden voittajat (näkyy kun vähintään yksi kohde ratkaistu) |
| 📈 PnL | Kaikkien pelaajien nettovoitto/-tappio ratkaistuista vedoista |
| 🔧 Admin-paneeli | Pelin hallinta (vain admineille) |

### Adminina

Rekisteröidy adminiksi lähettämällä:

```
/admin <salasana>
```

Saat admin-paneelin, josta hallitset peliä napeilla.

#### Admin-toiminnot (napit)

| Nappi | Kuvaus |
|---|---|
| 🎯 Uusi kohde | Luo uusi vetokohde — valitse tyyppi (Kyllä/Ei tai Voittajaveto), syötä otsikko ja kertoimet |
| ❌ Poista kohde | Poista avoin kohde, vedot palautetaan täysimääräisesti |
| 🔒 Lukitse/vapauta kohde | Vaihda kohteen tila open ↔ locked |
| ✅ Ratkaise kohde | Ratkaise kohde ja maksa voitot automaattisesti |
| ✏️ Muuta kertoimia | Muuta lukitun kohteen kertoimia (vain jos ei yhtään vetoa) |
| 💰 Aseta panosrajat | Muuta avoimen kohteen minimi- ja maksimipanosta |
| 🏁 Lopeta peli | Julkaise lopulliset tulokset (vaatii että kaikki kohteet on ratkaistu) |
| 🔄 Resetoi kaikki | Nollaa kaikki käyttäjät, kohteet ja vedot |

Pelin päätyttyä admin-paneelissa näkyy vain **Resetoi kaikki**.

#### Admin-komennot

| Komento | Kuvaus |
|---|---|
| `/weights` | Listaa kaikki aktiiviset kohteet painoarvoineen |
| `/weight <id> <paino>` | Aseta kohteen painoarvo — suurempi luku nostaa kohteen korkeammalle Vetokohteet-listalla |
| `/kertoimet <id> <kyllä> <ei>` | Muuta Kyllä/Ei-kohteen kertoimet (vain lukittu, 0 vetoa) |
| `/kertoimet <id> Vaihtoehto @ kerroin \| ...` | Muuta voittajavedon kertoimet (vain lukittu, 0 vetoa) |
| `/lisaasaldo <handle\|id> <summa>` | Lisää (tai vähennä, negatiivisella summalla) pelaajan saldoa. Jos nimimerkki ei ole yksikäsitteinen, käytä telegram-id:tä |
| `/kepuli <handle\|id> <summa>` | Merkitse pelaaja viralliselle tulostaululle kuulumattomaksi (käsin lisätty saldo); `0` poistaa merkinnän |
| `/broadcast <viesti>` | Lähetä viesti kaikille pelaajille |

> 🔒 **/admin-yritykset:** viisi väärää salasanaa lukitsee rekisteröitymisen 15 minuutiksi, ja `/admin`-viesti poistetaan heti ettei salasana jää chattiin.

> 💡 **Kertoimien muutos:** Admin-paneelin ✏️-nappi näyttää copy-pastettavan `/kertoimet`-komennon nykyisillä arvoilla. Muokkaa kertoimet ja lähetä takaisin.

#### Vetokohteen elinkaari

```
open → locked → resolved
```

1. **open** — pelaajat voivat tehdä ja päivittää vetoja sekä tehdä cashoutin
2. **locked** — uusia vetoja ei oteta, vanhat jäävät voimaan, cashout ei mahdollinen
3. **resolved** — tulos asetettu, voitot maksettu automaattisesti

#### Vetotyyppit

**Kyllä/Ei** (`simple`): pelaaja valitsee Kyllä- tai Ei-puolen, molemmat saavat omat kertoimensa.

**Voittajaveto** (`winner`): kaksi tai useampi nimetty vaihtoehto omilla kertoimillaan. Pelaaja valitsee yhden vaihtoehdon. Enintään 6 vaihtoehtoa per kohde — 3 tai alle näytetään yhdellä rivillä, 4–6 kahdella rivillä (3+2 tai 3+3).

#### Voiton laskenta

Voittajan saldolle maksetaan **panos × kerroin** (bruttopalautus), josta panos on jo veloitettu vedon lyöntihetkellä. Näkymissä (Omat vedot, PnL, tulossivu) voitto esitetään **nettona** eli `panos × kerroin − panos`. Häviäjät menettävät panoksensa.

#### Pelin lopetus

Admin-paneelin **🏁 Lopeta peli** lopettaa pelin ja julkaisee lopullisen tulostaulun. Kaikki kohteet täytyy ratkaista ennen lopetusta — botti estää lopetuksen jos avoimia tai lukittuja kohteita on jäljellä.

## Tuotantodeploy (CI/CD)

Repositoriossa on GitHub Actions -workflow (`.github/workflows/deploy.yml`), joka deployaa automaattisesti `master`-haaraan pushattaessa.

### Self-hosted runner

Workflow käyttää `prod-docker-01`-palvelimella PoggersOy-organisaatiolle
rekisteröityä yhteistä runneria labelillä `poggersoy-shared`. Tälle
repositoriolle ei rekisteröidä omaa runneria.

### Palvelimen alustus

```bash
sudo mkdir -p /srv/boogiebet-bot
sudo chown deploy:deploy /srv/boogiebet-bot
cd /srv/boogiebet-bot
git clone git@github.com:PoggersOy/boogiebet-bot.git .
# Luo .env tiedosto (ks. Asennus kohta 3)
```

### Deploy-prosessi

1. Push `master`-haaraan käynnistää workflown
2. Runner ajaa `git fetch` + `git checkout` tarkkaan commit-hashiin
3. `docker compose build bot && docker compose up -d db bot`
4. Jokainen onnistunut deploy tagätään automaattisesti (`v1.0.x`)

## Tekninen rakenne

| Tiedosto | Kuvaus |
|---|---|
| `bot/main.py` | Sisääntulopiste, handler-rekisteröinnit |
| `bot/handlers.py` | Käyttäjäkomennot ja inline-callback-handlerit |
| `bot/admin.py` | Admin-komennot ja admin-paneelin callback-handlerit |
| `bot/db.py` | Tietokantaoperaatiot (asyncpg) |
| `bot/texts.py` | Kaikki viestitekstit |
| `init.sql` | Tietokannan skeema |
| `docker-compose.yml` | PostgreSQL + botti-kontit |

## Tietokanta

| Taulu | Kuvaus |
|---|---|
| `users` | Pelaajat, saldot, admin-status, `bonus_balance` (kepuli-merkintä) |
| `bets` | Vetokohteet, tyyppi (`simple`/`winner`), kertoimet, status, tulos, panosrajat, painoarvo, `resolved_by`/`resolved_at` |
| `bet_options` | Voittajavedon vaihtoehdot (label, kerroin, järjestys) |
| `wagers` | Pelaajien vedot — yksi veto per pelaaja per kohde |
| `balance_events` | Append-only rahaliikenteen loki: jokainen saldomuutos syineen ja tekijöineen |
| `settings` | Pelin tila (`game_finished`) |

Skeeman muutokset tehdään `migrations/`-hakemiston numeroituina tiedostoina (ajetaan kerran käynnistyksessä ja kirjataan `schema_migrations`-tauluun), ei `init.sql`:ää muokkaamalla — näin muutokset päätyvät myös olemassa olevaan tuotantokantaan.

## Varmuuskopiot

`db-backup`-palvelu (docker-compose.yml) ajaa `pg_dump`-varmuuskopion päivittäin hakemistoon `./backups`, säilyttäen 14 viimeisintä. Palautus:

```bash
gunzip -c backups/boogiebet_YYYYMMDD_HHMMSS.sql.gz | docker compose exec -T db psql -U boogiebet -d boogiebet
```

## Testit

Integraatiotestit ajetaan oikeaa PostgreSQL-kantaa vasten:

```bash
DATABASE_URL=postgresql://boogiebet:boogiebet@localhost:5432/boogiebet_test python3 -m pytest tests/
```

`DATABASE_URL` on **pakollinen** ja sen on osoitettava kantaan, jonka nimi päättyy `_test` — testit ajavat `TRUNCATE`n ennen jokaista testiä, ja tämä suoja estää tuotantokannan tyhjentämisen vahingossa. Jokainen testi saa puhtaan kannan.
