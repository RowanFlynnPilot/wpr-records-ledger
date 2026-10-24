"""Keep the methodology page honest: it describes every published field, and it
lists the current version of the rules in its changelog."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export  # noqa: E402
import law  # noqa: E402

PAGE = (export.WEB / "methodology.html").read_text(encoding="utf-8")


def described(file: str) -> list[str]:
    table = re.search(rf'data-file="{file}".*?</table>', PAGE, re.S).group(0)
    return re.findall(r"<tr><td><code>([a-z0-9_]+)</code></td>", table)


def test_the_data_dictionary_describes_every_published_field_in_order():
    assert described("scorecard") == list(export.SCORECARD_FIELDS)
    assert described("requests") == list(export.REQUEST_FIELDS)
    assert described("request_events") == list(export.EVENT_FIELDS)
    assert described("meta") == list(export.META_FIELDS)


def test_the_changelog_lists_the_current_rules():
    changes = re.search(r'<ol class="changes" id="changes">(.*?)</ol>', PAGE, re.S).group(1)
    assert f"<code>{law.fingerprint()}</code>" in changes, (
        "law.py changed: add an entry to 'Changes to the rules' in web/methodology.html with "
        f"fingerprint {law.fingerprint()}")

    # CI checks out law.py with LF and Windows with CRLF; both must give this one fingerprint.
