import uuid
from django.db import models


class Document(models.Model):
    """A text document uploaded to a workspace for the copilot to draw on."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="documents",
    )
    title = models.CharField(max_length=255)
    content = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class DocumentChunk(models.Model):
    """A chunk of a document with its embedding (stored as a float list so the
    ranking works on any database - cosine similarity is computed in Python)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="document_chunks",
    )
    chunk_index = models.IntegerField(default=0)
    text = models.TextField()
    embedding = models.JSONField(default=list)

    class Meta:
        ordering = ["document_id", "chunk_index"]

    def __str__(self):
        return f"{self.document.title} #{self.chunk_index}"
