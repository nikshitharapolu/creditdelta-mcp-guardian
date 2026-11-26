"""Offline regression tests for the public-site navigation bug."""
from pathlib import Path
import pytest
pytest.importorskip('streamlit')
from streamlit.testing.v1 import AppTest
from creditdelta_mcp.report_generator import deterministic_report
from tests.test_report_generator import SAMPLE

APP = Path(__file__).resolve().parents[1] / 'src/creditdelta_mcp/dashboard.py'

@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GUARDIAN_AI_ENABLED', 'false')
    monkeypatch.setattr(
        "creditdelta_mcp.auth.show_account",
        lambda: None,
    )
    at = AppTest.from_file(str(APP)).run()
    result = dict(SAMPLE, cik='0000000001')
    at.session_state.company_matches = [{'name': 'Example Inc.', 'ticker': 'EX', 'cik': result['cik']}]
    at.session_state.financial_result = result
    at.session_state.generated_report = deterministic_report(result)
    at.session_state.report_source = 'template'
    navigate(at, 'Explore Companies')
    return at


def navigate(at, page):
    next(x for x in at.radio if x.label == 'Navigate').set_value(page).run()
    assert not at.exception


def button(at, label):
    return next(x for x in at.button if x.label == label)


def test_edited_draft_survives_page_navigation(app):
    app.text_area(key='report_editor').set_value('Edited public report draft.').run()
    navigate(app, 'Ask CreditDelta')
    navigate(app, 'Explore Companies')
    assert app.text_area(key='report_editor').value == 'Edited public report draft.'




def test_intentionally_empty_draft_stays_empty(app):
    app.text_area(key='report_editor').set_value('').run()
    navigate(app, 'Ask CreditDelta')
    navigate(app, 'Explore Companies')
    assert app.text_area(key='report_editor').value == ''
