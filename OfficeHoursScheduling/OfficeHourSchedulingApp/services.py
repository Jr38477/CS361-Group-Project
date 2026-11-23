from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Availability, Course, StaffAssignment


@transaction.atomic
def create_course(*, course_number, course_name, staff):
    """Persist the complete course or roll back every related write.

    staff contains (user, role, availability dictionaries) for three positions.
    Recheck current accounts/roles inside the transaction, after form validation.
    """
    roles = [role for _, role, _ in staff]
    if roles.count(StaffAssignment.Role.INSTRUCTOR) != 1 or roles.count(StaffAssignment.Role.TA) != 2 or len(staff) != 3:
        raise ValidationError("Exactly one instructor and two TAs are required.")
    ids = [user.pk for user, _, _ in staff]
    if len(set(ids)) != 3:
        raise ValidationError("All three staff assignments must be different people.")
    current_users = {
        user.pk: user for user in get_user_model().objects.select_for_update().filter(pk__in=ids, is_active=True)
    }
    course = Course(course_number=course_number, course_name=course_name)
    course.full_clean()
    course.save()
    for user, role, ranges in staff:
        current = current_users.get(user.pk)
        if current is None or not current.groups.filter(name=role).exists():
            raise ValidationError(f"The selected {role} account is no longer available. Correct the staff selection.")
        if not ranges:
            raise ValidationError(f"Provide at least one available time range for {current}.")
        assignment = StaffAssignment(course=course, user=current, role=role)
        assignment.full_clean()
        assignment.save()
        for values in ranges:
            availability = Availability(assignment=assignment, **values)
            availability.full_clean()
            availability.save()
    return course


@transaction.atomic
def delete_course(course_id):
    """Cascade only from the selected course, preserving all user accounts."""
    course = Course.objects.select_for_update().get(pk=course_id)
    course.delete()
