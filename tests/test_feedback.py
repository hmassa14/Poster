from poster.memory import Memory
from poster.stages import feedback as fb
from tests.conftest import FakeClaude


def test_feedback_digest_updates_style_and_lessons(project):
    inbox = project.feedback_dir / "inbox"
    (inbox / "publisher-note.md").write_text("The 'Also this week' items are too long. Keep them tighter.")
    items = fb.collect(project, pull_github=False)
    assert len(items) == 1 and items[0]["source"] == "publisher"

    memory = Memory(project)
    digest = fb.digest(FakeClaude(), project, memory, items, "(no issues yet)")
    counts = fb.apply_digest(project, memory, digest, items, log=lambda s: None)
    assert counts == {"style": 1, "format": 0, "lessons": 1, "corrections": 0}

    style = (project.publication_dir / "style.md").read_text()
    assert "Keep 'Also this week' items under 110 words." in style
    assert style.index("## Learned rules") < style.index("Keep 'Also this week' items")
    assert memory.lessons() == ["Readers want shorter items. _(from feedback, " + memory.lessons()[0].split("(from feedback, ")[1]]
    assert not list(inbox.glob("*.md"))
    assert (project.feedback_dir / "log.jsonl").exists()
