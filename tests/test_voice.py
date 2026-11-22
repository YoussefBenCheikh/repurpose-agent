import json
import uuid
from pathlib import Path

from repurpose_agent.config import Settings
from repurpose_agent.graph import build_graph
from repurpose_agent.schemas import Platform
from repurpose_agent.voice import BrandPost, HashEmbedder, MemoryVoiceStore, load_posts

from .fakes import FakeLLM

ROOT = Path(__file__).parent.parent


def store_with(*posts: tuple[str, str]) -> MemoryVoiceStore:
    store = MemoryVoiceStore(HashEmbedder())
    store.add([BrandPost(platform=p, text=t) for p, t in posts])
    return store


def test_hash_embedder_ranks_overlapping_text_higher():
    e = HashEmbedder()
    q, near, far = e.embed(["postgres job queue", "a postgres queue for jobs", "compost bins"])
    dot = lambda a, b: sum(x * y for x, y in zip(a, b, strict=True))  # noqa: E731
    assert dot(q, near) > dot(q, far)


def test_memory_store_filters_by_platform_dedupes_and_ranks():
    store = store_with(
        ("x", "postgres queues are underrated"),
        ("x", "my morning routine"),
        ("linkedin", "postgres queues at work"),
        ("x", "postgres queues are underrated"),  # duplicate
    )
    assert store.count() == 3 and store.count(Platform.X) == 2
    assert store.search("postgres queue", Platform.X, k=1) == ["postgres queues are underrated"]
    assert store.search("postgres", Platform.PINTEREST, k=3) == []
    assert store.add([BrandPost(platform="x", text="my morning routine")]) == 0


def test_load_posts_json_and_jsonl(tmp_path):
    jsonl = tmp_path / "p.jsonl"
    jsonl.write_text('{"platform": "x", "text": "a"}\n{"platform": "linkedin", "text": "b"}\n')
    assert [p.platform for p in load_posts(jsonl)] == [Platform.X, Platform.LINKEDIN]

    shipped = load_posts(ROOT / "brand" / "posts.json")
    assert {p.platform for p in shipped} == set(Platform)


def test_retrieved_examples_reach_writer_and_critic_for_the_right_platform():
    store = store_with(
        ("x", "Here's the thing about X posts."),
        ("linkedin", "LinkedIn voice sample."),
    )
    llm = FakeLLM()
    graph = build_graph(llm, Settings(voice_examples=2), voice_store=store)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke({"text": "Postgres is a great queue. " * 20}, config)

    state = graph.get_state(config).values
    assert state["voice"][Platform.X] == ["Here's the thing about X posts."]
    assert state["voice"][Platform.PINTEREST] == []

    x_prompts = [p for p in llm.prompts if "Platform: X" in p]
    assert x_prompts and all("Here's the thing about X posts." in p for p in x_prompts)
    assert all("LinkedIn voice sample." not in p for p in x_prompts)
    pin_prompts = [p for p in llm.prompts if "Platform: Pinterest" in p]
    assert all("<brand_voice_examples>" not in p for p in pin_prompts)


def test_no_store_means_no_examples():
    llm = FakeLLM()
    graph = build_graph(llm, Settings())
    graph.invoke(
        {"text": "Postgres is a great queue. " * 20},
        {"configurable": {"thread_id": str(uuid.uuid4())}},
    )
    assert all("<brand_voice_examples>" not in p for p in llm.prompts)


def test_shipped_brand_file_is_valid_json():
    assert len(json.loads((ROOT / "brand" / "posts.json").read_text())) >= 6
