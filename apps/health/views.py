from django.db import connection
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def healthz(request):
    try:
        connection.ensure_connection()
        db_status = "ok"
    except Exception as exc:
        db_status = f"error: {exc}"
    return Response({"status": "ok", "db": db_status})
