from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import Organization, User, Invitation


def _split_name(name):
    name = (name or "").strip()
    if not name:
        return "", ""
    parts = name.split(None, 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


class RegisterSerializer(serializers.Serializer):
    organization_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=150, required=False, default="")
    last_name = serializers.CharField(max_length=150, required=False, default="")

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def create(self, validated_data):
        with transaction.atomic():
            org = Organization.objects.create(name=validated_data["organization_name"])
            user = User.objects.create_user(
                email=validated_data["email"],
                password=validated_data["password"],
                first_name=validated_data.get("first_name", ""),
                last_name=validated_data.get("last_name", ""),
                organization=org,
                role=User.Role.OWNER,
            )
        return user


class UserSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source="organization.name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "role", "organization_name"]
        read_only_fields = fields


class MemberSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name", "role"]
        read_only_fields = fields

    def get_name(self, obj):
        full = f"{obj.first_name} {obj.last_name}".strip()
        return full or obj.email.split("@")[0]


class InvitationSerializer(serializers.ModelSerializer):
    invited_by_email = serializers.CharField(source="invited_by.email", read_only=True, default=None)

    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "token", "accepted", "created_at", "invited_by_email"]
        read_only_fields = fields


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=Invitation.Role.choices, default=Invitation.Role.MEMBER)

    def validate_email(self, value):
        org = self.context["organization"]
        if User.objects.filter(email__iexact=value, organization=org).exists():
            raise serializers.ValidationError("This person is already a member.")
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        if Invitation.objects.filter(email__iexact=value, organization=org, accepted=False).exists():
            raise serializers.ValidationError("An invitation for this email is already pending.")
        return value


class AcceptInvitationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=300)
    password = serializers.CharField(write_only=True, min_length=8)
