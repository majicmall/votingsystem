from django.apps import apps
from django.core.management.base import BaseCommand

from ballot.retention_anonymization import get_anonymization_blueprints


class Command(BaseCommand):
    help = (
        "Display ATL's Hottest field-level anonymization blueprint. "
        "READ-ONLY: no records or files are modified."
    )

    def handle(self, *args, **options):
        self.stdout.write("")
        self.stdout.write("=" * 76)
        self.stdout.write(" ATL'S HOTTEST — ANONYMIZATION BLUEPRINT")
        self.stdout.write("=" * 76)

        errors = []

        for blueprint in get_anonymization_blueprints():
            app_label, model_name = blueprint.model.split(".", 1)

            try:
                model = apps.get_model(app_label, model_name)
            except LookupError:
                errors.append(f"{blueprint.model}: MODEL NOT FOUND")
                continue

            actual_fields = {
                field.name
                for field in model._meta.get_fields()
            }

            self.stdout.write("")
            self.stdout.write(f"MODEL:   {blueprint.model}")
            self.stdout.write(f"RECORDS: {model.objects.count()}")

            for rule in blueprint.fields:
                exists = rule.field in actual_fields
                status = "OK" if exists else "FIELD NOT FOUND"

                self.stdout.write(
                    f"  [{status}] {rule.field}"
                    f" -> {rule.action}"
                )
                self.stdout.write(
                    f"       {rule.reason}"
                )

                if not exists:
                    errors.append(
                        f"{blueprint.model}.{rule.field}: FIELD NOT FOUND"
                    )

            if blueprint.notes:
                self.stdout.write(f"  NOTES: {blueprint.notes}")

        self.stdout.write("")
        self.stdout.write("=" * 76)

        if errors:
            self.stdout.write(
                self.style.ERROR(
                    " BLUEPRINT VALIDATION FAILED"
                )
            )

            for error in errors:
                self.stdout.write(
                    self.style.ERROR(f" - {error}")
                )

            raise SystemExit(1)

        self.stdout.write(
            self.style.SUCCESS(
                " BLUEPRINT VALIDATED — NO DATA WAS MODIFIED"
            )
        )
        self.stdout.write("=" * 76)
