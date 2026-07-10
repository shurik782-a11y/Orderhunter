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
]


def content_hash(title: str, description: str) -> str:
    payload = f"{title.strip().lower()}\n{description.strip().lower()}"
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def parse_budget_rub(text: str) -> int | None:
    for pat in _BUDGET_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        raw = m.group(1).replace(" ", "").replace("\u00a0", "")
        try:
            value = int(raw)
        except ValueError:
            continue
        matched = m.group(0).lower()
        if "$" in matched or "usd" in matched:
            value = int(value * 90)
        elif "uah" in matched or "грн" in matched or "₴" in matched:
            value = int(value * 2.2)  # rough UAH→RUB for filter only
        if value < 500:  # ignore noise like "1 руб"
            continue
        return value
    return None


@dataclass
class MatchResult:
    score: float
    reasons: list[str]
    case_slug: str
    intent_id: str
    intent_title: str
    price_min_rub: int
    client_need: str


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


class RulesMatcher:
    """Fast rules-first matcher: intents → boosts → case → budget gate."""

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

        # Must have at least one intent OR strong tech signal
        if not intent_id and score < 35:
            return MatchResult(
                min(score, 25.0),
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

        budget = order.budget_min_rub or parse_budget_rub(
            f"{order.budget_text} {order.description} {order.title}"
        )
        thr = self.profile.thresholds
        if budget is not None and budget < price_min:
            # Soft by default: penalize, rarely hard-reject (only if explicitly enabled)
            if thr.get("reject_if_budget_below_min") and budget < int(price_min * 0.5):
                return MatchResult(
                    0.0,
                    [f"бюджет {budget} << {price_min}"],
                    case_slug,
                    intent_id,
                    intent_title,
                    price_min,
                    self._client_need(order, intent_title),
                )
            score *= 0.75 if budget < int(price_min * 0.7) else 0.9
            reasons.append(f"бюджет {budget} ниже {price_min}")

        return MatchResult(
            min(score, 100.0),
            reasons,
            case_slug,
            intent_id,
            intent_title,
            price_min,
            self._client_need(order, intent_title),
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
