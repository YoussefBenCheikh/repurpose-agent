from pathlib import Path

from repurpose_agent.config import Settings
from repurpose_agent.demo import DemoLLM
from repurpose_agent.evals.rules import check_draft
from repurpose_agent.evals.runner import EvalCase, load_cases, run_eval
from repurpose_agent.schemas import Draft, LinkedInPost, PinterestPin, Platform, XThread

SOURCE = "Postgres handled 2,000 jobs per second with 8 workers. Retry after 5 attempts."
TERMS = ["postgres", "queue"]


def failed(draft: Draft) -> set[str]:
    return {r.rule for r in check_draft(draft, SOURCE, TERMS) if not r.passed}


def x(*tweets: str) -> Draft:
    return Draft(platform=Platform.X, content=XThread(tweets=list(tweets)))


def test_numbers_must_come_from_source():
    assert failed(x("Postgres did 2000 jobs/sec", "8 workers, 5 attempts")) == set()
    assert "no_invented_numbers" in failed(x("Postgres is 10x faster", "Trust me"))


def test_thread_numbering_is_not_an_invented_number():
    assert "no_invented_numbers" not in failed(x("Postgres queues 🧵", "1. Use SKIP LOCKED\n2/5"))


def test_key_terms_and_x_hook():
    assert failed(x("#tips Redis is fine", "nothing else")) == {
        "mentions_key_term",
        "x_hook_has_no_hashtag",
    }


def test_linkedin_rules():
    long_hook = "Postgres " * 30
    post = LinkedInPost(body=f"{long_hook}\n\nThat's it.", hashtags=["a", "b", "c"])
    assert failed(Draft(platform=Platform.LINKEDIN, content=post)) == {
        "linkedin_hook_fits_preview",
        "linkedin_invites_comments",
    }


def test_pinterest_title_keyword():
    pin = PinterestPin(
        title="Ten tips",
        description="A Postgres queue guide",
        hashtags=["a", "b", "c"],
        image_prompt="2:3 image",  # image prompt numbers are ignored
        board_suggestion="Dev",
    )
    assert failed(Draft(platform=Platform.PINTEREST, content=pin)) == {
        "pinterest_title_has_keyword"
    }


def test_dataset_loads_and_demo_eval_passes():
    cases = load_cases(Path(__file__).parent.parent / "evals" / "cases.json")
    assert len(cases) >= 4 and len({c.id for c in cases}) == len(cases)

    llm = DemoLLM(delay=0)
    report = run_eval(cases[:2], llm, Settings(), judge=llm, model_name="demo")
    assert report.errors == 0
    assert report.rule_pass_rate == 1.0
    assert report.judge_means()["faithfulness"] == 4
    assert "Rule pass rate **100%**" in report.to_markdown()


def test_case_errors_are_reported_not_raised():
    class Broken:
        def generate(self, schema, system, user):
            raise RuntimeError("boom")

    case = EvalCase(id="c", title="t", text="Some text " * 30, must_mention=["text"])
    report = run_eval([case], Broken(), Settings())
    assert report.errors == 1 and "boom" in report.cases[0].error
