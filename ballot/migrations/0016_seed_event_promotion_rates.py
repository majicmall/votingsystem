from decimal import Decimal

from django.db import migrations


def seed_event_promotion_rates(apps, schema_editor):
    EventPromotionRate = apps.get_model("ballot", "EventPromotionRate")

    rates = [
        {
            "package": "24_hours",
            "amount": Decimal("25.00"),
            "is_active": True,
            "display_order": 10,
        },
        {
            "package": "3_days",
            "amount": Decimal("60.00"),
            "is_active": True,
            "display_order": 20,
        },
        {
            "package": "7_days",
            "amount": Decimal("120.00"),
            "is_active": True,
            "display_order": 30,
        },
        {
            "package": "custom",
            "amount": Decimal("0.00"),
            "is_active": True,
            "display_order": 40,
        },
    ]

    for rate in rates:
        EventPromotionRate.objects.update_or_create(
            package=rate["package"],
            defaults={
                "amount": rate["amount"],
                "is_active": rate["is_active"],
                "display_order": rate["display_order"],
            },
        )


def reverse_seed_event_promotion_rates(apps, schema_editor):
    # Intentionally leave rates in place on reverse migrations.
    # This avoids deleting administrator-edited pricing data.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("ballot", "0015_eventpromotionrate_and_more"),
    ]

    operations = [
        migrations.RunPython(
            seed_event_promotion_rates,
            reverse_seed_event_promotion_rates,
        ),
    ]
