"""Élő value-motor: háttérszálon pollozza a vegas.hu-t és a Pinnacle-t,
párosít, value-t számol minden piacon, és karbantart egy élő állapotot.

Funkciók:
  - több piac: meccsgyőztes, Over/Under, hendikep,
  - tőke (bankroll) alapú javasolt tét (Kelly), minimum 100 Ft,
  - megrakott fogadások mentése, lezárása (nyert/vesztett), egyenleg-görbe.
"""
import json
import math
import os
import threading
import time

from .vegas import VegasClient, SPORT_NAMES
from .pinnacle import PinnacleClient, SPORT_MAP
from .notify import EmailNotifier
from . import matching, compute, value as V

STORE_MIN_VALUE = 0.5  # ennél kisebb value-t nem tárolunk


def _round_stake(x, step=100):
    return int(round(x / step) * step)


class Settings:
    def __init__(self, cfg):
        v = cfg.get("value", {})
        live = cfg.get("live", {})
        self.min_value_pct = v.get("min_value_pct", 3.0)
        self.min_odds = v.get("min_odds", 1.2)
        self.max_odds = v.get("max_odds", 15.0)
        self.kelly_fraction = v.get("kelly_fraction", 0.25)
        self.sports = list(live.get("sports", cfg.get("vegas", {}).get("sport_ids", [66])))
        self.markets = list(live.get("markets", ["ml", "ou", "ah"]))
        self.bankroll = float(live.get("bankroll", 0))
        self.min_bet = float(live.get("min_bet", 100))
        self.only_solid = bool(live.get("only_solid", True))
        self.notify_enabled = bool(cfg.get("notify", {}).get("enabled", False))
        solid = live.get("solid", {})
        self.solid_min_limit = float(solid.get("min_limit", 0))
        self.solid_min_age = float(solid.get("min_age_sec", 12))
        self.solid_max_hours = float(solid.get("max_hours_to_start", 0))

    def to_dict(self):
        return {k: getattr(self, k) for k in
                ("min_value_pct", "min_odds", "max_odds", "kelly_fraction",
                 "sports", "markets", "bankroll", "min_bet", "only_solid",
                 "solid_min_limit", "solid_min_age", "solid_max_hours", "notify_enabled")}

    def update(self, data):
        for k in ("min_value_pct", "min_odds", "max_odds", "kelly_fraction",
                  "bankroll", "min_bet", "solid_min_limit", "solid_min_age",
                  "solid_max_hours"):
            if data.get(k) is not None:
                setattr(self, k, float(data[k]))
        if data.get("only_solid") is not None:
            self.only_solid = bool(data["only_solid"])
        if data.get("notify_enabled") is not None:
            self.notify_enabled = bool(data["notify_enabled"])
        if isinstance(data.get("sports"), list):
            self.sports = [int(x) for x in data["sports"]]
        if isinstance(data.get("markets"), list):
            self.markets = [str(x) for x in data["markets"]]


class ValueEngine:
    def __init__(self, http, cfg, data_path="valuebet_data.json"):
        self.cfg = cfg
        self.vegas = VegasClient(http, cfg["vegas"])
        self.pinnacle = PinnacleClient(http)
        self.devig = cfg.get("reference", {}).get("devig_method", "proportional")
        self.settings = Settings(cfg)
        self.max_plausible = cfg.get("value", {}).get("max_plausible_pct", 30.0)
        live = cfg.get("live", {})
        solid = live.get("solid", {})
        self.solid_min_score = solid.get("min_score", 0.8)
        self.solid_max_odds = solid.get("max_odds", 5.0)
        self.solid_max_value = solid.get("max_value_pct", 20.0)
        self.notifier = EmailNotifier(cfg)
        self.notify_min = cfg.get("notify", {}).get("min_value_pct", 3.0)
        self._notified = set()
        self._notify_armed_at = time.time() + cfg.get("notify", {}).get("arm_after_sec", 30)
        self.poll_interval = live.get("poll_interval_sec", 5)
        self.grace_sec = live.get("grace_sec", 45)
        self.match_cfg = cfg.get("matching", {})
        self.data_path = data_path

        self._lock = threading.RLock()
        self._bets = {}
        self._placed = []
        self._next_id = 1
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.meta = {"last_cycle": None, "last_ok": None, "cycle_ms": 0,
                     "vegas_events": 0, "pinn_events": 0, "matched": 0,
                     "errors": [], "running": False}
        self._load()

    # ---------- perzisztencia ----------
    def _load(self):
        if not os.path.exists(self.data_path):
            return
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if "settings" in d:
                self.settings.update(d["settings"])
            self._placed = d.get("placed", [])
            self._next_id = max([b["id"] for b in self._placed], default=0) + 1
        except Exception:
            pass

    def _save(self):
        try:
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump({"settings": self.settings.to_dict(), "placed": self._placed},
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------- háttérszál ----------
    def start(self):
        self.meta["running"] = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def refresh(self):
        """Azonnali poll-ciklus kérése (Frissítés gomb)."""
        self._wake.set()

    def _loop(self):
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self._cycle()
                self.meta["last_ok"] = time.time()
            except Exception as e:
                self.meta["errors"] = [str(e)]
            self.meta["last_cycle"] = time.time()
            self.meta["cycle_ms"] = int((time.time() - t0) * 1000)
            self._wake.wait(self.poll_interval)
            self._wake.clear()

    def _cycle(self):
        with self._lock:
            sports = list(self.settings.sports)
        max_diff = self.match_cfg.get("max_start_diff_minutes", 90)
        min_score = self.match_cfg.get("min_token_score", 0.6)
        now = time.time()
        seen = set()
        veg_total = pinn_total = matched_total = 0

        for sid in sports:
            pinn_sid = SPORT_MAP.get(sid)
            if not pinn_sid:
                continue
            vegas_events = self.vegas.fetch_sport(sid)
            ref_events = self.pinnacle.fetch_sport(pinn_sid)
            veg_total += len(vegas_events)
            pinn_total += len(ref_events)
            pairs = matching.match_events(vegas_events, ref_events, max_diff, min_score)
            matched_total += len(pairs)

            for ve, re_, swapped, score in pairs:
                for b in compute.compute_bets(ve, re_, swapped, self.devig):
                    val = b["value_pct"]
                    if val < STORE_MIN_VALUE or val > self.max_plausible:
                        continue
                    key = f"{sid}:{ve.id}:{b['subkey']}"
                    seen.add(key)
                    with self._lock:
                        rec = self._bets.get(key)
                        if rec is None:
                            rec = {"key": key, "first_seen": now, "stable_since": now}
                        elif not rec.get("valid", False):
                            # volt érvénytelen/eltűnt -> a stabilitás újraindul
                            rec["stable_since"] = now
                        rec.update({
                            "sport_id": sid, "sport": SPORT_NAMES.get(sid, str(sid)),
                            "event": f"{ve.home} - {ve.away}",
                            "start": ve.start.isoformat() if ve.start else None,
                            "start_ts": ve.start.timestamp() if ve.start else None,
                            "market": b["market"], "market_name": b["market_name"],
                            "tip": b["tip"], "odds": b["odds"], "ref_odds": b["ref_odds"],
                            "fair_odds": b["fair_odds"], "fair_pct": b["fair_pct"],
                            "fair_p": b["fair_p"], "value_pct": val, "league": re_.league,
                            "pinn_url": b.get("pinn_url"), "match_score": score,
                            "limit": b.get("limit", 0), "last_seen": now, "valid": True,
                        })
                        self._bets[key] = rec

        with self._lock:
            for key, rec in list(self._bets.items()):
                if key not in seen:
                    rec["valid"] = False
                if now - rec["last_seen"] > self.grace_sec:
                    del self._bets[key]
                    self._notified.discard(key)
            self.meta.update({"vegas_events": veg_total, "pinn_events": pinn_total,
                              "matched": matched_total, "errors": []})

        self._maybe_notify(now)

    def _is_solid(self, rec, now):
        s = self.settings
        stable = now - rec.get("stable_since", rec["last_seen"])
        hts = (rec["start_ts"] - now) / 3600.0 if rec.get("start_ts") else None
        within = s.solid_max_hours <= 0 or (hts is not None and 0 <= hts <= s.solid_max_hours)
        return (rec.get("valid")
                and rec.get("match_score", 0) >= self.solid_min_score
                and rec["odds"] <= self.solid_max_odds
                and rec["value_pct"] <= self.solid_max_value
                and stable >= s.solid_min_age
                and rec.get("limit", 0) >= s.solid_min_limit
                and within)

    def _maybe_notify(self, now):
        """Új, biztos value tippekről email (a felfutási idő alatt csak előjegyzés)."""
        if not (self.settings.notify_enabled and self.notifier.configured()):
            return
        armed = now >= self._notify_armed_at
        fresh = []
        with self._lock:
            for key, rec in self._bets.items():
                if (self._is_solid(rec, now) and rec["value_pct"] >= self.notify_min
                        and key not in self._notified):
                    self._notified.add(key)
                    if armed:
                        fresh.append(dict(rec))
        if fresh:
            self._send_notification(fresh)

    def _send_notification(self, bets):
        bets.sort(key=lambda r: -r["value_pct"])
        lines = [f"{len(bets)} új biztos value tipp a vegas.hu-n:\n"]
        for b in bets:
            lines.append(
                f"• {b['sport']} | {b['event']}\n"
                f"  {b['market_name']} – {b['tip']}\n"
                f"  Vegas odds {b['odds']:.2f} | value +{b['value_pct']}% "
                f"| Pinnacle limit ${b.get('limit', 0)}\n"
                f"  Ellenőrzés: {b.get('pinn_url', '')}\n")
        subject = f"🟢 {len(bets)} új value tipp (vegas.hu) – legjobb +{bets[0]['value_pct']}%"
        self.notifier.send_async(subject, "\n".join(lines))

    # ---------- tét ----------
    def _stake(self, fair_p, odds):
        s = self.settings
        if s.bankroll <= 0:
            return 0
        full = V.kelly_fraction(fair_p, odds) * s.kelly_fraction
        st = _round_stake(s.bankroll * full)
        if 0 < st < s.min_bet:
            st = int(s.min_bet)
        return st

    # ---------- megrakott fogadások ----------
    def place(self, payload):
        with self._lock:
            rec = {
                "id": self._next_id,
                "ts": time.time(),
                "sport": payload.get("sport", ""),
                "event": payload.get("event", ""),
                "market_name": payload.get("market_name", ""),
                "tip": payload.get("tip", ""),
                "odds": float(payload.get("odds", 0)),
                "stake": int(payload.get("stake", 0)),
                "value_pct": float(payload.get("value_pct", 0)),
                "fair_pct": float(payload.get("fair_pct", 0)),
                "start": payload.get("start"),
                "status": "pending",
                "settled_ts": None,
            }
            self._next_id += 1
            self._placed.append(rec)
            self._save()
            return rec

    def settle(self, bet_id, result):
        with self._lock:
            for b in self._placed:
                if b["id"] == bet_id:
                    b["status"] = result  # won / lost / void / pending
                    b["settled_ts"] = time.time() if result != "pending" else None
                    self._save()
                    return b
        return None

    def delete(self, bet_id):
        with self._lock:
            self._placed = [b for b in self._placed if b["id"] != bet_id]
            self._save()

    def _profit(self, b):
        if b["status"] == "won":
            return b["stake"] * (b["odds"] - 1)
        if b["status"] == "lost":
            return -b["stake"]
        return 0.0

    def _stats(self):
        settled = [b for b in self._placed if b["status"] in ("won", "lost")]
        staked = sum(b["stake"] for b in settled)
        pnl = sum(self._profit(b) for b in settled)
        won = sum(1 for b in settled if b["status"] == "won")
        # egyenleg-görbe a beállított tőkéből indulva, lezárás sorrendjében
        start_bk = self.settings.bankroll
        curve = [{"i": 0, "balance": round(start_bk)}]
        bal = start_bk
        for i, b in enumerate(sorted(settled, key=lambda x: x["settled_ts"] or 0), 1):
            bal += self._profit(b)
            curve.append({"i": i, "balance": round(bal)})
        return {
            "placed_total": len(self._placed), "settled": len(settled),
            "won": won, "lost": len(settled) - won,
            "hit_rate": round(100 * won / len(settled), 1) if settled else 0,
            "staked": round(staked), "pnl": round(pnl),
            "roi": round(100 * pnl / staked, 1) if staked else 0,
            "open_stake": round(sum(b["stake"] for b in self._placed if b["status"] == "pending")),
            "curve": curve,
        }

    # ---------- felület felé ----------
    def snapshot(self):
        with self._lock:
            s = self.settings
            sports, markets = set(s.sports), set(s.markets)
            bets = []
            for rec in self._bets.values():
                if rec["sport_id"] not in sports or rec["market"] not in markets:
                    continue
                if rec["odds"] < s.min_odds or rec["odds"] > s.max_odds:
                    continue
                if rec["value_pct"] < s.min_value_pct:
                    continue
                now_t = time.time()
                stable_sec = now_t - rec.get("stable_since", rec["last_seen"])
                hours_to_start = ((rec["start_ts"] - now_t) / 3600.0
                                  if rec.get("start_ts") else None)
                solid = self._is_solid(rec, now_t)
                if s.only_solid and not solid:
                    continue
                out = {k: v for k, v in rec.items() if k != "fair_p"}
                out["age_sec"] = round(now_t - rec["last_seen"], 1)
                out["stable_sec"] = round(stable_sec)
                out["hours_to_start"] = round(hours_to_start, 1) if hours_to_start is not None else None
                out["status"] = "ÉLŐ" if rec["valid"] else "LEJÁRT"
                out["stake"] = self._stake(rec["fair_p"], rec["odds"])
                out["solid"] = solid
                bets.append(out)
            bets.sort(key=lambda r: (not r["valid"], -r["value_pct"]))
            meta = dict(self.meta)
            meta["now"] = time.time()
            return {"bets": bets, "settings": s.to_dict(), "meta": meta,
                    "placed": list(reversed(self._placed)), "stats": self._stats()}
