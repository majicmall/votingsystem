import uuid

from django.db import migrations


def backfill_advertiser_report_tokens(apps, schema_editor):
    AdvertisingCampaign = apps.get_model(
        "ballot",
        "AdvertisingCampaign",
    )

    campaigns = AdvertisingCampaign.objects.filter(
        advertiser_report_token__isnull=True
    ).only(
        "pk",
        "advertiser_report_token",
    )

    for campaign in campaigns.iterator():
        campaign.advertiser_report_token = uuid.uuid4()
        campaign.save(
            update_fields=["advertiser_report_token"]
        )


def reverse_backfill(apps, schema_editor):
    AdvertisingCampaign = apps.get_model(
        "ballot",
        "AdvertisingCampaign",
    )

    AdvertisingCampaign.objects.update(
        advertiser_report_token=None
    )


class Migration(migrations.Migration):

    dependencies = [
        (
            "ballot",
            "0049_advertisingcampaign_advertiser_report_token",
        ),
    ]

    operations = [
        migrations.RunPython(
            backfill_advertiser_report_tokens,
            reverse_backfill,
        ),
    ]
