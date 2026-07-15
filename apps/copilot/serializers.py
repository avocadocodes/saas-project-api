from rest_framework import serializers
from .models import Document


class DocumentSerializer(serializers.ModelSerializer):
    chunk_count = serializers.IntegerField(source="chunks.count", read_only=True)

    class Meta:
        model = Document
        fields = ["id", "title", "content", "chunk_count", "created_at"]
        read_only_fields = ["id", "chunk_count", "created_at"]


class DocumentListSerializer(serializers.ModelSerializer):
    chunk_count = serializers.IntegerField(source="chunks.count", read_only=True)

    class Meta:
        model = Document
        fields = ["id", "title", "chunk_count", "created_at"]
        read_only_fields = fields
