from __future__ import annotations


def safe_markdown(text: str) -> str:
    return str(text).replace("`", "'")


def chunk_lines(lines: list[str], chunk_size: int = 25) -> list[str]:
    chunks: list[str] = []
    for i in range(0, len(lines), chunk_size):
        chunks.append("\n\n".join(lines[i : i + chunk_size]))
    return chunks
