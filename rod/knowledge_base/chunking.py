"""
knowledge_base/chunking.py
Splits document text into embedding-sized chunks before it hits ChromaDB.

Why chunking at all:
all-MiniLM-L6-v2 has a hard 256 word-piece token limit. Anything past that is
silently truncated by sentence-transformers before embedding — no error, the
tail of the document just never becomes searchable. At ~4-4.5 chars/token in
English, a document anywhere near the API's 2000-char cap (~400-500 tokens)
already exceeds that limit today, so long SOPs/cases are quietly losing their
back half from the embedding.

Chunking also improves retrieval precision, not just correctness: a single
embedding for a 4-step SOP smears every step's semantics into one vector, so
a query about step 3 alone competes poorly against short, on-topic documents.
Splitting into chunks gives each semantic unit its own vector and its own
similarity score, which matters more here than usual because n_results is
capped at 5 (spec) — every slot should be the most relevant unit available,
not a diluted whole-document average.

Why these numbers:
max_chars=800 stays well under the 256-token ceiling even for punctuation-
or number-heavy retail text (worst case ~3 chars/token -> ~266 tokens; typical
prose is closer to 150-180 tokens for 800 chars). overlap_chars=100 preserves
context that spans a chunk boundary (a step referencing "the supplier flagged
above" one sentence earlier) without meaningfully hurting embedding quality.

Splitting prefers the strongest semantic boundary available, falling through
to a weaker one only when a unit at the current level still exceeds
max_chars: blank-line paragraphs first, then numbered list items (SOPs here
are written as inline "(1) ... (2) ... (3) ..." steps rather than
blank-line-separated ones — see seeds/seed_knowledge.py), then sentences, and
finally a hard character split as the last resort so no chunk ever exceeds
the limit. This keeps a whole SOP step or case paragraph in one chunk
whenever it fits, instead of the old pure-sentence splitter potentially
cutting a step in half or fusing unrelated steps together.
"""
import re

MAX_CHARS = 800
OVERLAP_CHARS = 100

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_LIST_ITEM_SPLIT_RE = re.compile(r"(?=(?<!\S)\(\d+\)\s)")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?\n])\s+")


def _split_into_atoms(text: str, max_chars: int) -> list[str]:
    """
    Breaks text into pieces no larger than max_chars, preferring to keep
    semantic units (paragraphs, then numbered list items, then sentences)
    intact and only falling through to a harder split when a unit still
    exceeds max_chars on its own.
    """
    atoms: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT_RE.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            atoms.append(paragraph)
            continue

        items = [i.strip() for i in _LIST_ITEM_SPLIT_RE.split(paragraph) if i.strip()]
        for item in items:
            if len(item) <= max_chars:
                atoms.append(item)
                continue

            sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(item) if s.strip()]
            for sentence in sentences:
                if len(sentence) <= max_chars:
                    atoms.append(sentence)
                else:
                    # Single sentence longer than max_chars — hard-split, no clean boundary available.
                    atoms.extend(sentence[i:i + max_chars] for i in range(0, len(sentence), max_chars))
    return atoms


def chunk_text(text: str, max_chars: int = MAX_CHARS, overlap_chars: int = OVERLAP_CHARS) -> list[str]:
    """
    Splits text into <=max_chars chunks along the strongest available
    semantic boundary (paragraph, numbered list item, then sentence), with
    overlap_chars of trailing context carried into the start of each
    subsequent chunk. Returns [text] unchanged if it already fits in one chunk.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    atoms = _split_into_atoms(text, max_chars)

    chunks: list[str] = []
    current = ""
    for atom in atoms:
        candidate = f"{current} {atom}".strip() if current else atom
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = atom
    if current:
        chunks.append(current)

    if overlap_chars <= 0 or len(chunks) <= 1:
        return chunks

    overlapped = [chunks[0]]
    for i in range(1, len(chunks)):
        prev_tail = chunks[i - 1][-overlap_chars:]
        overlapped.append(f"{prev_tail} {chunks[i]}".strip())
    return overlapped
