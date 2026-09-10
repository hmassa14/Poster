from poster.schemas import Draft, SEOPackage, SocialPosts
from poster.stages.seo import normalize_seo


def _seo(slug="hello world"):
    return SEOPackage(slug=slug, title_tag="t" * 80, meta_description="m" * 200, headline_h1="x", excerpt="e",
                      keywords=["a"], tags=["Models"], social=SocialPosts(linkedin="l", x="x" * 300, threads="t"),
                      email_subject="s" * 70, email_preheader="p", og_title="o", og_description="d", image_alt="i")


def test_limits_and_slug_uniqueness():
    draft = Draft(title="Title Here", dek="d", body_markdown="", stories_covered=[])
    out = normalize_seo(_seo(), draft, existing_slugs={"hello-world"})
    assert out.slug == "hello-world-2"
    assert len(out.title_tag) <= 61
    assert len(out.meta_description) <= 156
    assert len(out.email_subject) <= 61
    assert len(out.social.x) <= 271
    assert out.headline_h1 == "Title Here"
    assert out.tags == ["models"]


def test_bad_slug_falls_back_to_title():
    draft = Draft(title="A Real Title", dek="d", body_markdown="", stories_covered=[])
    out = normalize_seo(_seo(slug="!!!"), draft, existing_slugs=set())
    assert out.slug == "a-real-title"
