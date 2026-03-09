from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Seed the accounts_user table with an initial user."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default="mohan",
            help="Username for the seeded user (default: mohan)",
        )
        parser.add_argument(
            "--password",
            default="password123",
            help="Password for the seeded user (default: password123)",
        )
        parser.add_argument(
            "--email",
            default="",
            help="Email for the seeded user (default: empty)",
        )
        parser.add_argument(
            "--role",
            default="viewer",
            help="Role for the seeded user (default: viewer)",
        )
        parser.add_argument(
            "--superuser",
            action="store_true",
            help="Create the user as a superuser/staff.",
        )

    def handle(self, *args, **options):
        User = get_user_model()

        username = options["username"]
        password = options["password"]
        email = options["email"]
        role = options["role"]
        make_superuser = options["superuser"]

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "role": role,
                "is_active": True,
                "is_staff": make_superuser,
                "is_superuser": make_superuser,
            },
        )

        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created user '{username}' with role '{role}' "
                    f"({'superuser' if make_superuser else 'regular user'})."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"User '{username}' already exists; updating password/role/flags."
                )
            )
            user.email = email or user.email
            user.role = role or user.role
            if password:
                user.set_password(password)
            if make_superuser:
                user.is_staff = True
                user.is_superuser = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Updated user '{username}'"))

