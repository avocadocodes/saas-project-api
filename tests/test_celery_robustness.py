import pytest
from django.utils import timezone
from datetime import timedelta
from apps.projects.models import Task, Report
from apps.projects.tasks import generate_project_report, purge_old_reports


@pytest.mark.django_db
def test_report_task_is_idempotent(owner_a, project_a):
    """Calling generate_project_report twice on a READY report is a no-op."""
    Task.objects.create(project=project_a, title="T1", status=Task.Status.DONE)
    report = Report.objects.create(project=project_a, requested_by=owner_a)

    generate_project_report(str(report.id))

    report.refresh_from_db()
    assert report.status == Report.Status.READY
    first_completed_at = report.completed_at

    # Second call must not change completed_at
    generate_project_report(str(report.id))

    report.refresh_from_db()
    assert report.status == Report.Status.READY
    assert report.completed_at == first_completed_at


@pytest.mark.django_db
def test_report_task_counts_are_correct(owner_a, project_a):
    Task.objects.create(project=project_a, title="T1", status=Task.Status.DONE)
    Task.objects.create(project=project_a, title="T2", status=Task.Status.DONE)
    Task.objects.create(project=project_a, title="T3", status=Task.Status.IN_PROGRESS)
    report = Report.objects.create(project=project_a, requested_by=owner_a)

    generate_project_report(str(report.id))

    report.refresh_from_db()
    assert report.data["done"] == 2
    assert report.data["in_progress"] == 1
    assert report.data["total_tasks"] == 3
    assert report.data["completion_percentage"] == pytest.approx(66.67)


@pytest.mark.django_db
def test_purge_old_reports_deletes_old_and_keeps_new(owner_a, project_a):
    old_report = Report.objects.create(project=project_a, requested_by=owner_a)
    Report.objects.filter(pk=old_report.pk).update(
        created_at=timezone.now() - timedelta(days=31)
    )

    new_report = Report.objects.create(project=project_a, requested_by=owner_a)

    deleted = purge_old_reports()

    assert deleted == 1
    assert not Report.objects.filter(pk=old_report.pk).exists()
    assert Report.objects.filter(pk=new_report.pk).exists()


@pytest.mark.django_db
def test_purge_returns_zero_when_nothing_old(owner_a, project_a):
    Report.objects.create(project=project_a, requested_by=owner_a)
    deleted = purge_old_reports()
    assert deleted == 0


@pytest.mark.django_db
def test_purge_beat_schedule_is_configured():
    from django.conf import settings
    schedule = getattr(settings, "CELERY_BEAT_SCHEDULE", {})
    assert "purge-old-reports-nightly" in schedule
    entry = schedule["purge-old-reports-nightly"]
    assert entry["task"] == "apps.projects.tasks.purge_old_reports"
