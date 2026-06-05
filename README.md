# value-bet — value fogadás kereső a vegas.hu-ra

Lekéri a **vegas.hu** (Altenar sportsbook) odds-ait, összehasonlítja a **Pinnacle**
(a legélesebb fogadóiroda) odds-aival, és kilistázza, hol fizet a vegas.hu **többet,
mint amennyit a tényleges esély indokol** — azaz hol van *value*. Van egy **élő
webes felület** is (`--web`), ami 2 másodpercenként frissül, és jelzi, hogy egy
value bet még **él-e vagy lejárt**.

```
value = valós_valószínűség × odds − 1
```

Ha ez pozitív, value bet. A „valós valószínűséget" a referencia-irodák
odds-aiból becsüljük, miután eltávolítjuk belőlük a margint (vig).

> ⚠️ **Fontos:** csak a vegas.hu odds-aiból nem lehet value-t számolni — kell egy
> független referencia. Enélkül a program a `--list` móddal csak a meccseket és a
> marginokat mutatja.

---

## Telepítés

```powershell
cd C:\Users\LENOVO\value-bet
python -m pip install -r requirements.txt
copy config.example.json config.json
```

## 1) Gyors próba — vegas.hu meccsek és marginok (kulcs NEM kell)

```powershell
python -m valuebet --list                 # az összes beállított sport
python -m valuebet --list --sport 66      # csak foci
```

Példa kimenet:

```
Sport  Idő (UTC)    Meccs                       Odds (1/X/2)     Margin
Foci   06-05 14:00  Azerbajdzsán (N) - ...      9.00/4.50/1.32   9.1%
```

## 2) ⭐ Élő webes felület (`--web`) — ez a fő mód

Pinnacle a referencia, **kulcs nem kell**. A háttérben folyamatosan pollozza a
vegas.hu-t és a Pinnacle-t, a böngészős felület pedig 2 mp-enként frissül.

```powershell
python -m valuebet --web                  # majd nyisd meg: http://127.0.0.1:8765
python -m valuebet --web --port 9000      # más porton
```

**Asztali parancsikon:** az `Value Bet.bat` az asztalon dupla kattintásra elindítja
a szervert és megnyitja a felületet. (Leállítás: zárd be a „Value Bet szerver" ablakot.)

A felületen:
- **Több piac**: meccsgyőztes (1X2/győztes), **Over/Under** (gól/pont szám) és
  **hendikep**. A *Piacok* pipákkal szűrhető.
- **Táblázat** a value betekről, value% szerint rendezve.
- **Státusz**: `ÉLŐ` (zöld) = a value most is fennáll; `LEJÁRT` (piros) = eltűnt vagy
  a value a küszöb alá esett (még pár másodpercig látszik).
- **Tőke (Ft)** mező: ebből számolja a **javasolt tétet** (Kelly × tört), kerekítve,
  minimum 100 Ft. A *Tét (Ft)* oszlopban látod.
- **Megrakom** gomb: elmenti a fogadást. A *Megrakott fogadások* táblában lezárhatod
  **Nyert/Vesztett**-re, és látod a profitot. Mentés lemezre (`valuebet_data.json`),
  túléli az újraindítást.
- **Statisztika + egyenleg-görbe**: P/L, ROI, találati arány, és egy chart, ami a
  beállított tőkéből indulva mutatja az egyenleget a lezárt fogadások alapján.
- **🔒 Csak biztos value**: alapból bekapcsolva — csak a megbízható fogadásokat mutatja
  (tökéletes csapatnév-egyezés, odds ≤ 5, value ≤ 20%, ÉLŐ). Kikapcsolható.
- **Pinnacle odds = kattintható**: a Pinnacle oszlop linkje megnyitja az adott meccset a
  pinnacle.com-on, hogy ellenőrizhesd a valódi odds-ot.
- **Vig nélkül oszlop**: a Pinnacle margin (vig) levonása utáni „valós" odds — a value
  ehhez képest számolódik (a nyers Pinnacle odds is látszik mellette).
- **Szűrők** (élőben állíthatók, mentődnek): min. value %, min./max. odds, Kelly-tört,
  sportok, piacok. Pl. „csak olyan meccs, ahol az odds < 2.5" → *Max. odds* = 2.5.

A frissítési ütem a `config.json` → `live.poll_interval_sec` (alap: 5 mp; 2 alá ne vidd).

## 3) Egyszeri lista a terminálba (Pinnacle-lel is megy)

```powershell
python -m valuebet                        # value betek egyszeri listája
python -m valuebet --min-value 5          # csak 5% feletti value
```

> Megjegyzés: a `--web` mód mindig Pinnacle-t használ. A sima `python -m valuebet`
> (terminál) jelenleg a `reference.provider` szerinti forrást (alapból The Odds API,
> ahhoz kulcs kell) — élő követéshez a `--web` az ajánlott.

---

## Beállítások (`config.json`)

| Kulcs | Jelentés |
|---|---|
| `vegas.sport_ids` | Mely sportokat töltse. 66=Foci, 68=Tenisz, 67=Kosár, 70=Jégkorong, 145=E-sport, 78=Darts, 77=Asztalitenisz, 69=Röplabda |
| `reference.oddsapi_key` | The Odds API kulcs |
| `reference.oddsapi_sport_keys` | Mely ligákat kérje a referenciától (lásd a The Odds API sport-listáját) |
| `reference.devig_method` | `proportional` (egyszerű) vagy `shin` (pontosabb) |
| `value.min_value_pct` | Value% küszöb (alap: 3%) |
| `value.min_odds` / `max_odds` | Odds-tartomány szűrő |
| `value.kelly_fraction` | Tét-szorzó a teljes Kelly-hez (alap: 0.25) |
| `matching.max_start_diff_minutes` | Meccs-párosítás időablaka |
| `http.verify_ssl` | Állítsd `false`-ra, ha SSL hibát kapsz (céges/vírusirtó proxy) |

---

## Hogyan működik

```
vegas.hu  ──GetEvents──▶  VegasClient  ──┐
(Altenar API)                            ├─▶  párosítás (név + idő)  ─▶  value & Kelly  ─▶  tábla
The Odds API ─▶ OddsApiClient (de-vig) ──┘
```

- **`valuebet/vegas.py`** – a vegas.hu Altenar JSON API-ját hívja
  (`hu-sb2frontend-altenar2.biahosted.com`, integration `vegas.hu`). Egy hívás egy
  sport összes előmeccsét visszaadja a fő piac (1X2 / meccsgyőztes) odds-aival.
- **`valuebet/oddsapi.py`** – referencia-odds több irodától; irodánként de-vigeli,
  majd átlagol → konszenzus valós valószínűség.
- **`valuebet/matching.py`** – a két forrás meccseit csapatnév-normalizálással
  (ékezet-mentesítés, alias-ok) és kezdési idő alapján párosítja.
- **`valuebet/value.py`** – margin, value%, Kelly.

## Korlátok / megjegyzések

- **Név-párosítás:** klubcsapatoknál megbízható (Real Madrid, Bayern München→Munich
  stb.), **nemzeti válogatottaknál gyenge** (Magyarország ≠ Hungary). Egzotikus
  meccseket fogadás előtt ellenőrizz. Bővítsd a `matching._ALIASES` szótárat igény szerint.
- **The Odds API lefedettség:** főleg nagy klubligák. Tenisznél/kis ligáknál
  kevés vagy semmi referencia — ezekre nem lesz value-jelzés.
- A vegas.hu odds-ai változnak; a value pillanatkép. Mindig a tényleges szelvényen
  ellenőrizd az odds-ot fogadás előtt.
- Ez elemző eszköz, nem garantál nyereséget. Felelős játék: 18+.
```
