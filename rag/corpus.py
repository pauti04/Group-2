"""Knowledge-base loading and section parsing.

Shared by the day-one stub and the real pipeline, so both are grounded in the
same source text. Owner: person 2 (but stable — unlikely to need changes).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent.parent / "knowledge_base"


@dataclass
class Document:
    filename: str
    text: str
    sections: dict[str, str]

    @property
    def ticket_category(self) -> str | None:
        return self.sections.get("Ticket Category")

    @property
    def resolution(self) -> str | None:
        return self.sections.get("Resolution")


def _split_sections(text: str) -> dict[str, str]:
    """Split a KB doc on its `## Heading` lines into {heading: body}."""
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^##\s+(.*\S)\s*$", line)
        if match:
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            current = match.group(1)
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    return sections


def load_documents(kb_dir: Path = KB_DIR) -> list[Document]:
    docs = []
    for path in sorted(kb_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        docs.append(Document(filename=path.name, text=text, sections=_split_sections(text)))
    if not docs:
        raise FileNotFoundError(f"No markdown documents found in {kb_dir}")
    return docs
