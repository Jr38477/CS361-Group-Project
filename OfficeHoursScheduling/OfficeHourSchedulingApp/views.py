import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from . import services
from .forms import AvailabilityFormSet, CourseForm
from .models import Course, StaffAssignment
from .roles import is_administrator

logger = logging.getLogger(__name__)
POSITIONS = (("instructor", "Instructor", StaffAssignment.Role.INSTRUCTOR), ("ta1", "TA 1", StaffAssignment.Role.TA), ("ta2", "TA 2", StaffAssignment.Role.TA))


class AdministratorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return is_administrator(self.request.user)


class CourseListView(AdministratorRequiredMixin, View):
    def get(self, request):
        query = request.GET.get("q", "").strip()
        courses = Course.objects.all()
        if query:
            courses = courses.filter(Q(course_number__icontains=query) | Q(course_name__icontains=query))
        return render(request, "courses/list.html", {"courses": courses, "query": query})


class CourseDetailView(AdministratorRequiredMixin, View):
    def get(self, request, pk):
        course = get_object_or_404(Course.objects.prefetch_related("staff_assignments__user", "staff_assignments__availability"), pk=pk)
        return render(request, "courses/detail.html", {"course": course})


class CourseCreateView(AdministratorRequiredMixin, View):
    def get(self, request):
        return self.render_form(request)

    def render_form(self, request, form=None, sections=None):
        if form is None:
            form = CourseForm()
        if sections is None:
            sections = [(key, label, AvailabilityFormSet(prefix=key, error_messages={"too_few_forms": f"Provide at least one available time range for {label}."})) for key, label, _ in POSITIONS]
        return render(request, "courses/create.html", {"form": form, "sections": sections})

    def post(self, request):
        if request.POST.get("action") == "cancel":
            return redirect("courses:list")
        data = request.POST.copy()
        add_range = data.get("add_range")
        if add_range in {position[0] for position in POSITIONS}:
            try:
                count = int(data.get(f"{add_range}-TOTAL_FORMS", 0))
            except (ValueError, TypeError):
                count = 0
            data[f"{add_range}-TOTAL_FORMS"] = str(min(max(count, 0) + 1, 50))
        form = CourseForm(data)
        sections = [(key, label, AvailabilityFormSet(data, prefix=key, error_messages={"too_few_forms": f"Provide at least one available time range for {label}."})) for key, label, _ in POSITIONS]
        if add_range:
            return self.render_form(request, form, sections)
        valid = form.is_valid()
        for _, _, formset in sections:
            valid = formset.is_valid() and valid
        if valid:
            staff = []
            for (key, _, role), (_, _, formset) in zip(POSITIONS, sections):
                ranges = [{field: row.cleaned_data[field] for field in ("location", "date", "start_time", "end_time")} for row in formset if row.cleaned_data and not row.cleaned_data.get("DELETE")]
                staff.append((form.cleaned_data[key], role, ranges))
            try:
                course = services.create_course(course_number=form.cleaned_data["course_number"], course_name=form.cleaned_data["course_name"], staff=staff)
            except ValidationError as error:
                form.add_error(None, " ".join(error.messages))
            except IntegrityError:
                if Course.objects.filter(course_number=form.cleaned_data["course_number"]).exists():
                    form.add_error("course_number", "A course with this course number already exists.")
                else:
                    logger.exception("Course creation failed")
                    form.add_error(None, "The course could not be created. Please try again.")
            except DatabaseError:
                logger.exception("Course creation failed")
                form.add_error(None, "The course could not be created. Please try again.")
            else:
                messages.success(request, f"Course {course.course_number} was created successfully.")
                return redirect("courses:detail", pk=course.pk)
        return self.render_form(request, form, sections)


class CourseDeleteView(AdministratorRequiredMixin, View):
    def missing_course(self, request):
        messages.error(request, "The course no longer exists.")
        return redirect("courses:list")

    def get(self, request, pk):
        course = Course.objects.filter(pk=pk).first()
        if course is None:
            return self.missing_course(request)
        return render(request, "courses/delete.html", {"course": course})

    def post(self, request, pk):
        course = Course.objects.filter(pk=pk).first()
        if course is None:
            return self.missing_course(request)
        if request.POST.get("action") == "cancel":
            return redirect("courses:detail", pk=pk)
        if request.POST.get("confirm") != "yes":
            return render(request, "courses/delete.html", {"course": course, "error": "Please confirm deletion before continuing."})
        try:
            services.delete_course(pk)
        except Course.DoesNotExist:
            return self.missing_course(request)
        except DatabaseError:
            logger.exception("Course deletion failed")
            return render(request, "courses/delete.html", {"course": course, "error": "The course could not be deleted. Please try again."})
        messages.success(request, f"Course {course.course_number} was deleted successfully.")
        return redirect("courses:list")
from django.shortcuts import render

# Create your views here.
