from django.urls import path

from .views import CourseCreateView, CourseDeleteView, CourseDetailView, CourseListView, create_staff_account

app_name = "courses"
urlpatterns = [
    path("", CourseListView.as_view(), name="list"),
    path("create/", CourseCreateView.as_view(), name="create"),
    path("staff/create/", create_staff_account, name="create_staff_account"),
    path("<int:pk>/", CourseDetailView.as_view(), name="detail"),
    path("<int:pk>/delete/", CourseDeleteView.as_view(), name="delete"),
]
urlpatterns = [
    path("staff/create/", views.create_staff_account, name="create_staff_account"),
]
