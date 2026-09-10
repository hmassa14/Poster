from datetime import datetime, timezone

from poster.render import Renderer, plain_text, strip_title_and_dek
from poster.schemas import SEOPackage, SocialPosts
from tests.conftest import sample_markdown


def test_strip_title_and_dek():
    body = strip_title_and_dek(sample_markdown())
    assert body.startswith("## The week in one paragraph")


def test_render_issue_and_site(project):
    seo = SEOPackage(slug="a-b", title_tag="T", meta_description="M", headline_h1="H", excerpt="E", keywords=["k"],
                     tags=["models"], social=SocialPosts(linkedin="l", x="x", threads="t"), email_subject="S",
                     email_preheader="P", og_title="O", og_description="D", image_alt="I")
    r = Renderer(project)
    out = r.render_issue(issue_id="2026-09-10", body_markdown=sample_markdown(), seo=seo, title="Title", dek="Dek",
                         issues_index=[], published_at=datetime(2026, 9, 10, tzinfo=timezone.utc))
    assert out["url"].endswith("/issues/a-b/")
    assert '<meta name="description" content="M">' in out["page"]
    assert "unsubscribe_url" in out["email"] and "Title" in out["email"]
    files = r.write_site([{"issue_id": "2026-09-10", "slug": "a-b", "title": "Title", "excerpt": "E",
                           "published_at": "2026-09-10T00:00:00+00:00"}], {"a-b": out["page"]})
    names = {f.name for f in files}
    assert {"index.html", "feed.xml", "sitemap.xml", "robots.txt", "style.css"} <= names
    feed = (project.site_dir / "feed.xml").read_text()
    assert "<pubDate>Thu, 10 Sep 2026" in feed


def test_plain_text():
    assert plain_text("**Bold** [x](https://a.b)") == "Bold x (https://a.b)"
