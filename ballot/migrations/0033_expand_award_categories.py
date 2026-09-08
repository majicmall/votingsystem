from django.db import migrations


NEW_CATEGORIES = [
    # Icons / Legends / VIPs
    {
        "name": "ATL’s Hottest Icon",
        "slug": "atls-hottest-icon",
        "group": "Icons / Legends / VIPs",
        "sort_order": 57,
    },
    {
        "name": "Hottest Living Legend",
        "slug": "hottest-living-legend",
        "group": "Icons / Legends / VIPs",
        "sort_order": 58,
    },
    {
        "name": "Hottest Trailblazer",
        "slug": "hottest-trailblazer",
        "group": "Icons / Legends / VIPs",
        "sort_order": 59,
    },
    {
        "name": "ATL’s Hottest Of The Year",
        "slug": "atls-hottest-of-the-year",
        "group": "Icons / Legends / VIPs",
        "sort_order": 60,
    },
    {
        "name": "Hottest Homegrown Awards",
        "slug": "hottest-homegrown-awards",
        "group": "Icons / Legends / VIPs",
        "sort_order": 61,
    },

    # Events
    {
        "name": "Hottest House Music Event",
        "slug": "hottest-house-music-event",
        "group": "Events",
        "sort_order": 64,
    },
    {
        "name": "Hottest Fashion Show",
        "slug": "hottest-fashion-show",
        "group": "Events",
        "sort_order": 65,
    },
    {
        "name": "Hottest Social Event",
        "slug": "hottest-social-event",
        "group": "Events",
        "sort_order": 66,
    },

    # Personalities
    {
        "name": "ATL’s Hottest Influencer",
        "slug": "atls-hottest-influencer",
        "group": "Personalities",
        "sort_order": 62,
    },

    # Community
    {
        "name": "Hottest Non Profit Organization",
        "slug": "hottest-non-profit-organization",
        "group": "Community",
        "sort_order": 63,
    },
]


def add_categories(apps, schema_editor):
    Category = apps.get_model("ballot", "Category")

    for item in NEW_CATEGORIES:
        category = Category.objects.filter(name=item["name"]).first()

        if category:
            category.group = item["group"]
            category.sort_order = item["sort_order"]
            category.is_active = True

            if not category.slug:
                category.slug = item["slug"]

            category.save()
        else:
            Category.objects.create(
                name=item["name"],
                slug=item["slug"],
                group=item["group"],
                sort_order=item["sort_order"],
                is_active=True,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("ballot", "0032_alter_category_group"),
    ]

    operations = [
        migrations.RunPython(
            add_categories,
            migrations.RunPython.noop,
        ),
    ]
