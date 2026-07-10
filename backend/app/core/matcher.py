import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.normalizer import NormalizedOrder

_BUDGET_PATTERNS = [
    re.compile(r"(\d[\d\s]*)\s*[-–]\s*(\d[\d\s]*)\s*(?:₽|руб|р\.?)", re.I),
    re.compile(r"от\s*(\d[\d\s]*)\s*(?:₽|руб|р\.?)", re.I),
    re.compile(r"до\s*(\d[\d\s]*)\s*(?:₽|руб|р\.?)", re.I),
    re.compile(r"(\d[\d\s]*)\s*(?:₽|руб|р\.?)", re.I),
    re.compile(r"(\d[\d\s]*)\s*(?:uah|грн|₴)", re.I),
    re.compile(r"\$(\d[\d\s]*)", re.I),
    # Kwork priceLimit often comes as bare "24000" or "1600-24000"
    re.compile(r"^\s*(\d[\d\s]*)\s*[-–]\s*(\d[\d\s]*)\s*$"),
    re.compile(r"^\s*(\d[\d\s]{2,})\s*$"),
]


def content_hash(title: str, description: str) -> str:
    payload = f"{title.strip().lower()}\n{description.strip().lower()}"
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _to_int(raw: str) -> int | None:
    try:
        return int(raw.replace(" ", "").replace("\u00a0", ""))
    except ValueError:
        return None


def _scale_currency(value: int, matched: str) -> int:
    low = matched.lower()
    if "$" in low or "usd" in low:
        return int(value * 90)
    if "uah" in low or "грн" in low or "₴" in low:
        return int(value * 2.2)
    return value


def parse_budget_bounds(text: str) -> tuple[int | None, int | None]:
    """
    Return (min_rub, max_rub) when possible.
    For a single number (Kwork priceLimit) → (None, value) as client ceiling.
    """
    if not text:
        return None, None
    for pat in _BUDGET_PATTERNS:
        m = pat.search(text.strip())
        if not m:
            continue
        groups = [g for g in m.groups() if g is not None]
        if not groups:
            continue
        nums = [_to_int(g) for g in groups]
        nums = [n for n in nums if n is not None]
        if not nums:
            continue
        matched = m.group(0)
        nums = [_scale_currency(n, matched) for n in nums]
        nums = [n for n in nums if n >= 500]
        if not nums:
            continue
        if len(nums) >= 2:
            return min(nums[0], nums[1]), max(nums[0], nums[1])
        # Single number: treat as ceiling (priceLimit) unless "от N"
        if matched.lower().strip().startswith("от"):
            return nums[0], None
        if matched.lower().strip().startswith("до"):
            return None, nums[0]
        return None, nums[0]
    return None, None


def parse_budget_rub(text: str) -> int | None:
    """Best single figure for filters: prefer max (client ceiling) when known."""
    lo, hi = parse_budget_bounds(text)
    if hi is not None:
        return hi
    return lo


@dataclass
class MatchResult:
    score: float
    reasons: list[str]
    case_slug: str
    intent_id: str
    intent_title: str
    price_min_rub: int
    client_need: str
    budget_max_rub: int | None = None


class ProfileData:
    def __init__(self, data: dict):
        self.data = data

    @classmethod
    def load(cls, config_dir: Path) -> "ProfileData":
        path = config_dir / "profile.yaml"
        with path.open(encoding="utf-8") as f:
            return cls(yaml.safe_load(f))

    @property
    def thresholds(self) -> dict:
        return self.data.get("thresholds", {})

    @property
    def pricing(self) -> dict:
        return self.data.get("pricing", {})

    @property
    def min_project_rub(self) -> int:
        return int(self.pricing.get("project_min_rub", 20000))

    def intents(self) -> dict:
        return self.data.get("intents", {})

    def negative_terms(self) -> list[str]:
        return [t.lower() for t in self.data.get("skills_negative", [])]

    def junk_signals(self) -> list[str]:
        return [t.lower() for t in self.data.get("junk_signals", [])]

    def positive_terms(self) -> list[str]:
        return [t.lower() for t in self.data.get("skills_positive", [])]

    def keyword_boost(self) -> dict[str, int]:
        return {k.lower(): int(v) for k, v in self.data.get("keywords_boost", {}).items()}

    def price_for_intent(self, intent_id: str) -> int:
        intents = self.intents()
        meta = intents.get(intent_id) or {}
        key = meta.get("price_key", "project_min_rub")
        return int(self.pricing.get(key, self.min_project_rub))


def _contains(text: str, needle: str) -> bool:
    """Substring match; short tokens require word-ish boundaries."""
    if not needle:
        return False
    if len(needle) <= 4:
        return re.search(rf"(?<![a-zа-я0-9_]){re.escape(needle)}(?![a-zа-я0-9_])", text) is not None
    return needle in text


_STRONG_IT = (
    "сайт",
    "лендинг",
    "бот",
    "парсер",
    "api",
    "интеграц",
    "next.js",
    "react",
    "fastapi",
    "верстк",
    "mini app",
    "webhook",
    "починить",
    "доработ",
)


class RulesMatcher:
    """Fast rules-first matcher: intents → boosts → junk → budget gate."""

    def __init__(self, profile: ProfileData):
        self.profile = profile

    def match(self, order: NormalizedOrder) -> MatchResult:
        text = f"{order.title}\n{order.description}".lower()
        reasons: list[str] = []
        score = 0.0

        for term in self.profile.negative_terms():
            if _contains(text, term) or (len(term) > 4 and term in text):
                return MatchResult(
                    0.0, [f"стоп: {term}"], "", "", "", 0, order.title[:160]
                )

        junk_hits = [
            s for s in self.profile.junk_signals() if _contains(text, s) or s in text
        ]
        strong_it = any(_contains(text, t) or t in text for t in _STRONG_IT)
        if len(junk_hits) >= 2 and not strong_it:
            return MatchResult(
                0.0,
                [f"бред: {', '.join(junk_hits[:3])}"],
                "",
                "",
                "",
                0,
                order.title[:160],
            )
        if junk_hits and not strong_it:
            score -= 25
            reasons.append(f"шум:{junk_hits[0]}")

        intent_id, intent_title, intent_score, intent_hits = self._best_intent(text)
        if intent_id:
            score += intent_score
            reasons.append(f"интент:{intent_id}(+{intent_score})")
            for h in intent_hits[:3]:
                reasons.append(f"· {h}")
        else:
            reasons.append("интент:неясен")

        for kw, boost in self.profile.keyword_boost().items():
            if _contains(text, kw):
                score += boost
                if len(reasons) < 10:
                    reasons.append(f"+{boost} {kw}")

        for skill in self.profile.positive_terms():
            if _contains(text, skill):
                score += 4
                if len(reasons) < 12:
                    reasons.append(f"+4 {skill}")

        case_slug = self._suggest_case(text)
        if case_slug:
            score += 12
            reasons.append(f"кейс:{case_slug}")

        # TG job spam: without clear intent — drop hard
        if order.source == "telegram" and not intent_id:
            return MatchResult(
                min(max(score, 0.0), 20.0),
                reasons + ["tg без интента"],
                case_slug,
                "",
                "",
                self.profile.min_project_rub,
                self._client_need(order, intent_title),
            )

        # Must have at least one intent OR strong tech signal
        if not intent_id and score < 35:
            return MatchResult(
                min(max(score, 0.0), 25.0),
                reasons + ["слабо релевантно"],
                case_slug,
                "",
                "",
                self.profile.min_project_rub,
                self._client_need(order, intent_title),
            )

        price_min = (
            self.profile.price_for_intent(intent_id)
            if intent_id
            else self.profile.min_project_rub
        )

        budget_lo, budget_hi = parse_budget_bounds(
            f"{order.budget_text} {order.description} {order.title}".strip()
        )
        if order.budget_min_rub is not None and budget_hi is None:
            budget_hi = order.budget_min_rub
        budget = budget_hi or budget_lo or order.budget_min_rub

        thr = self.profile.thresholds
        if budget is not None and budget < price_min:
            # Явно мизерный потолок — отсев; чуть ниже floor — штраф, цена потом clamp
            if thr.get("reject_if_budget_below_min") and budget < int(price_min * 0.45):
                return MatchResult(
                    0.0,
                    [f"бюджет {budget} << {price_min}"],
                    case_slug,
                    intent_id,
                    intent_title,
                    price_min,
                    self._client_need(order, intent_title),
                    budget_max_rub=budget_hi,
                )
            if budget < int(price_min * 0.7):
                score *= 0.7
                reasons.append(f"потолок {budget} ниже floor {price_min}")
            else:
                score *= 0.92
                reasons.append(f"потолок {budget}, цена будет clamp")

        return MatchResult(
            min(max(score, 0.0), 100.0),
            reasons,
            case_slug,
            intent_id,
            intent_title,
            price_min,
            self._client_need(order, intent_title),
            budget_max_rub=budget_hi,
        )

    def _best_intent(self, text: str) -> tuple[str, str, float, list[str]]:
        best_id = ""
        best_title = ""
        best_score = 0.0
        best_hits: list[str] = []
        for intent_id, meta in self.profile.intents().items():
            kws = [str(k).lower() for k in meta.get("keywords", [])]
            hits = [k for k in kws if _contains(text, k)]
            if not hits:
                continue
            weight = float(meta.get("weight", 15))
            sc = weight + min(len(hits) - 1, 4) * 4
            if sc > best_score:
                best_score = sc
                best_id = intent_id
                best_title = str(meta.get("title", intent_id))
                best_hits = hits
        return best_id, best_title, best_score, best_hits

    def _client_need(self, order: NormalizedOrder, intent_title: str) -> str:
        title = order.title.strip()
        if intent_title:
            return f"{intent_title}: {title}"[:220]
        return title[:220]

    def _suggest_case(self, text: str) -> str:
        config_dir = Path(self.profile.data.get("_config_dir", "."))
        portfolio_path = config_dir / "portfolio.json"
        if not portfolio_path.exists():
            return ""
        cases = json.loads(portfolio_path.read_text(encoding="utf-8"))
        best_slug = ""
        best_hits = 0
        for case in cases:
            tags = [t.lower() for t in case.get("match_tags", [])]
            hits = sum(1 for t in tags if _contains(text, t) or t in text)
            if hits > best_hits:
                best_hits = hits
                best_slug = case.get("slug", "")
        return best_slug if best_hits >= 1 else ""
