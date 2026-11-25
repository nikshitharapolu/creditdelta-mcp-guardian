from unittest.mock import patch
from urllib.error import HTTPError
from creditdelta_mcp import report_generator as reports
from tests.test_report_generator import SAMPLE


def test_safe_status_for_hosted_failures():
    diagnostics = []
    with patch.object(reports, '_gemini_narrative', side_effect=ImportError('private details')), patch.object(reports, '_groq_narrative', side_effect=HTTPError('https://example.invalid', 403, 'private details', {}, None)):
        report, source = reports.generate_report(SAMPLE, 'secret', groq_api_key='secret', diagnostics=diagnostics)
    assert source == 'template'
    assert diagnostics[0]['category'] == 'dependency_import'
    assert diagnostics[1]['http_status'] == 403
    assert 'private details' not in str(diagnostics)
    assert 'secret' not in str(diagnostics)


def test_missing_keys_are_explicit_and_old_status_cleared():
    diagnostics = [{'old': 'status'}]
    reports.generate_report(SAMPLE, None, diagnostics=diagnostics)
    assert diagnostics == [{'provider': 'gemini', 'status': 'not_configured'}, {'provider': 'groq', 'status': 'not_configured'}]
