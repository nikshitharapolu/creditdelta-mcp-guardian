import json
from unittest.mock import patch, MagicMock
import pytest
from creditdelta_mcp import report_generator as reports
from tests.test_report_generator import SAMPLE

TEXT = '## AI-generated interpretation\n\nThe reported revenue increased between the supplied reporting periods. These facts alone do not establish the cause.'

@pytest.mark.parametrize('failure', [TimeoutError(), RuntimeError('429'), ValueError('bad response')])
def test_gemini_failure_uses_groq(failure):
    with patch.object(reports, '_gemini_narrative', side_effect=failure), patch.object(reports, '_groq_narrative', return_value=TEXT) as groq:
        report, source = reports.generate_report(SAMPLE, 'fake', groq_api_key='fake-groq')
    assert source == 'groq'
    assert reports.verified_facts(SAMPLE) in report
    assert 'current-1' in report
    groq.assert_called_once()


def test_success_skips_backup():
    with patch.object(reports, '_gemini_narrative', return_value=TEXT), patch.object(reports, '_groq_narrative') as groq:
        assert reports.generate_report(SAMPLE, 'fake', groq_api_key='fake')[1] == 'gemini'
        groq.assert_not_called()


def test_groq_without_gemini_key():
    with patch.object(reports, '_gemini_narrative') as gemini, patch.object(reports, '_groq_narrative', return_value=TEXT):
        assert reports.generate_report(SAMPLE, None, groq_api_key='fake')[1] == 'groq'
        gemini.assert_not_called()


@pytest.mark.parametrize('value', ['', 'short', None, 'x'*4001])
def test_invalid_outputs_use_template(value):
    with patch.object(reports, '_gemini_narrative', return_value=value), patch.object(reports, '_groq_narrative', return_value=value):
        report, source = reports.generate_report(SAMPLE, 'fake', groq_api_key='fake')
        assert source == 'template'
        assert report == reports.deterministic_report(SAMPLE)


def test_both_down_no_sensitive_logs(caplog):
    with patch.object(reports, '_gemini_narrative', side_effect=TimeoutError('secret-key')), patch.object(reports, '_groq_narrative', side_effect=RuntimeError('secret-key')):
        assert reports.generate_report(SAMPLE, 'fake', groq_api_key='fake')[1] == 'template'
    assert 'secret-key' not in caplog.text


@pytest.mark.parametrize('finish,content', [('stop', TEXT), ('length', TEXT), ('stop', None)])
def test_groq_transport(finish, content):
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value.read.return_value = json.dumps({'choices': [{'finish_reason': finish, 'message': {'content': content}}]}).encode()
    with patch.object(reports, 'build_opener', return_value=opener):
        if finish != 'stop':
            with pytest.raises(ValueError):
                reports._groq_narrative('public facts', 'fake', 'openai/gpt-oss-20b')
        else:
            assert reports._groq_narrative('public facts', 'fake', 'openai/gpt-oss-20b') == content
    req = opener.open.call_args.args[0]
    assert req.full_url == 'https://api.groq.com/openai/v1/chat/completions'
    assert opener.open.call_args.kwargs['timeout'] == 15
    body = json.loads(req.data)
    assert body['stream'] is False
    assert 'tools' not in body


def test_groq_response_size_limit():
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value.read.return_value = b'x'*65537
    with patch.object(reports, 'build_opener', return_value=opener), pytest.raises(ValueError):
        reports._groq_narrative('facts', 'fake', 'model')
