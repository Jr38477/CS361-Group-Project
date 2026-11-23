ADMINISTRATOR = "Administrator"
INSTRUCTOR = "Instructor"
TA = "TA"


def is_administrator(user):
    return user.is_authenticated and user.is_active and (
        user.is_superuser or user.groups.filter(name=ADMINISTRATOR).exists()
    )
