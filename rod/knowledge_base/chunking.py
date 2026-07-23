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

Splitting happens on sentence boundaries so chunks stay semantically coherent
instead of cutting mid-sentence; a single run-on "sentence" longer than
max_chars is hard-split as a last resort so no chunk ever exceeds the limit.
"""
import re

MAX_CHARS = 800
OVERLAP_CHARS = 100

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?\n])\s+")


def chunk_text(text: str, max_chars: int = MAX_CHARS, overlap_chars: int = OVERLAP_CHARS) -> list[str]:
    """
    Splits text into <=max_chars chunks on sentence boundaries, with
    overlap_chars of trailing context carried into the start of each
    subsequent chunk. Returns [text] unchanged if it already fits in one chunk.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = _SENTENCE_SPLIT_RE.split(text)

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(sentence) > max_chars:
            # Single sentence longer than max_chars — hard-split, no clean boundary available.
            for i in range(0, len(sentence), max_chars):
                chunks.append(sentence[i:i + max_chars])
            current = ""
        else:
            current = sentence

    if current:
        chunks.append(current)

    if overlap_chars <= 0 or len(chunks) <= 1:
        return chunks

    overlapped = [chunks[0]]
    for i in range(1, len(chunks)):
        prev_tail = chunks[i - 1][-overlap_chars:]
        overlapped.append(f"{prev_tail} {chunks[i]}".strip())
    return overlapped
