"""Oracle System — prediction-backed truth arbitration for the mesh.

Oracle Rep is a separate reputation tier earned ONLY by:
  1. Correctly predicting outcomes on Kalshi/Polymarket-sourced markets
  2. Winning truth stakes on posts/comments

Oracle Rep can be staked on posts to protect them from mob downvoting.
Other oracles can counter-stake. After the stake period (1-7 days),
whichever side has more oracle rep staked wins. Losers' rep is divided
proportionally among winners.

Scoring formula for predictions:
  oracle_rep_earned = 1.0 - probability_of_chosen_outcome / 100
  - Bet YES at 99% → earn 0.01 (trivial, everyone knew)
  - Bet YES at 50% → earn 0.50 (genuine uncertainty, real insight)
  - Bet YES at 10% → earn 0.90 (contrarian genius if correct)

Designed for AI game theory: this mechanism works identically
whether participants are humans, AI agents, or a mix.

Persistence: JSON files in backend/data/ (auto-saved on change).
"""

import json
import time
import logging
import secrets
import threading
import atexit
from pathlib import Path
from typing import Optional

logger = logging.getLogger("services.mesh_oracle")

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
ORACLE_FILE = DATA_DIR / "oracle_ledger.json"

# ─── Constants ────────────────────────────────────────────────────────────

MIN_STAKE_DAYS = 1  # Minimum stake duration
MAX_STAKE_DAYS = 7  # Maximum stake duration
GRACE_PERIOD_HOURS = 24  # Counter-stakers get 24h after any new stake
ORACLE_DECAY_DAYS = 90  # Oracle rep decays over 90 days like regular rep


class OracleLedger:
    """Oracle reputation ledger — predictions, stakes, and truth arbitration.

    Storage:
      oracle_rep:   {node_id: float}           — current oracle rep balances
      predictions:  [{node_id, market_title, side, probability_at_bet, timestamp, resolved, correct, rep_earned}]
      stakes:       [{stake_id, message_id, poster_id, staker_id, side ("truth"|"false"),
                      amount, duration_days, created_at, expires_at, resolved}]
      prediction_log: [{node_id, market_title, side, probability_at_bet, rep_earned, timestamp}]
    """

    def __init__(self):
        self.oracle_rep: dict[str, float] = {}
        self.predictions: list[dict] = []
        self.market_stakes: list[dict] = []  # Rep staked on prediction markets
        self.stakes: list[dict] = []  # Truth stakes on posts (separate system)
        self.prediction_log: list[dict] = []  # Public log of all predictions
        self._dirty = False
        self._save_lock = threading.Lock()
        self._save_timer: threading.Timer | None = None
        self._SAVE_INTERVAL = 5.0
        atexit.register(self._flush)
        self._load()

    # ─── Persistence ──────────────────────────────────────────────────

    def _load(self):
        if ORACLE_FILE.exists():
            try:
                data = json.loads(ORACLE_FILE.read_text(encoding="utf-8"))
                self.oracle_rep = data.get("oracle_rep", {})
                self.predictions = data.get("predictions", [])
                self.market_stakes = data.get("market_stakes", [])
                self.stakes = data.get("stakes", [])
                self.prediction_log = data.get("prediction_log", [])
                logger.info(
                    f"Loaded oracle ledger: {len(self.oracle_rep)} oracles, "
                    f"{len(self.predictions)} predictions, "
                    f"{len(self.market_stakes)} market stakes, {len(self.stakes)} truth stakes"
                )
            except Exception as e:
                logger.error(f"Failed to load oracle ledger: {e}")

    def _save(self):
        """Mark dirty and schedule a coalesced disk write."""
        self._dirty = True
        with self._save_lock:
            if self._save_timer is None or not self._save_timer.is_alive():
                self._save_timer = threading.Timer(self._SAVE_INTERVAL, self._flush)
                self._save_timer.daemon = True
                self._save_timer.start()

    def _flush(self):
        """Actually write to disk (called by timer or atexit)."""
        if not self._dirty:
            return
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "oracle_rep": self.oracle_rep,
                "predictions": self.predictions,
                "market_stakes": self.market_stakes,
                "stakes": self.stakes,
                "prediction_log": self.prediction_log,
            }
            ORACLE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._dirty = False
        except Exception as e:
            logger.error(f"Failed to save oracle ledger: {e}")

    # ─── Oracle Rep ───────────────────────────────────────────────────

    def get_oracle_rep(self, node_id: str) -> float:
        """Get current oracle rep for a node (excludes locked/staked amount)."""
        total = self.oracle_rep.get(node_id, 0.0)
        # Subtract locked truth stakes on posts
        locked = sum(
            s["amount"]
            for s in self.stakes
            if s["staker_id"] == node_id and not s.get("resolved", False)
        )
        # Subtract locked market stakes
        locked += sum(
            s["amount"]
            for s in self.market_stakes
            if s["node_id"] == node_id and not s.get("resolved", False)
        )
        return round(max(0, total - locked), 3)

    def get_total_oracle_rep(self, node_id: str) -> float:
        """Get total oracle rep including locked stakes."""
        return round(self.oracle_rep.get(node_id, 0.0), 3)

    def _add_oracle_rep(self, node_id: str, amount: float):
        """Add oracle rep to a node."""
        self.oracle_rep[node_id] = self.oracle_rep.get(node_id, 0.0) + amount

    def _remove_oracle_rep(self, node_id: str, amount: float):
        """Remove oracle rep from a node (floor at 0)."""
        self.oracle_rep[node_id] = max(0, self.oracle_rep.get(node_id, 0.0) - amount)

    # ─── Predictions ──────────────────────────────────────────────────

    def place_prediction(
        self, node_id: str, market_title: str, side: str, probability_at_bet: float
    ) -> tuple[bool, str]:
        """Place a FREE prediction on a market outcome (no rep risked).

        Args:
            node_id: Predictor's node ID
            market_title: Title of the prediction market
            side: "yes", "no", or any outcome name for multi-outcome markets
            probability_at_bet: Current probability (0-100) of the chosen side

        Returns (success, detail)
        """
        if not side or not side.strip():
            return False, "Side is required"

        if not (0 <= probability_at_bet <= 100):
            return False, "Probability must be 0-100"

        # Check for duplicate predictions on same market
        existing = [
            p
            for p in self.predictions
            if p["node_id"] == node_id
            and p["market_title"] == market_title
            and not p.get("resolved", False)
        ]
        if existing:
            return (
                False,
                f"You already have an active prediction on '{market_title}'. Your decision was FINAL.",
            )

        # Also check market stakes — can't free-pick AND stake on same market
        existing_stake = [
            s
            for s in self.market_stakes
            if s["node_id"] == node_id
            and s["market_title"] == market_title
            and not s.get("resolved", False)
        ]
        if existing_stake:
            return (
                False,
                f"You already have a STAKED prediction on '{market_title}'. Your decision was FINAL.",
            )

        self.predictions.append(
            {
                "prediction_id": secrets.token_hex(6),
                "node_id": node_id,
                "market_title": market_title,
                "side": side,
                "probability_at_bet": probability_at_bet,
                "timestamp": time.time(),
                "resolved": False,
                "correct": None,
                "rep_earned": 0.0,
            }
        )
        self._save()

        # Potential rep = contrarianism score
        potential = round(1.0 - probability_at_bet / 100, 3)

        logger.info(
            f"FREE prediction: {node_id} picks '{side}' on '{market_title}' "
            f"at {probability_at_bet}% (potential: {potential} oracle rep)"
        )
        return True, (
            f"FREE PICK placed: {side.upper()} on '{market_title}' "
            f"at {probability_at_bet}%. Potential oracle rep: {potential}. "
            f"This decision is FINAL."
        )

    def resolve_market(self, market_title: str, outcome: str) -> tuple[int, int]:
        """Resolve all FREE predictions on a market.

        Args:
            market_title: Title of the market
            outcome: "yes", "no", or any outcome name for multi-outcome markets

        Returns (winners, losers) counts
        """
        if not outcome:
            return 0, 0

        outcome_lower = outcome.lower()
        winners, losers = 0, 0
        now = time.time()

        for p in self.predictions:
            if p["market_title"] != market_title or p.get("resolved", False):
                continue

            p["resolved"] = True
            correct = p["side"].lower() == outcome_lower
            p["correct"] = correct

            if correct:
                # Rep earned = contrarianism score
                rep = round(1.0 - p["probability_at_bet"] / 100, 3)
                rep = max(0.01, rep)  # Minimum 0.01 even for easy bets
                p["rep_earned"] = rep
                self._add_oracle_rep(p["node_id"], rep)
                winners += 1

                self.prediction_log.append(
                    {
                        "node_id": p["node_id"],
                        "market_title": market_title,
                        "side": p["side"],
                        "outcome": outcome,
                        "probability_at_bet": p["probability_at_bet"],
                        "rep_earned": rep,
                        "timestamp": p["timestamp"],
                        "resolved_at": now,
                    }
                )
                logger.info(
                    f"Oracle win: {p['node_id']} earned {rep} oracle rep "
                    f"on '{market_title}' ({p['side']} at {p['probability_at_bet']}%)"
                )
            else:
                p["rep_earned"] = 0.0
                losers += 1

                self.prediction_log.append(
                    {
                        "node_id": p["node_id"],
                        "market_title": market_title,
                        "side": p["side"],
                        "outcome": outcome,
                        "probability_at_bet": p["probability_at_bet"],
                        "rep_earned": 0.0,
                        "timestamp": p["timestamp"],
                        "resolved_at": now,
                    }
                )

        self._save()
        return winners, losers

    def get_active_markets(self) -> list[str]:
        """Get list of market titles with unresolved predictions or stakes."""
        titles = set()
        for p in self.predictions:
            if not p.get("resolved", False):
                titles.add(p["market_title"])
        for s in self.market_stakes:
            if not s.get("resolved", False):
                titles.add(s["market_title"])
        return list(titles)

    # ─── Market Stakes (prediction markets) ────────────────────────────

    def place_market_stake(
        self, node_id: str, market_title: str, side: str, amount: float, probability_at_bet: float
    ) -> tuple[bool, str]:
        """Stake oracle rep on a prediction market outcome. FINAL decision.

        Args:
            node_id: Staker's node ID
            market_title: Title of the prediction market
            side: "yes", "no", or outcome name for multi-outcome markets
            amount: How much oracle rep to risk
            probability_at_bet: Current probability (0-100) of the chosen side

        Returns (success, detail)
        """
        if not side or not side.strip():
            return False, "Side is required"

        if amount <= 0:
            return False, "Stake amount must be positive"

        if not (0 <= probability_at_bet <= 100):
            return False, "Probability must be 0-100"

        available = self.get_oracle_rep(node_id)
        if available < amount:
            return False, f"Insufficient oracle rep (have {available:.2f}, need {amount:.2f})"

        # Can't have both a free pick AND a stake on the same market
        existing_free = [
            p
            for p in self.predictions
            if p["node_id"] == node_id
            and p["market_title"] == market_title
            and not p.get("resolved", False)
        ]
        if existing_free:
            return (
                False,
                f"You already have a FREE prediction on '{market_title}'. Your decision was FINAL.",
            )

        # Can't stake twice on the same market
        existing_stake = [
            s
            for s in self.market_stakes
            if s["node_id"] == node_id
            and s["market_title"] == market_title
            and not s.get("resolved", False)
        ]
        if existing_stake:
            return (
                False,
                f"You already have a STAKED prediction on '{market_title}'. Your decision was FINAL.",
            )

        self.market_stakes.append(
            {
                "stake_id": secrets.token_hex(6),
                "node_id": node_id,
                "market_title": market_title,
                "side": side,
                "amount": amount,
                "probability_at_bet": probability_at_bet,
                "timestamp": time.time(),
                "resolved": False,
                "correct": None,
                "rep_earned": 0.0,
            }
        )
        self._save()

        logger.info(
            f"MARKET STAKE: {node_id} stakes {amount:.2f} rep on '{side}' "
            f"for '{market_title}' at {probability_at_bet}%"
        )
        return True, (
            f"STAKED {amount:.2f} oracle rep on {side.upper()} for '{market_title}' "
            f"at {probability_at_bet}%. This decision is FINAL. "
            f"If correct, you split the loser pool proportionally."
        )

    def resolve_market_stakes(self, market_title: str, outcome: str) -> dict:
        """Resolve all market stakes for a concluded market.

        Winners split the loser pool proportionally to their stake.
        If everyone picked the same side, stakes are returned (no profit, no loss).

        Returns summary dict.
        """
        if not outcome:
            return {"resolved": 0}

        outcome_lower = outcome.lower()
        active = [
            s
            for s in self.market_stakes
            if s["market_title"] == market_title and not s.get("resolved", False)
        ]

        if not active:
            return {"resolved": 0}

        winners = [s for s in active if s["side"].lower() == outcome_lower]
        losers = [s for s in active if s["side"].lower() != outcome_lower]

        winner_pool = sum(s["amount"] for s in winners)
        loser_pool = sum(s["amount"] for s in losers)

        now = time.time()

        if not losers:
            # Everyone picked the same side — return stakes, no profit
            for s in active:
                s["resolved"] = True
                s["correct"] = True
                s["rep_earned"] = 0.0  # No profit when no opposition
            self._save()
            logger.info(
                f"Market stake resolution [{market_title}]: unanimous '{outcome}', "
                f"{len(winners)} stakers get rep back (no loser pool)"
            )
            return {
                "resolved": len(active),
                "winners": len(winners),
                "losers": 0,
                "winner_pool": winner_pool,
                "loser_pool": 0,
                "unanimous": True,
            }

        # Losers lose their staked rep
        for s in losers:
            self._remove_oracle_rep(s["node_id"], s["amount"])
            s["resolved"] = True
            s["correct"] = False
            s["rep_earned"] = 0.0

            self.prediction_log.append(
                {
                    "node_id": s["node_id"],
                    "market_title": market_title,
                    "side": s["side"],
                    "outcome": outcome,
                    "probability_at_bet": s["probability_at_bet"],
                    "rep_earned": 0.0,
                    "staked": s["amount"],
                    "timestamp": s["timestamp"],
                    "resolved_at": now,
                }
            )

        # Winners split loser pool proportionally + keep their own stake
        for s in winners:
            proportion = s["amount"] / winner_pool if winner_pool > 0 else 0
            winnings = round(loser_pool * proportion, 3)
            s["resolved"] = True
            s["correct"] = True
            s["rep_earned"] = winnings
            self._add_oracle_rep(s["node_id"], winnings)

            self.prediction_log.append(
                {
                    "node_id": s["node_id"],
                    "market_title": market_title,
                    "side": s["side"],
                    "outcome": outcome,
                    "probability_at_bet": s["probability_at_bet"],
                    "rep_earned": winnings,
                    "staked": s["amount"],
                    "timestamp": s["timestamp"],
                    "resolved_at": now,
                }
            )

        self._save()
        logger.info(
            f"Market stake resolution [{market_title}]: '{outcome}' wins. "
            f"{len(winners)} winners split {loser_pool:.2f} rep from {len(losers)} losers"
        )
        return {
            "resolved": len(active),
            "winners": len(winners),
            "losers": len(losers),
            "winner_pool": round(winner_pool, 3),
            "loser_pool": round(loser_pool, 3),
        }

    def get_market_consensus(self, market_title: str) -> dict:
        """Get network consensus for a single market — picks + stakes per side."""
        sides: dict[str, dict] = {}

        # Count free predictions
        for p in self.predictions:
            if p["market_title"] != market_title or p.get("resolved", False):
                continue
            s = p["side"]
            if s not in sides:
                sides[s] = {"picks": 0, "staked": 0.0}
            sides[s]["picks"] += 1

        # Count market stakes
        for st in self.market_stakes:
            if st["market_title"] != market_title or st.get("resolved", False):
                continue
            s = st["side"]
            if s not in sides:
                sides[s] = {"picks": 0, "staked": 0.0}
            sides[s]["picks"] += 1
            sides[s]["staked"] = round(sides[s]["staked"] + st["amount"], 3)

        total_picks = sum(v["picks"] for v in sides.values())
        total_staked = round(sum(v["staked"] for v in sides.values()), 3)

        return {
            "market_title": market_title,
            "total_picks": total_picks,
            "total_staked": total_staked,
            "sides": sides,
        }

    def get_all_market_consensus(self) -> dict[str, dict]:
        """Bulk consensus for all active markets. Returns {market_title: consensus_summary}."""
        titles = set()
        for p in self.predictions:
            if not p.get("resolved", False):
                titles.add(p["market_title"])
        for s in self.market_stakes:
            if not s.get("resolved", False):
                titles.add(s["market_title"])

        result = {}
        for title in titles:
            c = self.get_market_consensus(title)
            result[title] = {
                "total_picks": c["total_picks"],
                "total_staked": c["total_staked"],
                "sides": c["sides"],
            }
        return result

    # ─── Truth Stakes (posts/comments — separate system) ──────────────

    def place_stake(
        self,
        staker_id: str,
        message_id: str,
        poster_id: str,
        side: str,
        amount: float,
        duration_days: int,
    ) -> tuple[bool, str]:
        """Stake oracle rep on a post's truthfulness.

        Args:
            staker_id: Oracle staking their rep
            message_id: The post/message being evaluated
            poster_id: Who posted the original message
            side: "truth" or "false"
            amount: How much oracle rep to stake
            duration_days: 1-7 days before resolution

        Returns (success, detail)
        """
        if side not in ("truth", "false"):
            return False, "Side must be 'truth' or 'false'"

        if not (MIN_STAKE_DAYS <= duration_days <= MAX_STAKE_DAYS):
            return False, f"Duration must be {MIN_STAKE_DAYS}-{MAX_STAKE_DAYS} days"

        if amount <= 0:
            return False, "Stake amount must be positive"

        available = self.get_oracle_rep(staker_id)
        if available < amount:
            return False, f"Insufficient oracle rep (have {available}, need {amount})"

        # Check if this staker already has an active stake on this message
        existing = [
            s
            for s in self.stakes
            if s["staker_id"] == staker_id
            and s["message_id"] == message_id
            and not s.get("resolved", False)
        ]
        if existing:
            return False, "You already have an active stake on this message"

        now = time.time()
        expires = now + (duration_days * 86400)

        # Check if there are existing stakes — extend grace period
        active_stakes = [
            s for s in self.stakes if s["message_id"] == message_id and not s.get("resolved", False)
        ]
        # If this is a counter-stake, ensure the expiry is at least GRACE_PERIOD_HOURS
        # after the latest stake on the other side
        for s in active_stakes:
            if s["side"] != side:
                min_expires = s.get("last_counter_at", s["created_at"]) + (
                    GRACE_PERIOD_HOURS * 3600
                )
                if expires < min_expires:
                    expires = min_expires

        stake = {
            "stake_id": secrets.token_hex(6),
            "message_id": message_id,
            "poster_id": poster_id,
            "staker_id": staker_id,
            "side": side,
            "amount": amount,
            "duration_days": duration_days,
            "created_at": now,
            "expires_at": expires,
            "resolved": False,
            "last_counter_at": now,
        }
        self.stakes.append(stake)

        # Update last_counter_at on opposing stakes (extends their grace period)
        for s in active_stakes:
            if s["side"] != side:
                s["last_counter_at"] = now

        self._save()

        days_str = f"{duration_days} day{'s' if duration_days > 1 else ''}"
        logger.info(
            f"Oracle stake: {staker_id} stakes {amount} oracle rep "
            f"as '{side}' on message {message_id} for {days_str}"
        )
        return True, (
            f"Staked {amount} oracle rep as '{side.upper()}' on message "
            f"{message_id} for {days_str}. Expires {time.strftime('%Y-%m-%d %H:%M', time.localtime(expires))}"
        )

    def resolve_expired_stakes(self) -> list[dict]:
        """Resolve all expired stake contests. Called periodically.

        Returns list of resolution summaries.
        """
        now = time.time()
        resolutions = []

        # Group active stakes by message_id
        active_by_msg: dict[str, list[dict]] = {}
        for s in self.stakes:
            if not s.get("resolved", False):
                active_by_msg.setdefault(s["message_id"], []).append(s)

        for msg_id, stakes in active_by_msg.items():
            # Check if ALL stakes for this message have expired
            if not all(s["expires_at"] <= now for s in stakes):
                continue  # Some stakes haven't expired yet

            # Tally sides
            truth_total = sum(s["amount"] for s in stakes if s["side"] == "truth")
            false_total = sum(s["amount"] for s in stakes if s["side"] == "false")

            if truth_total == false_total:
                # Tie — everyone gets their rep back, no resolution
                for s in stakes:
                    s["resolved"] = True
                resolutions.append(
                    {
                        "message_id": msg_id,
                        "outcome": "tie",
                        "truth_total": truth_total,
                        "false_total": false_total,
                    }
                )
                continue

            winning_side = "truth" if truth_total > false_total else "false"
            losing_total = false_total if winning_side == "truth" else truth_total
            winning_total = truth_total if winning_side == "truth" else false_total

            winners = [s for s in stakes if s["side"] == winning_side]
            losers = [s for s in stakes if s["side"] != winning_side]

            # Losers lose their staked rep
            for s in losers:
                self._remove_oracle_rep(s["staker_id"], s["amount"])
                s["resolved"] = True

            # Winners divide losers' rep proportionally
            for s in winners:
                proportion = s["amount"] / winning_total if winning_total > 0 else 0
                winnings = round(losing_total * proportion, 3)
                self._add_oracle_rep(s["staker_id"], winnings)
                s["resolved"] = True

            # Duration weight for the poster's reputation effect
            max_duration = max(s["duration_days"] for s in stakes)
            duration_label = (
                "resounding" if max_duration >= 7 else "contested" if max_duration >= 3 else "brief"
            )

            resolution = {
                "message_id": msg_id,
                "poster_id": stakes[0].get("poster_id", ""),
                "outcome": winning_side,
                "truth_total": round(truth_total, 3),
                "false_total": round(false_total, 3),
                "duration_label": duration_label,
                "max_duration_days": max_duration,
                "winners": [
                    {
                        "node_id": s["staker_id"],
                        "staked": s["amount"],
                        "won": (
                            round(losing_total * (s["amount"] / winning_total), 3)
                            if winning_total > 0
                            else 0
                        ),
                    }
                    for s in winners
                ],
                "losers": [
                    {
                        "node_id": s["staker_id"],
                        "lost": s["amount"],
                    }
                    for s in losers
                ],
            }
            resolutions.append(resolution)
            logger.info(
                f"Oracle resolution [{msg_id}]: {winning_side.upper()} wins "
                f"({truth_total} vs {false_total}), {duration_label} verdict"
            )

        if resolutions:
            self._save()
        return resolutions

    def get_stakes_for_message(self, message_id: str) -> dict:
        """Get all stakes on a message with totals."""
        active = [
            s for s in self.stakes if s["message_id"] == message_id and not s.get("resolved", False)
        ]
        truth_stakes = [s for s in active if s["side"] == "truth"]
        false_stakes = [s for s in active if s["side"] == "false"]

        return {
            "message_id": message_id,
            "truth_total": round(sum(s["amount"] for s in truth_stakes), 3),
            "false_total": round(sum(s["amount"] for s in false_stakes), 3),
            "truth_stakers": [
                {"node_id": s["staker_id"], "amount": s["amount"], "expires": s["expires_at"]}
                for s in truth_stakes
            ],
            "false_stakers": [
                {"node_id": s["staker_id"], "amount": s["amount"], "expires": s["expires_at"]}
                for s in false_stakes
            ],
            "earliest_expiry": min((s["expires_at"] for s in active), default=0),
        }

    # ─── Oracle Profile ───────────────────────────────────────────────

    def get_oracle_profile(self, node_id: str) -> dict:
        """Full oracle profile — rep, prediction history, active stakes."""
        total_rep = self.get_total_oracle_rep(node_id)
        available_rep = self.get_oracle_rep(node_id)

        # Prediction stats
        my_predictions = [p for p in self.prediction_log if p["node_id"] == node_id]
        wins = [p for p in my_predictions if p["rep_earned"] > 0]
        losses = [p for p in my_predictions if p["rep_earned"] == 0]

        # Active stakes
        active_stakes = [
            {
                "message_id": s["message_id"],
                "side": s["side"],
                "amount": s["amount"],
                "expires": s["expires_at"],
            }
            for s in self.stakes
            if s["staker_id"] == node_id and not s.get("resolved", False)
        ]

        # Recent prediction log (last 20)
        recent = sorted(my_predictions, key=lambda x: x.get("resolved_at", 0), reverse=True)[:20]
        prediction_history = [
            {
                "market": p["market_title"][:50],
                "side": p["side"],
                "probability": p["probability_at_bet"],
                "outcome": p.get("outcome", "?"),
                "rep_earned": p["rep_earned"],
                "correct": p["rep_earned"] > 0,
                "age": f"{int((time.time() - p.get('resolved_at', p['timestamp'])) / 86400)}d ago",
            }
            for p in recent
        ]

        # Farming score — what % of bets were on >80% probability outcomes
        if my_predictions:
            easy_bets = sum(
                1
                for p in my_predictions
                if (p["side"] == "yes" and p["probability_at_bet"] > 80)
                or (p["side"] == "no" and p["probability_at_bet"] < 20)
            )
            farming_pct = round(easy_bets / len(my_predictions) * 100)
        else:
            farming_pct = 0

        return {
            "node_id": node_id,
            "oracle_rep": available_rep,
            "oracle_rep_total": total_rep,
            "oracle_rep_locked": round(total_rep - available_rep, 3),
            "predictions_won": len(wins),
            "predictions_lost": len(losses),
            "win_rate": round(len(wins) / max(1, len(wins) + len(losses)) * 100),
            "farming_pct": farming_pct,
            "active_stakes": active_stakes,
            "prediction_history": prediction_history,
        }

    def get_active_predictions(self, node_id: str) -> list[dict]:
        """Get a node's unresolved predictions (free picks + staked)."""
        results = []
        now = time.time()

        # Free picks
        for p in self.predictions:
            if p["node_id"] != node_id or p.get("resolved", False):
                continue
            potential = round(1.0 - p["probability_at_bet"] / 100, 3)
            days = int((now - p["timestamp"]) / 86400)
            results.append(
                {
                    "prediction_id": p["prediction_id"],
                    "market_title": p["market_title"],
                    "side": p["side"],
                    "probability_at_bet": p["probability_at_bet"],
                    "potential_rep": potential,
                    "staked": 0,
                    "mode": "free",
                    "placed": f"{days}d ago",
                }
            )

        # Market stakes
        for s in self.market_stakes:
            if s["node_id"] != node_id or s.get("resolved", False):
                continue
            days = int((now - s["timestamp"]) / 86400)
            results.append(
                {
                    "prediction_id": s["stake_id"],
                    "market_title": s["market_title"],
                    "side": s["side"],
                    "probability_at_bet": s["probability_at_bet"],
                    "potential_rep": 0,  # Depends on loser pool — unknown until resolution
                    "staked": s["amount"],
                    "mode": "staked",
                    "placed": f"{days}d ago",
                }
            )

        return results

    # ─── Cleanup ──────────────────────────────────────────────────────

    def cleanup_old_data(self):
        """Remove resolved predictions and market stakes older than decay window."""
        cutoff = time.time() - (ORACLE_DECAY_DAYS * 86400)
        before_pred = len(self.predictions)
        before_stakes = len(self.market_stakes)
        self.predictions = [
            p for p in self.predictions if not p.get("resolved", False) or p["timestamp"] >= cutoff
        ]
        self.market_stakes = [
            s
            for s in self.market_stakes
            if not s.get("resolved", False) or s["timestamp"] >= cutoff
        ]
        # Trim prediction log
        self.prediction_log = [
            p for p in self.prediction_log if p.get("resolved_at", p["timestamp"]) >= cutoff
        ]
        removed = (before_pred - len(self.predictions)) + (before_stakes - len(self.market_stakes))
        if removed:
            self._save()
            logger.info(f"Cleaned up {removed} old predictions/stakes")


# ─── Module-level singleton ──────────────────────────────────────────────

oracle_ledger = OracleLedger()
