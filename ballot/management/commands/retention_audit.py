from django.apps import apps
from django.core.management.base import BaseCommand

from ballot.data_retention import get_retention_rules


class Command(BaseCommand):
    help = (
        "Display ATL's Hottest data-retention policy and current record "
        "counts. This command is READ-ONLY."
    )

    def handle(self, *args, **options):
        self.stdout.write("")
        self.stdout.write("=" * 72)
        self.stdout.write(" ATL'S HOTTEST — DATA RETENTION POLICY AUDIT")
        self.stdout.write("=" * 72)

        for rule in get_retention_rules():
            app_label, model_name = rule.model.split(".", 1)

            try:
                model = apps.get_model(app_label, model_name)
                count = model.objects.count()
            except LookupError:
                count = "MODEL NOT FOUND"

            automatic = (
                f"{rule.automatic_days} days"
                if rule.automatic_days is not None
                else "NOT ENABLED"
            )

            self.stdout.write("")
            self.stdout.write(f"MODEL:      {rule.model}")
            self.stdout.write(f"TREATMENT:  {rule.treatment}")
            self.stdout.write(f"RECORDS:    {count}")
            self.stdout.write(f"AUTOMATIC:  {automatic}")
            self.stdout.write(f"PURPOSE:    {rule.purpose}")
            self.stdout.write(f"NOTES:      {rule.notes}")

        self.stdout.write("")
        self.stdout.write("=" * 72)
        self.stdout.write(" READ-ONLY AUDIT COMPLETE — NO DATA WAS MODIFIED")
        self.stdout.write("=" * 72)
