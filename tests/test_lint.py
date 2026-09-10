from poster.lint import lint_draft, word_count
from tests.conftest import sample_markdown

BANNED = ["game-changer", "delve"]


def test_sample_passes():
    rep = lint_draft(sample_markdown(), banned=BANNED, min_words=300, max_words=2400)
    assert rep.ok, rep.as_text()


def test_missing_section_and_banned_phrase():
    md = sample_markdown().replace("## Signal vs. noise", "## Hot takes") + "\n\nThis is a game-changer."
    rep = lint_draft(md, banned=BANNED, min_words=300, max_words=2400)
    assert any("missing required section: 'Signal vs. noise'" in e for e in rep.errors)
    assert any("unexpected section heading" in e for e in rep.errors)
    assert any("banned phrase" in e for e in rep.errors)


def test_signoff_and_length():
    md = sample_markdown() + "\n\nThat's all for this week!"
    rep = lint_draft(md, banned=BANNED, min_words=5000, max_words=6000)
    assert any("sign-off" in e for e in rep.errors)
    assert any("too short" in e for e in rep.errors)


def test_word_count_ignores_urls():
    assert word_count("[a b](https://x.y/z) c") == 3
