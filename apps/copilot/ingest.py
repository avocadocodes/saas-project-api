"""Chunk a document and embed each chunk."""

from .embeddings import embed_texts
from .models import DocumentChunk

CHUNK_SIZE = 700       # characters
CHUNK_OVERLAP = 120


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = (text or "").strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def ingest_document(document):
    """(Re)build the chunks + embeddings for a document. Returns chunk count."""
    document.chunks.all().delete()
    pieces = chunk_text(document.content)
    if not pieces:
        return 0

    vectors = embed_texts(pieces)
    rows = [
        DocumentChunk(
            document=document,
            organization=document.organization,
            chunk_index=i,
            text=piece,
            embedding=vector or [],
        )
        for i, (piece, vector) in enumerate(zip(pieces, vectors))
    ]
    DocumentChunk.objects.bulk_create(rows)
    return len(rows)
