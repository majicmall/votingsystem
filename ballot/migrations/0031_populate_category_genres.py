from django.db import migrations


FASHION_BEAUTY_CATEGORIES = [
    "Hottest Accessories Designer",
    "Hottest Fashion Designer",
    "Fashion Stylist",
    "Hottest Hairstylist",
    "Hottest Female Model",
    "Hottest Male Model",
    "Hottest Mature Model",
    "Hottest Full Figured Model",
    "Hottest Make Up Artist",
]


def populate_category_genres(apps, schema_editor):
    Category = apps.get_model("ballot", "Category")

    # Move the existing Fashion categories into Fashion & Beauty.
    Category.objects.filter(
        name__in=FASHION_BEAUTY_CATEGORIES
    ).update(group="Fashion & Beauty")

    # Preserve the existing Hottest Event record and anything attached to it.
    Category.objects.filter(
        name="Hottest Event"
    ).update(
        name="Hottest Event Series",
        slug="hottest-event-series",
        group="Events",
    )

    # Add the new Venues category if it does not already exist.
    open_mic, created = Category.objects.get_or_create(
        name="Hottest Open Mic/Jam Session",
        defaults={
            "slug": "hottest-open-mic-jam-session",
            "group": "Venues",
            "sort_order": 56,
            "is_active": True,
        },
    )

    if not created:
        open_mic.group = "Venues"
        open_mic.is_active = True

        if not open_mic.slug:
            open_mic.slug = "hottest-open-mic-jam-session"

        open_mic.save(
            update_fields=[
                "group",
                "is_active",
                "slug",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("ballot", "0030_alter_category_group"),
    ]

    operations = [
        migrations.RunPython(
            populate_category_genres,
            migrations.RunPython.noop,
        ),
    ]
