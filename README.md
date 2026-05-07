# boogieBet

Telegram-veikkausbotti kaveriporukoille. Jokainen pelaaja aloittaa 1 000 €:n virtuaalisaldolla, tekee vetoja adminien luomiin kohteisiin ja paras saldo voittaa.

## Ominaisuudet

- Virtuaalisaldot ja kerroinpohjaiset vedot
- Adminit luovat, lukitsevat ja ratkaisevat vetokohteita
- Voitot maksetaan automaattisesti ratkaisun yhteydessä
- Reaaliaikainen tulostaulu
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
| `/kohteet` | Selaa avoimia vetokohteita ja tee vetoja |
| `/omat` | Näytä omat aktiiviset vetosi |
| `/tulokset` | Tulostaulu ja kaikkien saldot |
| `/saldo` | Tarkista oma saldosi |

Vetoja voi tehdä myös inline-napeilla kohdelistasta — valitse kohde, paina **Kyllä** tai **Ei** ja syötä summa.

Veto voidaan muuttaa ennen kohteen lukitsemista. Muutos palauttaa vanhan panoksen saldolle ja veloittaa uuden.

### Adminina

Rekisteröidy adminiksi lähettämällä:

```
/admin <salasana>
```

Saat admin-paneelin, josta hallitset peliä napeilla. Admin-paneeli aukeaa myös aina `/admin`-komennolla.

#### Admin-toiminnot

| Toiminto | Kuvaus |
|---|---|
| **➕ Uusi kohde** | Luo uusi vetokohde (otsikko + kertoimet) |
| **🔒 Lukitse kohde** | Lukitse kohde — ei enää uusia vetoja |
| **✅ Ratkaise kohde** | Ratkaise lukittu kohde, valitse Kyllä tai Ei |
| **🏁 Lopeta peli** | Lopeta peli ja julkaise lopulliset tulokset |

#### Vetokohteen elinkaari

```
open → locked → resolved
```

1. **open** — pelaajat voivat tehdä ja muuttaa vetoja
2. **locked** — uusia vetoja ei oteta, vanhat jäävät voimaan
3. **resolved** — tulos asetettu, voitot maksettu automaattisesti

#### Voiton laskenta

Voitto = panos × kerroin. Häviäjät menettävät panoksensa, voittajat saavat kertoimen mukaisen maksun saldolleen.

#### Pelin lopetus

`/lopeta` (tai admin-paneelin nappi) lopettaa pelin ja julkaisee lopullisen tulostaulun. Jos lukittuja ratkaisemattomia kohteita on jäljellä, botti varoittaa ennen vahvistusta.

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

### Tietokanta

- **users** — pelaajat, saldot, admin-status
- **bets** — vetokohteet, kertoimet, status, tulos
- **wagers** — pelaajien vedot (yksi veto per pelaaja per kohde)
- **settings** — pelin tila (`game_finished`)
