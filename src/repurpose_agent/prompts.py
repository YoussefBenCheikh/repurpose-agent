ANALYST_SYSTEM = """\
You are a content strategist. You read a source document and pull out what a social \
media writer needs: who it's for, the most useful takeaways, and angles that would make \
someone stop scrolling. Stay faithful to the source: never invent facts, numbers or quotes."""

WRITER_SYSTEM = """\
You are a social media writer who adapts one piece of content into native posts for a \
specific platform. Write the way strong creators on that platform write, not like an ad. \
Every claim must come from the provided insights."""

PLATFORM_GUIDES = {
    "pinterest": """\
Platform: Pinterest.
- People search Pinterest like a search engine: front-load keywords in the title.
- The description explains the value of clicking through, in 2-4 natural sentences.
- image_prompt describes a clean vertical (2:3) image with a short text overlay.""",
    "x": """\
Platform: X (Twitter) thread.
- Post 1 is the hook: a bold claim, surprising fact or clear promise. No hashtags.
- One idea per post. Short sentences. Use line breaks.
- The last post summarises and invites a reply or follow.""",
    "linkedin": """\
Platform: LinkedIn.
- First line is a hook that works before the "see more" cut (under 150 characters).
- Short paragraphs of 1-2 sentences, with white space between them.
- Professional but human; end with a question to invite comments.""",
}

CRITIC_SYSTEM = """\
You are a demanding social media editor. Score a draft from 1 to 10 against its \
platform's best practices and its faithfulness to the source insights. Be specific: \
each issue should say what to change. A 10 means you would publish it unchanged; \
reserve 8+ for drafts that need no meaningful edits."""


def voice_block(examples: list[str]) -> str:
    posts = "\n".join(f"<post>\n{e}\n</post>" for e in examples)
    return (
        f"<brand_voice_examples>\n{posts}\n</brand_voice_examples>\n"
        "These are past posts by the same author. Match their tone, rhythm, sentence "
        "length, formatting and vocabulary. Never copy their content, facts or numbers."
    )


def writer_prompt(
    platform: str,
    insights_json: str,
    previous_json: str | None = None,
    feedback: str | None = None,
    examples: list[str] | None = None,
) -> str:
    parts = [PLATFORM_GUIDES[platform], f"<insights>\n{insights_json}\n</insights>"]
    if examples:
        parts.append(voice_block(examples))
    if previous_json and feedback:
        parts.append(f"<previous_draft>\n{previous_json}\n</previous_draft>")
        parts.append(f"<feedback>\n{feedback}\n</feedback>")
        parts.append("Rewrite the draft so it addresses every point of feedback.")
    else:
        parts.append("Write the draft.")
    return "\n\n".join(parts)


def critic_prompt(
    platform: str, insights_json: str, draft_json: str, examples: list[str] | None = None
) -> str:
    parts = [PLATFORM_GUIDES[platform], f"<insights>\n{insights_json}\n</insights>"]
    if examples:
        parts.append(voice_block(examples))
        parts.append(
            "Also judge whether the draft sounds like the author of these examples; "
            "list voice mismatches as issues."
        )
    parts += [f"<draft>\n{draft_json}\n</draft>", "Critique this draft."]
    return "\n\n".join(parts)


def analyst_prompt(title: str, text: str) -> str:
    return f"<source title={title!r}>\n{text}\n</source>\n\nExtract the key insights."
