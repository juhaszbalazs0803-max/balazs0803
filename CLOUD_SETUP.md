# Email-értesítés kikapcsolt laptop mellett (felhő, ingyenes)

A laptopodon futó alkalmazás csak akkor figyel, ha a gép be van kapcsolva.
Ahhoz, hogy **kikapcsolt laptop mellett is** kapj emailt új tippről, a keresőt a
**GitHub felhőjében** futtatjuk (GitHub Actions) — ez ingyenes.

## Két mód

| Mód | Workflow | Késleltetés | Mikor |
|---|---|---|---|
| **Gyors (ajánlott)** | `value-watch.yml` | ~90 mp | Folyamatosan fut a felhőben (`notify_watch.py` loop). Amint feltűnik egy biztos value bet, pár tíz másodpercen belül jön az email. |
| Lassú (tartalék) | `value-notify.yml` | manuális | Egyszeri keresés (`notify_cron.py`). Az ütemezése ki van kapcsolva, hogy ne küldjön dupla emailt; csak kézzel indítsd. |

**A gyors mód** óránként indít egy ~55 perces figyelő-loopot, ami ~90 mp-enként
keres és AZONNAL emailt küld a saját email-címedre az ÚJAKRÓL.
Az órák között legfeljebb pár perc „vakablak" lehet (a futás újraindulásáig).

> **Fontos – publikus repó kell.** A folyamatos futás csak **publikus** GitHub
> repóban ingyenes/korlátlan (a privátnak havi 2000 perc kerete van, amit ez
> kimerítene). Ezért titok a kódban NINCS – az email és a jelszó GitHub
> *secret*-ből jön (lásd 3. pont), a `config.json` pedig privát adatot ne
> tartalmazzon (a felhőben a `config.example.json` is elég).

> **Még gyorsabb, vakablak nélkül (opcionális, haladó):** ha nulla kiesés kell,
> a `notify_watch.py` változatlanul futtatható egy mindig-bekapcsolt ingyenes
> gépen is: Oracle Cloud „Always Free" VM (systemd/cron loop), vagy Google
> Cloud Run + Cloud Scheduler 1 perces hívással. Ezek fiók-regisztrációt
> igényelnek, de tényleg folyamatosak.

## 1. Gmail App jelszó (egyszer)
1. Kapcsold be a kétlépcsős azonosítást a Google-fiókodon.
2. Menj ide: https://myaccount.google.com/apppasswords
3. Hozz létre egy app jelszót → kapsz egy 16 karakteres kódot (pl. `abcd efgh ijkl mnop`).
   Ezt fogjuk használni (NEM a normál jelszavadat).

## 2. GitHub repó
1. Regisztrálj/lépj be: https://github.com  (ingyenes).
2. Bal fent **New repository** → név pl. `value-bet` → válaszd a **Private**-ot → Create.
3. A repó oldalán: **Add file → Upload files**, és húzd be a teljes `value-bet`
   mappa tartalmát (köztük a `valuebet` mappát, `notify_cron.py`, `config.json`,
   `notified.json`, `requirements.txt` és a `.github` mappát). Commit.
   - Megjegyzés: privát repóban a `config.json`-ban lévő email cím nem publikus.

## 3. Titkok (secrets) megadása
A repóban: **Settings → Secrets and variables → Actions → New repository secret**.
Hozz létre három titkot:
| Név | Érték |
|---|---|
| `SMTP_USER` | a Gmail-címed (pl. `valami@gmail.com`) |
| `SMTP_PASSWORD` | a Gmail **app jelszó** (a 16 karakter, szóközök nélkül is jó) |
| `TO_EMAIL` | a cím, ahová az értesítést kéred (általában ugyanaz) |

## 4. Indítás / ellenőrzés (gyors mód)
- A repó **Actions** fülén látod a **„Value Bet figyelő (gyors)"** workflow-t.
- Első indítás: nyisd meg → **Run workflow** (egyszer kézzel). Ezután óránként
  magától újraindul, és a köztes ~55 percben folyamatosan figyel.
- A futás logjában látod: „Elküldve N ÚJ tipp" / „Nincs új tipp (… biztos)".

## Beállítások
- A felhős kereső a repóban lévő `config.json` (vagy felhőben a
  `config.example.json`) → `live.solid` és `notify` értékeit használja
  (most: limit 500, max 24 óra kezdésig, min. value 3%). A GitHub web felületén
  is szerkesztheted.
- Figyelési sűrűség: `.github/workflows/value-watch.yml` → `POLL_SEC` (alap 90).
  Lejjebb is vihető (pl. 60), de a vegas.hu/Pinnacle terhelése miatt 60 alá ne.

## Korlátok
- Az órák közötti újraindulás miatt legfeljebb pár perc „vakablak" lehet. Élő,
  másodperces követésre továbbra is a laptopos `--web` felület való; a felhős
  figyelő a „ne maradj le róla" célra jó. Teljesen vakablak-mentes változathoz
  lásd a fenti „Még gyorsabb" opciót (Oracle/GCP).
- A GitHub időzítő nem másodperc-pontos, a 0. perces indítás pár percet csúszhat.
- Csak addig fut, amíg a GitHub Actions engedélyezett a repón (alapból igen).
  A GitHub a 60 napja inaktív repók ütemezőjét felfüggeszti – ha sokáig nem
  nyúlsz hozzá, egy kézi „Run workflow" újraélesíti.
