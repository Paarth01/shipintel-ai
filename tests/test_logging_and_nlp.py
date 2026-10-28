"""Logging formatters and the optional NLP adapter (tested with a stub model: no spaCy needed)."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from app.config import Settings
from app.extractors import nlp as nlp_mod
from app.logging_config import JsonFormatter, TextFormatter, request_id_var, setup_logging
from app.pipeline import process_document


# ------------------------------------------------------------------ logging
def _record(msg="hello", exc=None, **extra):
    rec = logging.LogRecord("shipintel.test", logging.INFO, __file__, 1, msg, (), exc)
    rec.request_id = "rid-12345678"
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_json_formatter_emits_valid_json_with_context_fields():
    out = json.loads(
        JsonFormatter().format(
            _record("request", method="POST", path="/extract", status=200, duration_ms=1.5)
        )
    )
    assert out["request_id"] == "rid-12345678" and out["method"] == "POST" and out["status"] == 200
    assert out["level"] == "INFO" and out["ts"].endswith("Z")


def test_json_formatter_logs_exception_type_and_frames_but_never_the_message():
    try:
        secret = "".join(
            ["SECRET", " DOCUMENT", " TEXT"]
        )  # built at runtime, like real document text
        raise RuntimeError(secret)
    except RuntimeError:
        import sys

        rec = _record("boom", exc=sys.exc_info())
    text = JsonFormatter().format(rec)
    out = json.loads(text)
    assert (
        out["exc_type"] == "RuntimeError" and "stack" in out and "SECRET DOCUMENT TEXT" not in text
    )
    assert "SECRET DOCUMENT TEXT" not in TextFormatter("%(message)s").format(rec)


def test_text_formatter_appends_structured_fields():
    line = TextFormatter("%(levelname)s %(message)s").format(
        _record("request", method="GET", path="/health", status=200)
    )
    assert "method=GET" in line and "path=/health" in line and "status=200" in line


def test_setup_logging_is_idempotent_and_honours_format_and_level(capsys):
    setup_logging("WARNING", "json")
    setup_logging("WARNING", "json")
    logger = logging.getLogger("shipintel")
    assert len(logger.handlers) == 1 and logger.level == logging.WARNING and not logger.propagate
    token = request_id_var.set("rid-abcdef12")
    try:
        logger.warning("something")
        logger.info("filtered out")
    finally:
        request_id_var.reset(token)
    lines = [json.loads(x) for x in capsys.readouterr().err.splitlines() if x.strip()]
    assert len(lines) == 1 and lines[0]["request_id"] == "rid-abcdef12"
    for h in list(
        logger.handlers
    ):  # do not leave a handler bound to the (soon closed) captured stderr
        logger.removeHandler(h)


# ------------------------------------------------------------------ NLP adapter (stubbed model)
def _ent(text, label, start, end):
    return SimpleNamespace(text=text, label_=label, start_char=start, end_char=end)


class FakeNlp:
    def __init__(self, ents_for):
        self.ents_for = ents_for

    def __call__(self, text):
        return SimpleNamespace(ents=self.ents_for(text))


def _install(monkeypatch, ents_for):
    monkeypatch.setattr(nlp_mod, "_load", lambda model: FakeNlp(ents_for))


def _span(text, needle, label):
    i = text.index(needle)
    return _ent(needle, label, i, i + len(needle))


def test_nlp_adapter_unavailable_returns_none(monkeypatch):
    monkeypatch.setattr(nlp_mod, "_load", lambda model: None)
    assert nlp_mod.nlp_candidates([], [], Settings()) is None
    assert nlp_mod.nlp_available(Settings()) is False


def test_nlp_suggests_unknown_ports_and_parties_with_low_scores(monkeypatch):
    text = "The cargo is loading at Vizhinjam and discharging at Gdansk. The charterer, Orion Commodities Ltd, has signed.\n"
    _install(
        monkeypatch,
        lambda t: [
            _span(t, "Vizhinjam", "GPE"),
            _span(t, "Gdansk", "GPE"),
            _span(t, "Orion Commodities Ltd", "ORG"),
        ],
    )
    r = process_document("p.txt", text.encode(), settings=Settings(), nlp=True)
    assert r.metadata.extractor == "rules+spacy"
    assert (
        r.fields["origin_port"].value == "Vizhinjam"
        and r.fields["destination_port"].value == "Gdansk"
    )
    assert r.fields["counterparty"].value == "Orion Commodities Ltd"
    for name in ("origin_port", "destination_port", "counterparty"):
        f = r.fields[name]
        assert (
            f.status.value == "needs_review" and f.heuristic_score <= 0.55
        )  # suggestions are always reviewed


def test_nlp_never_overrides_rule_results_or_invents_roles(monkeypatch):
    text = "Port of Loading: Rotterdam\nShe called at Berlin for fuel. Contact Acme Ltd about it.\n"
    _install(monkeypatch, lambda t: [_span(t, "Berlin", "GPE"), _span(t, "Acme Ltd", "ORG")])
    r = process_document("p.txt", text.encode(), settings=Settings(), nlp=True)
    assert r.fields["origin_port"].value == "Rotterdam"  # rules already had it
    assert (
        r.fields["counterparty"].value is None
    )  # no role word before the ORG => not a counterparty
    assert r.fields["destination_port"].value is None


def test_nlp_flag_without_model_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(nlp_mod, "_load", lambda model: None)
    r = process_document("p.txt", b"Vessel: MV A ONE\n", settings=Settings(), nlp=True)
    assert r.metadata.extractor == "rules" and any(w.code == "NLP_UNAVAILABLE" for w in r.warnings)
