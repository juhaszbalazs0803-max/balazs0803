"""Próba-email küldése a felhőből (a GitHub secretekkel).

Ha épp van élő biztos value bet, a legjobb 1-3-at küldi el az ÉLES formátummal
(javasolt téttel és a tőke %-ával). Ha nincs, egy egyértelműen jelölt PÉLDA
tippet küld, hogy lásd, hogyan néz majd ki az email.

Env: SMTP_USER, SMTP_PASSWORD, TO_EMAIL (mint a többi felhős scriptnél).
"""
import os
from types import SimpleNamespace

from valuebet.notify import EmailNotifier
import notify_cron


def sample_bet():
    """Egy realisztikus PÉLDA value bet a formátum bemutatásához."""
    v = SimpleNamespace(sport_id=66, id=999001, start=None,
                        home="Példa Hazai FC", away="Példa Vendég SC")
    odds = 2.10
    fair_p = 0.50                       # ~5% value ezen az odds-on
    b = {
        "market": "ml",
        "subkey": "ml:home",
        "market_name": "Meccsgyőztes",
        "tip": "1 — Példa Hazai FC",
        "odds": odds,
        "fair_p": fair_p,
        "fair_pct": round(fair_p * 100, 1),
        "value_pct": round((fair_p * odds - 1) * 100, 2),
        "limit": 1500,
        "pinn_url": "https://www.pinnacle.com/",
    }
    return v, b


def main():
    path = "config.json" if os.path.exists("config.json") else "config.example.json"
    cfg = notify_cron.json.load(open(path, encoding="utf-8"))
    n = cfg.setdefault("notify", {})
    n["smtp_user"] = os.environ.get("SMTP_USER", n.get("smtp_user", ""))
    n["smtp_password"] = os.environ.get("SMTP_PASSWORD", n.get("smtp_password", ""))
    n["to_email"] = os.environ.get("TO_EMAIL", n.get("to_email") or n["smtp_user"])

    notifier = EmailNotifier(cfg)
    if not notifier.configured():
        print("HIBA: nincs SMTP beállítva (SMTP_USER / SMTP_PASSWORD / TO_EMAIL).")
        return

    try:
        found, _ = notify_cron.scan(cfg)
    except Exception as e:
        print(f"Keresés hiba (példával folytatom): {e}")
        found = []

    if found:
        found.sort(key=lambda x: -x[2]["value_pct"])
        items = [(v, b) for _, v, b in found[:3]]
        intro = (f"✅ PRÓBA EMAIL – a figyelő működik. Most {len(found)} biztos value "
                 f"tipp van; itt a legjobb {len(items)}. Próbáld ki a 'Megraktam' gombot!")
        subject = f"✅ Próba email – működik ({len(found)} élő tipp)"
    else:
        items = [sample_bet()]
        intro = ("✅ PRÓBA EMAIL – a figyelő működik. Most épp nincs élő biztos value "
                 "tipp, ezért egy PÉLDA tippet mutatok – próbáld ki rajta a 'Megraktam' "
                 "gombot! (Erre a példára ne fogadj.)")
        subject = "✅ Próba email – működik (példa tipp)"

    text, html = notify_cron.build_email(cfg, items, intro)
    notifier.send(subject, text, html)
    print(f"Próba email elküldve: {subject}")


if __name__ == "__main__":
    main()
