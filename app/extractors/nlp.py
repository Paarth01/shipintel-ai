"""Optional spaCy NER adapter (disabled by default; needs `requirements-nlp.txt` + a model).

It is a *suggestion* layer, not the baseline: it only proposes values for fields the rules left
empty - ports (GPE/LOC/FAC entities after loading/discharge verbs) and counterparty (ORG entities
after a role word such as 'chartered by'). Suggestions get a low heuristic score so they always
land in `needs_review`. spaCy's pretrained NER is a statistical model; the rules are not.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.config import Settings
from app.evidence import Candidate
from app.gazetteer import lookup_port
from app.normalizers import clean_party, smart_title
from app.schemas import PageText, Severity

NER_SCORE = 0.5
_LOAD = re.compile(r"(?i)\b(?:load(?:ing|ed)?|lift(?:ing|ed)?|shipp(?:ed|ing))\b[^.\n]{0,25}$")
_DISCH = re.compile(r"(?i)\b(?:discharg\w*|deliver\w*|unload\w*)\b[^.\n]{0,25}$")
_ROLE = re.compile(r"(?i)(charter(?:ed|ers?)?|shipper|consignee)\b[^.\n]{0,25}$")
_ROLE_NUM = {"charter": 1, "shipper": 2, "consignee": 3}


@lru_cache(maxsize=2)
def _load(model: str):
    try:
        import spacy

        return spacy.load(model, disable=["lemmatizer"])
    except Exception:
        return None


def nlp_available(settings: Settings) -> bool:
    return _load(settings.spacy_model) is not None


def nlp_candidates(
    pages: list[PageText], existing: list[Candidate], settings: Settings
) -> list[Candidate] | None:
    """Return suggested candidates, or None if spaCy / the model is unavailable."""
    nlp = _load(settings.spacy_model)
    if nlp is None:
        return None
    have = {c.field for c in existing if c.value is not None}
    out: list[Candidate] = []
    for page in pages:
        doc = nlp(page.text)
        for ent in doc.ents:
            before = page.text[max(0, ent.start_char - 60) : ent.start_char]
            if ent.label_ in ("GPE", "LOC", "FAC"):
                field = (
                    "origin_port"
                    if _LOAD.search(before)
                    else "destination_port"
                    if _DISCH.search(before)
                    else None
                )
                if field and field not in have:
                    hit = lookup_port(ent.text)
                    value = hit[0] if hit else smart_title(ent.text)
                    out.append(
                        Candidate(
                            field,
                            value,
                            ent.text,
                            page.page,
                            ent.start_char,
                            ent.end_char,
                            "spacy_ner",
                            NER_SCORE,
                            ent.label_,
                            "extracted",
                            [("NER_SUGGESTION", "Suggested by spaCy NER; verify.", Severity.INFO)],
                        )
                    )
            elif ent.label_ == "ORG" and "counterparty" not in have:
                m = _ROLE.search(before)
                party = clean_party(ent.text)
                if m and party:
                    role = next((n for k, n in _ROLE_NUM.items() if m[1].lower().startswith(k)), 3)
                    out.append(
                        Candidate(
                            "counterparty",
                            party,
                            ent.text,
                            page.page,
                            ent.start_char,
                            ent.end_char,
                            "spacy_ner",
                            NER_SCORE,
                            "ORG",
                            "extracted",
                            [("NER_SUGGESTION", "Suggested by spaCy NER; verify.", Severity.INFO)],
                            role=role,
                        )
                    )
    return out
