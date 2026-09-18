from django.core.management.base import BaseCommand

from ballot.data_retention import (
    POLICY_VERSION,
    get_field_retention_rules,
    get_retention_rules,
)


class Command(BaseCommand):
    help = (
        "Display the locked ATL's Hottest retention schedule. "
        "READ-ONLY: no records or files are modified."
    )

    def handle(self, *args, **options):
        self.stdout.write("")
        self.stdout.write("=" * 78)
        self.stdout.write(" ATL'S HOTTEST — LOCKED RETENTION SCHEDULE")
        self.stdout.write("=" * 78)
        self.stdout.write(f" POLICY VERSION: {POLICY_VERSION}")
        self.stdout.write(" MODE: READ-ONLY")
        self.stdout.write("")

        for rule in get_retention_rules():
            period = (
                f"{rule.automatic_days} days"
                if rule.automatic_days is not None
                else "NO AUTOMATIC PERIOD"
            )

            self.stdout.write(f"MODEL:      {rule.model}")
            self.stdout.write(f"TREATMENT:  {rule.treatment}")
            self.stdout.write(f"PERIOD:     {period}")
            self.stdout.write(f"ANCHOR:     {rule.anchor}")
            self.stdout.write(f"PURPOSE:    {rule.purpose}")
            self.stdout.write(f"NOTES:      {rule.notes}")
            self.stdout.write("")

        self.stdout.write("-" * 78)
        self.stdout.write(" FIELD-SPECIFIC RETENTION RULES")
        self.stdout.write("-" * 78)

        for field_name, rule in get_field_retention_rules().items():
            self.stdout.write(f"FIELD:      {field_name}")
            self.stdout.write(f"ACTION:     {rule['action']}")
            self.stdout.write(f"PERIOD:     {rule['days']} days")
            self.stdout.write(f"ANCHOR:     {rule['anchor']}")
            self.stdout.write("")

        self.stdout.write("=" * 78)
        self.stdout.write(
            self.style.SUCCESS(
                " RETENTION SCHEDULE LOADED — NO DATA WAS MODIFIED"
            )
        )
        self.stdout.write("=" * 78)
