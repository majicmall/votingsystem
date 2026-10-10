from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from ballot.models import Category, Nominee, NominationLedger, Vote, SelfNominationCheckIn


SOURCE_SLUG = "hottest-influencer"
TARGET_SLUG = "atls-hottest-influencer"


class Command(BaseCommand):
    help = "Safely consolidate the duplicate Influencer award category."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the consolidation; default is read-only dry run.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]

        with transaction.atomic():
            try:
                source = Category.objects.select_for_update().get(slug=SOURCE_SLUG)
                target = Category.objects.select_for_update().get(slug=TARGET_SLUG)
            except Category.DoesNotExist as exc:
                raise CommandError(f"Required category missing: {exc}")

            if source.slug != "hottest-influencer":
                raise CommandError("Source category identity mismatch.")
            if target.slug != "atls-hottest-influencer":
                raise CommandError("Target category identity mismatch.")

            source_nominees = list(
                Nominee.objects.select_for_update()
                .filter(category=source)
                .order_by("pk")
            )
            target_nominees = list(
                Nominee.objects.filter(category=target)
            )

            if Vote.objects.filter(category__in=[source, target]).exists():
                raise CommandError("Votes exist. Manual review required.")

            moves = []
            duplicates = []

            for nominee in source_nominees:
                matches = [
                    candidate
                    for candidate in target_nominees
                    if candidate.campaign_id == nominee.campaign_id
                    and (
                        Nominee.normalize_identity_name(candidate.name)
                        == Nominee.normalize_identity_name(nominee.name)
                        or (
                            nominee.contact_email
                            and candidate.contact_email
                            and Nominee.normalize_identity_email(nominee.contact_email)
                            == Nominee.normalize_identity_email(candidate.contact_email)
                        )
                        or (
                            nominee.social_link
                            and candidate.social_link
                            and Nominee.normalize_identity_url(nominee.social_link)
                            == Nominee.normalize_identity_url(candidate.social_link)
                        )
                        or (
                            nominee.website
                            and candidate.website
                            and Nominee.normalize_identity_url(nominee.website)
                            == Nominee.normalize_identity_url(candidate.website)
                        )
                    )
                ]

                if len(matches) > 1:
                    raise CommandError(
                        f"Ambiguous identity match for {nominee.pk}."
                    )

                if matches:
                    duplicates.append((nominee, matches[0]))
                else:
                    moves.append(nominee)

            if len(duplicates) > 1:
                raise CommandError(
                    f"Multiple identity duplicates found: {len(duplicates)}. "
                    "Manual review required."
                )

            if duplicates:
                duplicate_source, duplicate_target = duplicates[0]

                if (
                    Nominee.normalize_identity_name(duplicate_source.name)
                    != "demarcus jackson"
                    or duplicate_target.approval_status != Nominee.APPROVAL_APPROVED
                ):
                    raise CommandError(
                        "Unexpected duplicate identity. Manual review required."
                    )

            self.stdout.write(
                f"{'APPLY' if apply else 'DRY RUN'}: "
                f"{len(moves)} nominees to move; "
                f"{len(duplicates)} historical duplicate to retain."
            )

            ledger_count = NominationLedger.objects.filter(
                category=source
            ).count()

            self.stdout.write(
                f"Source ledger records: {ledger_count}"
            )

            checkins = list(
                SelfNominationCheckIn.objects.filter(categories=source)
                .distinct()
            )

            self.stdout.write(
                f"Check-Ins requiring category consolidation: {len(checkins)}"
            )

            if not apply:
                self.stdout.write(
                    self.style.SUCCESS("DRY RUN COMPLETE — no changes made.")
                )
                return

            for nominee in moves:
                nominee.category = target
                nominee.save(update_fields=["category", "updated_at"])

                NominationLedger.objects.filter(
                    nominee=nominee,
                    category=source,
                ).update(category=target)

            for checkin in checkins:
                checkin.categories.add(target)
                checkin.categories.remove(source)

            for duplicate_source, duplicate_target in duplicates:
                duplicate_source.is_active = False
                duplicate_source.save(update_fields=["is_active", "updated_at"])

            source.is_active = False
            source.save(update_fields=["is_active"])

            if NominationLedger.objects.filter(
                nominee__category=source
            ).exclude(category=source).exists():
                raise CommandError("Historical ledger consistency failure.")

            if NominationLedger.objects.filter(
                nominee__category=target,
                category=source,
            ).exists():
                raise CommandError("Moved nominee has an unmoved ledger record.")

            if Nominee.objects.filter(
                category=source,
                is_active=True,
            ).exists():
                raise CommandError("Active nominees remain in duplicate category.")

            if SelfNominationCheckIn.objects.filter(
                categories=source
            ).exists():
                raise CommandError("Check-Ins still reference duplicate category.")

            self.stdout.write(
                self.style.SUCCESS(
                    "Influencer category consolidation applied."
                )
            )
