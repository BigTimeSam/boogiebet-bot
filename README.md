# boogieBet

Telegram-veikkausbotti kaveriporukoille. Jokainen pelaaja aloittaa 1 000 €:n virtuaalisaldolla, tekee vetoja adminien luomiin kohteisiin ja paras saldo voittaa.

## Ominaisuudet

- Virtuaalisaldot ja kerroinpohjaiset vedot (min 20 €, max 200 € per kohde)
- Kaksi vetotyyppiä: **Kyllä/Ei** ja **Voittajaveto** (useampi vaihtoehto)
- Adminit luovat, lukitsevat/avaavat ja ratkaisevat vetokohteita
- Voitot maksetaan automaattisesti ratkaisun yhteydessä
- Cashout ennen lukitsemista — palauttaa 95 % panoksesta
- Tulostaulu aktiivisine maksimivoittoineen ja lopulliset tulokset pelin päätyttyä
- Voittajat-näkymä listaa ratkaistujen kohteiden voittajat ja häviäjät
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
git clone git@github.com:BigTimeSam/boogiebet-bot.git
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

### 4. Käynnistä

```bash
docker compose up -d
```

Tarkista lokit:

```bash
docker compose logs -f bot
```

## Käyttö

### Pelaajana

Aloita lähettämällä `/start` botille. Saat 1 000 €:n virtuaalisaldon ja pääset päävalikkoon.

| Komento | Kuvaus |
|---|---|
| `/start` | Rekisteröidy ja avaa päävalikko |
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
| 🎯 Omat vedot | Omat vedot tiloineen ja voitto/tappio-tiedot |
| 🏆 Tulostaulu | Pelaajat järjestyksessä saldoineen ja maksimivoittoineen |
| 🥇 Voittajat | Ratkaistujen kohteiden voittajat ja häviäjät (näkyy kun vähintään yksi kohde ratkaistu) |
| 🔧 Admin-paneeli | Pelin hallinta (vain admineille) |

### Adminina

Rekisteröidy adminiksi lähettämällä:

```
/admin <salasana>
```

Saat admin-paneelin, josta hallitset peliä napeilla.

#### Admin-toiminnot

| Nappi | Kuvaus |
|---|---|
| 🎯 Uusi kohde | Luo uusi vetokohde — valitse tyyppi (Kyllä/Ei tai Voittajaveto), syötä otsikko ja kertoimet |
| ❌ Poista kohde | Poista avoin kohde, vedot palautetaan täysimääräisesti |
| 🔒 Lukitse/vapauta kohde | Vaihda kohteen tila open ↔ locked |
| ✅ Ratkaise kohde | Ratkaise kohde ja maksa voitot automaattisesti |
| 🏁 Lopeta peli | Julkaise lopulliset tulokset (vaatii että kaikki kohteet on ratkaistu) |
| 🔄 Resetoi kaikki | Nollaa kaikki käyttäjät, kohteet ja vedot |

Pelin päätyttyä admin-paneelissa näkyy vain **Resetoi kaikki**.

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

Voitto = panos × kerroin. Häviäjät menettävät panoksensa, voittajat saavat kertoimen mukaisen maksun saldolleen.

#### Pelin lopetus

Admin-paneelin **🏁 Lopeta peli** lopettaa pelin ja julkaisee lopullisen tulostaulun. Kaikki kohteet täytyy ratkaista ennen lopetusta — botti estää lopetuksen jos avoimia tai lukittuja kohteita on jäljellä.

## Tuotantodeploy (CI/CD)

Repositoriossa on GitHub Actions -workflow (`.github/workflows/deploy.yml`), joka deployaa automaattisesti `master`-haaraan pushattaessa.

### Self-hosted runner

Workflow käyttää self-hosted runneria palvelimella. Rekisteröi runner GitHubissa:

**Settings → Actions → Runners → New self-hosted runner**

Lisää label `prod-docker-01` ja käynnistä runnerpalvelu:

```bash
sudo ./svc.sh install && sudo ./svc.sh start
```

### Palvelimen alustus

```bash
sudo mkdir -p /srv/boogiebet-bot
sudo chown deploy:deploy /srv/boogiebet-bot
cd /srv/boogiebet-bot
git clone git@github.com:BigTimeSam/boogiebet-bot.git .
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
| `users` | Pelaajat, saldot, admin-status |
| `bets` | Vetokohteet, tyyppi (`simple`/`winner`), kertoimet, status, tulos |
| `bet_options` | Voittajavedon vaihtoehdot (label, kerroin, järjestys) |
| `wagers` | Pelaajien vedot — yksi veto per pelaaja per kohde |
| `settings` | Pelin tila (`game_finished`) |

## Testit

Integraatiotestit ajetaan oikeaa PostgreSQL-kantaa vasten:

```bash
python3 -m pytest tests/
```

Testit vaativat `DATABASE_URL`-ympäristömuuttujan tai käynnissä olevan Docker Compose -kannan oletusarvoilla (`localhost:5432`). Jokainen testi saa puhtaan kannan — data nollataan ennen jokaista testiä.
