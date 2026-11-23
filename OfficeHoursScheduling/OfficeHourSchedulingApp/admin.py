from django.contrib import admin

# Courses are managed through the validated course workflow. Registering a plain
# ModelAdmin would allow bypassing its required staff/availability validation.
from .models import Availability, Enrollment, OfficeHour, Reservation, StaffAssignment

admin.site.register([Availability, Enrollment, OfficeHour, Reservation, StaffAssignment])
# Register your models here.
