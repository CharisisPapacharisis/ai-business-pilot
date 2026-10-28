"""Normalize and compact tool evidence without changing saved source data."""

UNVERIFIED_EMPTY_RESULT = "UNVERIFIED_EMPTY_RESULT"


def content_text(content: object) -> str:
    """Extract readable text from strings or MCP content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def compact_text(text: str, limit: int) -> str:
    """Keep both ends of long text within a character budget."""
    if len(text) <= limit:
        return text
    marker = "\n... content compacted for model context ...\n"
    remaining = limit - len(marker)
    head = int(remaining * 0.65)
    return f"{text[:head]}{marker}{text[-(remaining - head) :]}"


def compact_evidence(items: list[str], max_chars: int = 5000) -> str:
    """Build a bounded, source-balanced view for the reporter and drafter."""
    latest_by_tool = {}
    for item in items:
        tool_name = item.partition(":")[0]
        latest_by_tool[tool_name] = item

    def priority(item: str) -> int:
        tool_name = item.partition(":")[0]
        if "execute_readonly_query" in tool_name or "linear_" in tool_name:
            return 3
        if "describe_table" in tool_name:
            return 1
        return 0

    selected = []
    remaining = max_chars
    for item in sorted(latest_by_tool.values(), key=priority, reverse=True):
        if remaining <= 0:
            break
        compacted = compact_text(item, min(2200, remaining))
        selected.append(compacted)
        remaining -= len(compacted) + 2
    return "\n\n".join(selected)
