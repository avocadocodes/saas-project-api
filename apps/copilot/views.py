from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.projects.models import Project, Task
from . import answer as answer_mod
from . import embeddings, ingest, retrieval, verification
from .models import Document, DocumentChunk
from .serializers import DocumentSerializer, DocumentListSerializer

MAX_TASK_CANDIDATES = 12
MAX_DOC_CANDIDATES = 6


class CopilotAskView(APIView):
    """Grounded, self-verifying answer over the org's tasks, projects, and docs."""

    def post(self, request):
        question = (request.data.get("question") or "").strip()
        if not question:
            return Response({"detail": "A question is required."}, status=400)

        org = request.user.organization

        # Lexical candidates: projects + tasks
        projects = list(Project.objects.filter(organization=org).order_by("created_at"))
        tasks = list(
            Task.objects.filter(project__organization=org)
            .select_related("project", "assignee").order_by("created_at")
        )
        lexical = retrieval.rank_lexical(
            question, retrieval.build_documents(projects, tasks), MAX_TASK_CANDIDATES
        )

        # Vector candidates: document chunks
        doc_candidates = []
        q_vec = embeddings.embed_text(question)
        if q_vec:
            chunks = list(
                DocumentChunk.objects.filter(organization=org).select_related("document")
            )
            doc_candidates = retrieval.rank_chunks(q_vec, chunks, MAX_DOC_CANDIDATES)

        candidates = doc_candidates + lexical
        context = answer_mod.build_context(candidates)

        raw = answer_mod.generate(question, context)
        if raw is None:
            return Response({
                "answer": "The copilot is temporarily unavailable. Please try again.",
                "citations": [], "grounded": False, "abstained": False,
                "verification": None, "model": None,
            })

        abstained = answer_mod.is_abstention(raw)
        citations = answer_mod.extract_citations(raw, candidates)
        grounded = (not abstained) and len(citations) > 0

        verify = None
        if grounded:
            verify = verification.verify(raw, context)

        return Response({
            "answer": raw,
            "citations": citations,
            "grounded": grounded,
            "abstained": abstained,
            "verification": verify,
            "model": settings.COPILOT_MODEL,
            "retrieved": {
                "documents": len(doc_candidates),
                "tasks_projects": len(lexical),
            },
        })


class DocumentsView(APIView):
    """List documents in the org, or add one (chunked + embedded on save)."""

    def get(self, request):
        docs = Document.objects.filter(organization=request.user.organization)
        return Response(DocumentListSerializer(docs, many=True).data)

    def post(self, request):
        serializer = DocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = Document.objects.create(
            organization=request.user.organization,
            created_by=request.user,
            title=serializer.validated_data["title"],
            content=serializer.validated_data.get("content", ""),
        )
        chunks = ingest.ingest_document(document)
        data = DocumentSerializer(document).data
        data["embedded"] = embeddings.embeddings_configured() and chunks > 0
        return Response(data, status=status.HTTP_201_CREATED)


class DocumentDetailView(APIView):
    def get(self, request, document_id):
        doc = Document.objects.filter(
            id=document_id, organization=request.user.organization
        ).first()
        if not doc:
            return Response({"detail": "Document not found."}, status=404)
        return Response(DocumentSerializer(doc).data)

    def delete(self, request, document_id):
        doc = Document.objects.filter(
            id=document_id, organization=request.user.organization
        ).first()
        if not doc:
            return Response({"detail": "Document not found."}, status=404)
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
