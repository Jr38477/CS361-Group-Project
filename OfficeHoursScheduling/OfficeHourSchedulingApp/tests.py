from datetime import date, time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError
from django.db.models.signals import post_delete
from django.test import Client, TestCase
from django.urls import reverse

from . import services
from .forms import CourseForm
from .models import Availability, Course, Enrollment, OfficeHour, Reservation, StaffAssignment


class CourseWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser(username="admin", email="admin@example.test", password="test-admin-password")
        cls.instructor = User.objects.create_user(username="instructor", first_name="Ada", is_staff=True)
        cls.ta1 = User.objects.create_user(username="ta1", first_name="Grace", is_staff=True)
        cls.ta2 = User.objects.create_user(username="ta2", first_name="Alan", is_staff=True)
        cls.student = User.objects.create_user(username="student")
        for user, role in ((cls.instructor, "Instructor"), (cls.ta1, "TA"), (cls.ta2, "TA"), (cls.student, "Student")):
            group, _ = Group.objects.get_or_create(name=role)
            user.groups.add(group)
        cls.create_url = reverse("courses:create")
        cls.list_url = reverse("courses:list")

    def setUp(self):
        self.client.force_login(self.admin)

    def payload(self, number="CS361"):
        data = {"course_number": number, "course_name": "Software Engineering", "instructor": str(self.instructor.pk), "ta1": str(self.ta1.pk), "ta2": str(self.ta2.pk)}
        for prefix in ("instructor", "ta1", "ta2"):
            data.update({f"{prefix}-TOTAL_FORMS": "1", f"{prefix}-INITIAL_FORMS": "0", f"{prefix}-MIN_NUM_FORMS": "1", f"{prefix}-MAX_NUM_FORMS": "50"})
            data.update(self.range_data(prefix, 0))
        return data

    def range_data(self, prefix, index, location="EMS E180", day="2026-11-23"):
        return {f"{prefix}-{index}-location": location, f"{prefix}-{index}-date": day, f"{prefix}-{index}-start_time": "10:00", f"{prefix}-{index}-end_time": "11:00"}

    def create(self, number="CS361"):
        response = self.client.post(self.create_url, self.payload(number))
        self.assertEqual(response.status_code, 302)
        return Course.objects.get(course_number=number)

    def related_fixture(self, course):
        assignment = course.staff_assignments.get(role="Instructor")
        enrollment = Enrollment.objects.create(course=course, student=self.student)
        office_hour = OfficeHour.objects.create(assignment=assignment, date=date(2026, 11, 23), start_time=time(12), end_time=time(13), location="EMS")
        reservation = Reservation.objects.create(office_hour=office_hour, student=self.student)
        return enrollment, office_hour, reservation

    def record_snapshot(self):
        return {model.__name__: list(model.objects.order_by("pk").values()) for model in (Course, StaffAssignment, Availability, Enrollment, OfficeHour, Reservation, get_user_model())}

    def assert_rejected(self, data):
        before = self.record_snapshot()
        response = self.client.post(self.create_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(before, self.record_snapshot())
        return response

    def test_create_form_lists_only_accounts_with_required_roles(self):
        inactive = get_user_model().objects.create_user(username="inactive", is_active=False)
        inactive.groups.add(Group.objects.get(name="Instructor"))
        response = self.client.get(self.create_url)
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertQuerySetEqual(form.fields["instructor"].queryset, [self.instructor])
        self.assertEqual(set(form.fields["ta1"].queryset), {self.ta1, self.ta2})
        self.assertContains(response, 'name="instructor-TOTAL_FORMS"')

    def test_success_stores_correct_staff_and_availability_and_confirmation(self):
        data = self.payload()
        data["ta1-0-location"] = "TA room"
        response = self.client.post(self.create_url, data, follow=True)
        course = Course.objects.get(course_number="CS361")
        self.assertRedirects(response, reverse("courses:detail", args=[course.pk]))
        self.assertContains(response, "was created successfully")
        self.assertEqual(course.staff_assignments.count(), 3)
        expected = {self.instructor.pk: "Instructor", self.ta1.pk: "TA", self.ta2.pk: "TA"}
        self.assertEqual(dict(course.staff_assignments.values_list("user_id", "role")), expected)
        for assignment in course.staff_assignments.all():
            entry = assignment.availability.get()
            self.assertEqual(entry.date, date(2026, 11, 23))
            self.assertEqual(entry.start_time, time(10))
            self.assertEqual(entry.end_time, time(11))
            self.assertEqual(entry.location, "TA room" if assignment.user_id == self.ta1.pk else "EMS E180")
        Enrollment.objects.create(course=course, student=self.student)
        self.assertEqual(course.enrollments.get().student, self.student)
        self.assertContains(self.client.get(self.list_url), "CS361")

    def test_duplicate_course_preserves_existing_records(self):
        self.related_fixture(self.create())
        response = self.assert_rejected(self.payload())
        self.assertContains(response, "already exists")

    def test_required_text_fields_reject_blank_and_whitespace_and_retain_other_values(self):
        for field in ("course_number", "course_name"):
            for value in ("", "   "):
                with self.subTest(field=field, value=value):
                    data = self.payload()
                    data[field] = value
                    response = self.assert_rejected(data)
                    self.assertIn(field, response.context["form"].errors)
                    self.assertEqual(response.context["form"]["ta1"].value(), str(self.ta1.pk))
                    self.assertEqual(response.context["sections"][1][2].forms[0]["location"].value(), "EMS E180")

    def test_overlength_fields_report_limits(self):
        for field, limit in (("course_number", 20), ("course_name", 120)):
            with self.subTest(field=field):
                data = self.payload()
                data[field] = "x" * (limit + 1)
                response = self.assert_rejected(data)
                self.assertIn(str(limit), str(response.context["form"].errors[field]))

    def test_exact_length_limits_and_trimmed_input_succeed(self):
        data = self.payload(" " + "C" * 20 + " ")
        data["course_name"] = " " + "N" * 120 + " "
        response = self.client.post(self.create_url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Course.objects.get().course_name, "N" * 120)

    def test_trimmed_duplicate_course_is_rejected(self):
        self.create()
        response = self.assert_rejected(self.payload(" CS361 "))
        self.assertContains(response, "already exists")

    def test_each_staff_position_is_required(self):
        for field in ("instructor", "ta1", "ta2"):
            with self.subTest(field=field):
                data = self.payload()
                del data[field]
                response = self.assert_rejected(data)
                self.assertIn(field, response.context["form"].errors)
                self.assertContains(response, "one instructor and two TAs")

    def test_duplicate_ta_and_dual_role_person_are_rejected(self):
        data = self.payload()
        data["ta2"] = str(self.ta1.pk)
        self.assertContains(self.assert_rejected(data), "different people")
        self.instructor.groups.add(Group.objects.get(name="TA"))
        data = self.payload()
        data["ta1"] = str(self.instructor.pk)
        self.assertContains(self.assert_rejected(data), "different people")

    def test_missing_inactive_and_wrong_role_staff_are_rejected(self):
        inactive = get_user_model().objects.create_user(username="inactive-ta", is_active=False)
        inactive.groups.add(Group.objects.get(name="TA"))
        deleted = get_user_model().objects.create_user(username="deleted")
        deleted_id = deleted.pk
        deleted.delete()
        for field, value in (("instructor", self.ta1.pk), ("ta1", self.student.pk), ("ta2", inactive.pk), ("ta1", deleted_id), ("ta2", "invalid")):
            with self.subTest(field=field, value=value):
                data = self.payload()
                data[field] = str(value)
                response = self.assert_rejected(data)
                self.assertIn(field, response.context["form"].errors)
                self.assertContains(response, "existing active")

    def test_availability_required_for_each_person(self):
        for index, prefix in enumerate(("instructor", "ta1", "ta2")):
            with self.subTest(prefix=prefix):
                data = self.payload()
                data[f"{prefix}-TOTAL_FORMS"] = "0"
                response = self.assert_rejected(data)
                self.assertTrue(response.context["sections"][index][2].non_form_errors())
                self.assertContains(response, "Provide at least one")

    def test_missing_and_invalid_availability_fields_are_identified(self):
        cases = (("date", ""), ("date", "2026-02-30"), ("date", "Monday"), ("start_time", ""), ("start_time", "25:00"), ("end_time", ""), ("end_time", "09:00"), ("end_time", "10:00"), ("location", "   "), ("location", "x" * 121))
        for field, value in cases:
            with self.subTest(field=field, value=value):
                data = self.payload()
                data[f"ta2-0-{field}"] = value
                response = self.assert_rejected(data)
                self.assertIn(field, response.context["sections"][2][2].forms[0].errors)
                self.assertEqual(response.context["form"]["course_number"].value(), "CS361")

    def test_multiple_ranges_stay_with_correct_course_and_person(self):
        data = self.payload()
        for prefix, count in (("instructor", 2), ("ta1", 3), ("ta2", 2)):
            data[f"{prefix}-TOTAL_FORMS"] = str(count)
            for index in range(1, count):
                data.update(self.range_data(prefix, index, location=f"{prefix} room {index}", day=f"2026-11-{23 + index}"))
        self.assertEqual(self.client.post(self.create_url, data).status_code, 302)
        course = Course.objects.get()
        for user, prefix, count in ((self.instructor, "instructor", 2), (self.ta1, "ta1", 3), (self.ta2, "ta2", 2)):
            entries = course.staff_assignments.get(user=user).availability.all()
            self.assertEqual(entries.count(), count)
            self.assertEqual(set(entries.values_list("location", flat=True)), {"EMS E180"} | {f"{prefix} room {i}" for i in range(1, count)})

    def test_deleted_ranges_are_not_saved_but_cannot_remove_all_availability(self):
        data = self.payload()
        data["ta1-TOTAL_FORMS"] = "2"
        data.update(self.range_data("ta1", 1, location="Removed room"))
        data["ta1-1-DELETE"] = "on"
        self.assertEqual(self.client.post(self.create_url, data).status_code, 302)
        self.assertEqual(Availability.objects.count(), 3)
        self.assertFalse(Availability.objects.filter(location="Removed room").exists())
        data = self.payload("CS362")
        data["ta1-0-DELETE"] = "on"
        self.assert_rejected(data)

    def test_missing_or_tampered_management_form_and_excess_ranges_do_not_save(self):
        for value in (None, "not-a-number", "51", "999999"):
            with self.subTest(value=value):
                data = self.payload()
                if value is None:
                    del data["instructor-TOTAL_FORMS"]
                else:
                    data["instructor-TOTAL_FORMS"] = value
                response = self.assert_rejected(data)
                self.assertTrue(response.context["sections"][0][2].non_form_errors())

    def test_add_range_without_javascript_keeps_data_and_does_not_save(self):
        data = self.payload()
        data["add_range"] = "ta1"
        response = self.assert_rejected(data)
        self.assertEqual(len(response.context["sections"][1][2].forms), 2)
        self.assertEqual(response.context["form"]["course_name"].value(), "Software Engineering")

    def test_cancel_creation_writes_nothing(self):
        data = self.payload()
        data["action"] = "cancel"
        before = self.record_snapshot()
        self.assertRedirects(self.client.post(self.create_url, data), self.list_url)
        self.assertEqual(self.record_snapshot(), before)
        self.assertContains(self.client.get(self.create_url), f'href="{self.list_url}">Cancel')

    def test_creation_database_failure_rolls_back_partial_writes_and_preserves_form(self):
        original_save = Availability.save
        calls = 0

        def fail_second_save(instance, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise DatabaseError("Simulated write failure")
            return original_save(instance, *args, **kwargs)

        with patch.object(Availability, "save", fail_second_save), self.assertLogs("OfficeHourSchedulingApp.views", level="ERROR"):
            response = self.assert_rejected(self.payload())
        self.assertEqual(calls, 2)
        self.assertContains(response, "could not be created")
        self.assertEqual(response.context["form"]["course_number"].value(), "CS361")
        self.assertEqual(response.context["sections"][0][2].forms[0]["date"].value(), "2026-11-23")

    def test_creation_integrity_failure_is_handled_without_partial_writes(self):
        with patch.object(Availability, "save", side_effect=IntegrityError("Simulated constraint failure")), self.assertLogs("OfficeHourSchedulingApp.views", level="ERROR"):
            self.assertContains(self.assert_rejected(self.payload()), "could not be created")

    def test_service_rechecks_staff_deleted_or_role_changed_after_validation(self):
        for change in ("role", "delete"):
            with self.subTest(change=change):
                user = get_user_model().objects.create_user(username=f"stale-{change}")
                user.groups.add(Group.objects.get(name="TA"))
                data = self.payload()
                data["ta2"] = str(user.pk)
                form = CourseForm(data)
                self.assertTrue(form.is_valid())
                stale_user = form.cleaned_data["ta2"]
                if change == "role":
                    user.groups.clear()
                else:
                    get_user_model().objects.filter(pk=user.pk).delete()
                ranges = [{"date": date(2026, 11, 23), "start_time": time(10), "end_time": time(11), "location": "EMS"}]
                with self.assertRaises(ValidationError):
                    services.create_course(course_number="CS361", course_name="Software", staff=[(self.instructor, "Instructor", ranges), (self.ta1, "TA", ranges), (stale_user, "TA", ranges)])
                self.assertFalse(Course.objects.exists())
                self.assertFalse(StaffAssignment.objects.exists())
                self.assertFalse(Availability.objects.exists())

    def test_delete_get_shows_confirmation_without_deleting(self):
        course = self.create()
        self.related_fixture(course)
        before = self.record_snapshot()
        response = self.client.get(reverse("courses:delete", args=[course.pk]))
        for text in ("CS361", "Software Engineering", "permanently deleted", "accounts will remain", 'name="confirm"'):
            self.assertContains(response, text)
        self.assertEqual(self.record_snapshot(), before)

    def test_post_without_explicit_confirmation_preserves_everything(self):
        course = self.create()
        self.related_fixture(course)
        before = self.record_snapshot()
        response = self.client.post(reverse("courses:delete", args=[course.pk]))
        self.assertContains(response, "Please confirm deletion")
        self.assertEqual(self.record_snapshot(), before)

    def test_delete_removes_dependencies_preserves_accounts_and_other_course_and_search(self):
        target = self.create()
        other = self.create("CS362")
        target_related = self.related_fixture(target)
        other_related = self.related_fixture(other)
        users_before = list(get_user_model().objects.order_by("pk").values())
        other_assignments = list(other.staff_assignments.values_list("pk", flat=True))
        other_availability = list(Availability.objects.filter(assignment__course=other).values_list("pk", flat=True))
        response = self.client.post(reverse("courses:delete", args=[target.pk]), {"confirm": "yes"}, follow=True)
        self.assertRedirects(response, self.list_url)
        self.assertContains(response, "was deleted successfully")
        self.assertFalse(Course.objects.filter(pk=target.pk).exists())
        self.assertFalse(StaffAssignment.objects.filter(course_id=target.pk).exists())
        self.assertFalse(Availability.objects.filter(assignment__course_id=target.pk).exists())
        for record in target_related:
            self.assertFalse(type(record).objects.filter(pk=record.pk).exists())
        for record in other_related:
            record.refresh_from_db()
        self.assertEqual(list(other.staff_assignments.values_list("pk", flat=True)), other_assignments)
        self.assertEqual(list(Availability.objects.filter(assignment__course=other).values_list("pk", flat=True)), other_availability)
        self.assertEqual(list(get_user_model().objects.order_by("pk").values()), users_before)
        self.assertContains(response, "CS362")
        self.assertNotContains(self.client.get(self.list_url, {"q": "CS361"}), "Software Engineering")

    def test_cancel_deletion_returns_to_course_with_all_records_intact(self):
        course = self.create()
        self.related_fixture(course)
        before = self.record_snapshot()
        url = reverse("courses:delete", args=[course.pk])
        response = self.client.post(url, {"action": "cancel", "confirm": "yes"})
        self.assertRedirects(response, reverse("courses:detail", args=[course.pk]))
        self.assertContains(self.client.get(url), f'href="{reverse("courses:detail", args=[course.pk])}">Cancel')
        self.assertEqual(self.record_snapshot(), before)

    def test_missing_course_on_get_and_post_redirects_with_message(self):
        other = self.create()
        self.related_fixture(other)
        missing = self.create("DELETED")
        missing_id = missing.pk
        services.delete_course(missing_id)
        before = self.record_snapshot()
        url = reverse("courses:delete", args=[missing_id])
        for method in (self.client.get, self.client.post):
            with self.subTest(method=method.__name__):
                response = method(url, {"confirm": "yes"}, follow=True)
                self.assertRedirects(response, self.list_url)
                self.assertContains(response, "course no longer exists")
                self.assertEqual(self.record_snapshot(), before)

    def test_delete_race_reports_missing_course(self):
        course = self.create()
        with patch.object(services, "delete_course", side_effect=Course.DoesNotExist):
            response = self.client.post(reverse("courses:delete", args=[course.pk]), {"confirm": "yes"}, follow=True)
        self.assertRedirects(response, self.list_url)
        self.assertContains(response, "course no longer exists")

    def test_delete_failure_after_cascade_rolls_back_and_allows_retry(self):
        course = self.create()
        self.related_fixture(course)
        self.related_fixture(self.create("CS362"))
        before = self.record_snapshot()

        def fail_after_delete(sender, instance, **kwargs):
            if instance.pk == course.pk:
                raise DatabaseError("Simulated failure after cascade")

        post_delete.connect(fail_after_delete, sender=Course, weak=False)
        try:
            with self.assertLogs("OfficeHourSchedulingApp.views", level="ERROR"):
                response = self.client.post(reverse("courses:delete", args=[course.pk]), {"confirm": "yes"})
        finally:
            post_delete.disconnect(fail_after_delete, sender=Course)
        self.assertContains(response, "could not be deleted")
        self.assertEqual(self.record_snapshot(), before)
        retry = self.client.post(reverse("courses:delete", args=[course.pk]), {"confirm": "yes"})
        self.assertRedirects(retry, self.list_url)

    def test_anonymous_get_and_post_redirect_to_login_without_changes(self):
        course = self.create()
        self.related_fixture(course)
        self.client.logout()
        before = self.record_snapshot()
        for url in (self.create_url, self.list_url, reverse("courses:detail", args=[course.pk]), reverse("courses:delete", args=[course.pk])):
            for method in (self.client.get, self.client.post):
                with self.subTest(url=url, method=method.__name__):
                    data = {} if method.__name__ == "get" else self.payload() | {"confirm": "yes"}
                    self.assertRedirects(method(url, data), f"{reverse('login')}?next={url}")
        self.assertEqual(self.record_snapshot(), before)

    def test_non_admin_roles_and_staff_flag_alone_cannot_get_or_post(self):
        course = self.create()
        self.related_fixture(course)
        plain_staff = get_user_model().objects.create_user(username="plain-staff", is_staff=True)
        for user in (self.instructor, self.ta1, self.student, plain_staff):
            self.client.force_login(user)
            before = self.record_snapshot()
            for url in (self.create_url, self.list_url, reverse("courses:detail", args=[course.pk]), reverse("courses:delete", args=[course.pk])):
                for method in (self.client.get, self.client.post):
                    with self.subTest(user=user.username, url=url, method=method.__name__):
                        self.assertEqual(method(url, self.payload() | {"confirm": "yes"}).status_code, 403)
            self.assertEqual(self.record_snapshot(), before)

    def test_active_administrator_group_can_create_and_delete_without_superuser_flag(self):
        admin = get_user_model().objects.create_user(username="group-admin")
        admin.groups.add(Group.objects.get(name="Administrator"))
        self.client.force_login(admin)
        course = self.create()
        self.assertRedirects(self.client.post(reverse("courses:delete", args=[course.pk]), {"confirm": "yes"}), self.list_url)

    def test_csrf_required_for_create_and_delete(self):
        course = self.create()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        before = self.record_snapshot()
        self.assertEqual(csrf_client.post(self.create_url, self.payload("CS362")).status_code, 403)
        self.assertEqual(csrf_client.post(reverse("courses:delete", args=[course.pk]), {"confirm": "yes"}).status_code, 403)
        self.assertEqual(self.record_snapshot(), before)

    def test_search_matches_number_or_name_and_clears(self):
        self.create()
        Course.objects.create(course_number="MATH101", course_name="Calculus")
        for query in ("CS361", "Software"):
            response = self.client.get(self.list_url, {"q": query})
            self.assertContains(response, "Software Engineering")
            self.assertNotContains(response, "Calculus")
        self.assertContains(self.client.get(self.list_url), "Calculus")

    def test_unsupported_delete_methods_cannot_mutate(self):
        course = self.create()
        before = self.record_snapshot()
        self.assertEqual(self.client.delete(reverse("courses:delete", args=[course.pk])).status_code, 405)
        self.assertEqual(self.record_snapshot(), before)
