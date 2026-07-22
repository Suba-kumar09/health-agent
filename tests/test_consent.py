from agent.consent import (
    ConsentManager,
    ensure_first_run_consent,
    resolve_capture_mode,
    run_detailed_consent_flow,
)


def test_no_consent_recorded_initially(tmp_path):
    consent = ConsentManager(tmp_path)
    assert consent.has_basic_consent() is False
    assert consent.has_detailed_consent() is False


def test_ensure_first_run_consent_prompts_once_and_persists(tmp_path):
    consent = ConsentManager(tmp_path)
    prompts = []

    def prompt_fn(text):
        prompts.append(text)
        return "y"

    assert ensure_first_run_consent(consent, prompt_fn) is True
    assert consent.has_basic_consent() is True
    assert len(prompts) == 1

    # Second call shouldn't prompt again -- consent already on record.
    assert ensure_first_run_consent(consent, prompt_fn) is True
    assert len(prompts) == 1


def test_declining_first_run_consent_does_not_persist(tmp_path):
    consent = ConsentManager(tmp_path)

    assert ensure_first_run_consent(consent, lambda text: "n") is False
    assert consent.has_basic_consent() is False


def test_detailed_mode_requires_separate_consent(tmp_path):
    consent = ConsentManager(tmp_path)
    consent.record_basic_consent()

    # Basic consent alone doesn't grant detailed mode.
    assert resolve_capture_mode("detailed", consent) == "aggregate"

    run_detailed_consent_flow(consent, lambda text: "y")
    assert resolve_capture_mode("detailed", consent) == "detailed"


def test_declining_detailed_flow_leaves_mode_downgraded(tmp_path):
    consent = ConsentManager(tmp_path)
    consent.record_basic_consent()
    run_detailed_consent_flow(consent, lambda text: "n")

    assert resolve_capture_mode("detailed", consent) == "aggregate"


def test_aggregate_mode_unaffected_by_consent_state(tmp_path):
    consent = ConsentManager(tmp_path)
    assert resolve_capture_mode("aggregate", consent) == "aggregate"


def test_audit_log_written_when_detailed_active(tmp_path):
    consent = ConsentManager(tmp_path, now_fn=lambda: 12345.0)
    consent.log_detailed_mode_audit()

    content = (tmp_path / "detailed_mode_audit.log").read_text(encoding="utf-8")
    assert "12345.0" in content
    assert "detailed_mode_active" in content
