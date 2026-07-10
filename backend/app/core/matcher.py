import hashlib
import json
import re
from pathlib import Path

import yaml

from app.core.normalizer import NormalizedOrder

_BUDGET_PATTERNS = [
    re.compile(r"(\d[\d\s]*)\s*[-–]\s*(\d[\d\s]*)\s*(?:₽|руб|р\.?)", re.I),
    re.compile(r"от\s*(\d[\d\s]*)\s*(?:₽|руб|р\.?)", re.I),
    re.compile(r"(\d[\d\s]*)\s*(?:₽|руб|р\.?)", re.I),
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
        if "$" in pat.pattern:
            value *= 100
        return value
    return None


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
    def min_project_rub(self) -> int:
        return int(self.data.get("pricing", {}).get("project_min_rub", 30000))

    def negative_terms(self) -> list[str]:
        return [t.lower() for t in self.data.get("skills_negative", [])]

    def positive_terms(self) -> list[str]:
        return [t.lower() for t in self.data.get("skills_positive", [])]

    def keyword_boost(self) -> dict[str, int]:
        return {k.lower(): v for k, v in self.data.get("keywords_boost", {}).items()}


class RulesMatcher:
    def __init__(self, profile: ProfileData):
        self.profile = profile

    def match(self, order: NormalizedOrder) -> tuple[float, list[str], str]:
        text = f"{order.title}\n{order.description}".lower()
        reasons: list[str] = []
        score = 0.0

        for term in self.profile.negative_terms():
            if term in text:
                return 0.0, [f"стоп-слово: {term}"], ""

        budget = order.budget_min_rub or parse_budget_rub(
            f"{order.budget_text} {order.description}"
        )
        if budget is not None and budget < self.profile.min_project_rub:
            return 0.0, [f"бюджет {budget} < {self.profile.min_project_rub}"], ""

        for kw, boost in self.profile.keyword_boost().items():
            if kw in text:
                score += boost
                reasons.append(f"+{boost} {kw}")

        for skill in self.profile.positive_terms():
            if skill in text:
                score += 3
                if len(reasons) < 8:
                    reasons.append(f"+3 {skill}")

        case_slug = self._suggest_case(text)
        if case_slug:
            score += 10
            reasons.append(f"кейс: {case_slug}")

        return min(score, 100.0), reasons, case_slug

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
            hits = sum(1 for t in tags if t in text)
            if hits > best_hits:
                best_hits = hits
                best_slug = case.get("slug", "")
        return best_slug if best_hits >= 2 else (best_slug if best_hits == 1 else "")
