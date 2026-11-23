from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="Course",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("course_number", models.CharField(max_length=20, unique=True)),
                ("course_name", models.CharField(max_length=120)),
            ],
            options={"ordering": ["course_number"]},
        ),
        migrations.CreateModel(
            name="StaffAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("Instructor", "Instructor"), ("TA", "TA")], max_length=10)),
                ("course", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="staff_assignments", to="OfficeHourSchedulingApp.course")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="course_staff_assignments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [
                models.UniqueConstraint(fields=("course", "user"), name="unique_course_staff"),
                models.UniqueConstraint(condition=models.Q(role="Instructor"), fields=("course",), name="one_course_instructor"),
                models.CheckConstraint(condition=models.Q(role__in=["Instructor", "TA"]), name="valid_staff_role"),
            ]},
        ),
        migrations.CreateModel(
            name="Availability",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()), ("start_time", models.TimeField()), ("end_time", models.TimeField()),
                ("location", models.CharField(max_length=120)),
                ("assignment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="availability", to="OfficeHourSchedulingApp.staffassignment")),
            ],
            options={"ordering": ["date", "start_time"], "abstract": False, "constraints": [models.CheckConstraint(condition=models.Q(end_time__gt=models.F("start_time")), name="availability_positive_range")]},
        ),
        migrations.CreateModel(
            name="Enrollment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("course", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="enrollments", to="OfficeHourSchedulingApp.course")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="course_enrollments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("course", "student"), name="unique_course_student")]},
        ),
        migrations.CreateModel(
            name="OfficeHour",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()), ("start_time", models.TimeField()), ("end_time", models.TimeField()),
                ("location", models.CharField(max_length=120)),
                ("assignment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="office_hours", to="OfficeHourSchedulingApp.staffassignment")),
            ],
            options={"ordering": ["date", "start_time"], "abstract": False, "constraints": [models.CheckConstraint(condition=models.Q(end_time__gt=models.F("start_time")), name="office_hour_positive_range")]},
        ),
        migrations.CreateModel(
            name="Reservation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("office_hour", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reservations", to="OfficeHourSchedulingApp.officehour")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="office_hour_reservations", to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("office_hour", "student"), name="unique_office_hour_student")]},
        ),
    ]
