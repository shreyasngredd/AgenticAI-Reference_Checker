"""Terminal chatbot for formatting references.

Uses claude-agent-sdk's ClaudeSDKClient, so the conversation keeps its
context across turns (you can say "now give me that one in Harvard").

The agent has exactly two tools, both calling the free Crossref API:
- lookup_doi(doi):       metadata for one DOI.
- search_crossref(title): find a paper by its title.

To keep the agent from writing references from memory, the tools also do
the checking in code: they format the reference in APA 7, Chicago and
Harvard (using agent.py's formatters), give a label ("OK", "Check" or
"Not found") with the reasons, and build the Google Scholar search link.
The link is only built, never fetched.

Usage:
    python chat.py        (type "exit" to quit)
"""

import asyncio

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)

import agent  # Reuses the Crossref, checking and formatting code from refs mode.

SYSTEM_PROMPT = """You are a reference-formatting assistant.

Style:
- Use APA 7th by default. Use Chicago or Harvard only if the user asks.

Rules:
- Never write a reference from memory. Always call a lookup tool first:
  lookup_doi if the user gives a DOI, otherwise search_crossref with the title.
- Use only what the tools return. Each result has the reference already
  formatted in all three styles ("formatted"): copy the one for the style in use.
  Do not add, fix or guess anything (no authors, years, pages or DOIs of your own).
- Each result has a "label" worked out by code: "OK", "Check" or "Not found",
  with "reasons". Show the label and reasons with the reference; never change them.
  If a tool returns an error, the label is "Not found": say so plainly.
- search_crossref returns "match" only when exactly one paper's title is
  clearly the closest. If "match" is null, show its label ("Not found", or
  "Check" when there are several or only weak candidates) and reasons, and
  ask for the DOI. You may
  list the "candidates" as possibilities, but never present one as their reference.
- APA titles are in sentence case. If "original_title" is not null and you
  show APA, add it on its own line: Original title: <original_title>
- After each reference, add the "scholar_link" from the tool result exactly as
  given, on its own line: Google Scholar: <link>
- If the user has no DOI or title, or the details they need are missing, ask
  them for it instead of guessing.
"""


def checked_reference(citation):
    """Turn Crossref metadata into a checked result for the agent.

    Everything here is done in code, not by the model: the formatted
    references, the label and its reasons, and the Google Scholar link.
    """
    warnings = agent.validate_reference(citation, citation["type"])
    # APA sentence case: flag titles whose casing code isn't sure of.
    warnings += agent.title_case_warnings(citation)
    return {
        "formatted": {style: agent.format_reference(citation, style) for style in agent.STYLES},
        "label": "Check" if warnings else "OK",
        "reasons": warnings,
        # The title as Crossref gives it, when the APA title is cased differently.
        "original_title": agent.original_title_note(citation),
        "scholar_link": agent.search_links(citation)["google_scholar"],
        "metadata": citation,
    }


def search_titles(title):
    """Search Crossref for a title. Returns (result, None) or (None, error message).

    The matching is agent.search_crossref_title, the same code refs mode
    uses, so the rules (thresholds in agent.py) are in one place. Only a
    clear match gets "match"; otherwise the label is "Check" (several or
    weak candidates) or "Not found", with the reasons and candidates.
    """
    search, error = agent.search_crossref_title(title)
    if error:
        return None, error

    match, label = None, {"check": "Check", "not_found": "Not found"}.get(search["outcome"])
    if search["outcome"] == "match":
        match = checked_reference(search["citation"])
        match["title_similarity"] = search["candidates"][0]["title_similarity"]
        label = match["label"]
    return {
        "match": match,
        "label": label,
        "reasons": search["reasons"],
        # Short list of near misses, so the user can say which one they meant.
        "candidates": search["candidates"],
    }, None


@tool(
    "lookup_doi",
    "Look up one DOI on Crossref. Returns the reference formatted in APA 7, "
    "Chicago and Harvard, a label (OK / Check) with reasons, and a Google Scholar link.",
    {"doi": str},
)
async def lookup_doi(args):
    """Custom tool: fetch and check the metadata for one DOI."""
    doi = agent.clean_doi(args.get("doi", ""))
    if not doi:
        return agent.error_result("No DOI given. Pass a DOI like 10.1038/nature14539.")
    # The request waits on the network, so run it in a background thread.
    citation, error = await asyncio.to_thread(agent.lookup_doi, doi)
    if error:
        return agent.error_result(f"Not found: {error}")
    return agent.tool_json(checked_reference(citation))


@tool(
    "search_crossref",
    "Search Crossref by title. Returns 'match' (formatted references, label, "
    "reasons, Google Scholar link) only if a title is close enough, otherwise "
    "match is null and 'candidates' lists the nearest papers.",
    {"title": str},
)
async def search_crossref(args):
    """Custom tool: find a paper on Crossref by its title."""
    title = args.get("title", "").strip()
    if not title:
        return agent.error_result("No title given.")
    result, error = await asyncio.to_thread(search_titles, title)
    if error:
        return agent.error_result(f"Not found: {error}")
    return agent.tool_json(result)


# Bundle the two tools into an in-process MCP server named "crossref".
CROSSREF_SERVER = create_sdk_mcp_server(name="crossref", tools=[lookup_doi, search_crossref])
CHAT_TOOLS = ["mcp__crossref__lookup_doi", "mcp__crossref__search_crossref"]


async def chat():
    """Read the user's input, send it to the agent, print the reply; repeat."""
    options = ClaudeAgentOptions(
        model="claude-opus-5-5",
        system_prompt=SYSTEM_PROMPT,
        tools=[],  # No built-in tools (no Read, Write, Bash, web...).
        mcp_servers={"crossref": CROSSREF_SERVER},
        allowed_tools=CHAT_TOOLS,  # Only our two Crossref tools.
    )

    print('Reference assistant. Paste a DOI or a title. Type "exit" to quit.')
    # One client for the whole chat, so every turn sees the earlier ones.
    async with ClaudeSDKClient(options=options) as client:
        while True:
            # input() blocks, so run it in a thread to keep the client responsive.
            try:
                text = (await asyncio.to_thread(input, "\nYou: ")).strip()
            except (EOFError, KeyboardInterrupt):
                break  # Ctrl-D / Ctrl-C also quit.
            if text.lower() == "exit":
                break
            if not text:
                continue

            await client.query(text)
            # Print the reply as it arrives, and which tools were called.
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"\nAssistant: {block.text}")
                        elif isinstance(block, ToolUseBlock):
                            print(f"[tool] {block.name.split('__')[-1]}: {block.input}")
    print("Bye.")


if __name__ == "__main__":
    asyncio.run(chat())
