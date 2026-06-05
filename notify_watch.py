"""Folyamatos (közel azonnali) figyelő – felhőben vagy lokálisan.

A `notify_cron.py` EGYszer-fut logikáját ismétli egy loopban: alapból ~90
mp-enként keres value betet és AZONNAL emailt küld az ÚJAKRÓL. Így nem kell a
~15-30 perces időzített futásra várni – amint feltűnik egy biztos value bet,
pár tíz másodpercen belül jön az email.

Hol fut:
- A GitHub Actions felhőjében (`.github/workflows/value-watch.yml`), így a
  laptop KIKAPCSOLVA is megy.
- Vagy lokálisan: `python notify_watch.py` (amíg a gép be van kapcsolva).

Dedup: a `notified.json` (közös a cron megoldással), hogy ne spammeljen.

Környezeti változók:
  SMTP_USER, SMTP_PASSWORD, TO_EMAIL  – mint a cronnál (GitHub secrets).
  POLL_SEC          – ennyi mp-enként keres (alap 90).
  MAX_RUNTIME_SEC   – ennyi mp után tisztán kilép (alap 3300 = 55 perc),
                      hogy a CI a következő ütemezett futással folytassa.
"""
import json
import os
import time
import traceback
from datetime import datetime

from valuebet.notify import EmailNotifier
import notify_cron

STATE_FILE = notify_cron.STATE_FILE
KEEP_SEC = notify_cron.KEEP_SEC


def load_config():
    path = "config.json" if os.path.exists("config.json") else "config.example.json"
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    n = cfg.setdefault("notify", {})
    n["smtp_user"] = os.environ.get("SMTP_USER", n.get("smtp_user", ""))
    n["smtp_password"] = os.environ.get("SMTP_PASSWORD", n.get("smtp_password", ""))
    n["to_email"] = os.environ.get("TO_EMAIL", n.get("to_email") or n["smtp_user"])
    return cfg


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def send_email(new, notifier, cfg):
    new.sort(key=lambda x: -x[2]["value_pct"])
    items = [(v, b) for _, v, b in new]
    text, html = notify_cron.build_email(
        cfg, items, f"{len(new)} új biztos value tipp a vegas.hu-n:")
    notifier.send(f"🟢 {len(new)} új value tipp – legjobb +{new[0][2]['value_pct']}%",
                  text, html)


def main():
    cfg = load_config()
    notifier = EmailNotifier(cfg)
    if not notifier.configured():
        print("HIBA: nincs SMTP beállítva (SMTP_USER / SMTP_PASSWORD / TO_EMAIL).")
        return

    poll = int(os.environ.get("POLL_SEC", "90"))
    max_runtime = int(os.environ.get("MAX_RUNTIME_SEC", "3300"))
    started = time.time()
    state = load_state()
    print(f"Figyelő indul: poll={poll}s, futásidő<={max_runtime}s, "
          f"ismert tippek={len(state)}")

    while True:
        cycle = time.time()
        try:
            found, now = notify_cron.scan(cfg)
            state = {k: t for k, t in state.items() if now - t < KEEP_SEC}
            new = [(k, v, b) for (k, v, b) in found if k not in state]

            sent_ok = True
            if new:
                try:
                    send_email(new, notifier, cfg)
                    print(f"[{datetime.now():%H:%M:%S}] Elküldve {len(new)} ÚJ tipp "
                          f"(összes biztos: {len(found)}).")
                except Exception as e:
                    sent_ok = False
                    print(f"[{datetime.now():%H:%M:%S}] [email] HIBA: {e} "
                          f"(újrapróbálom a következő körben)")
            else:
                print(f"[{datetime.now():%H:%M:%S}] Nincs új tipp "
                      f"({len(found)} biztos, mind ismert).")

            # Csak sikeres küldés (vagy nincs új) után jegyezzük ismertnek.
            if sent_ok:
                for k, _, _ in found:
                    state[k] = now
                save_state(state)
        except Exception:
            print(f"[{datetime.now():%H:%M:%S}] Ciklus hiba:\n"
                  + traceback.format_exc())

        if time.time() - started > max_runtime:
            print("Futásidő letelt, tiszta kilépés (a CI folytatja).")
            save_state(state)
            return
        time.sleep(max(5, poll - (time.time() - cycle)))


if __name__ == "__main__":
    main()
