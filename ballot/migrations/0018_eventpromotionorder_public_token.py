import uuid

from django.db import migrations, models


def populate_public_tokens(apps, schema_editor):
    EventPromotionOrder = apps.get_model("ballot", "EventPromotionOrder")

    for order in EventPromotionOrder.objects.filter(public_token__isnull=True):
        order.public_token = uuid.uuid4()
        order.save(update_fields=["public_token"])


class Migration(migrations.Migration):

    dependencies = [
        ("ballot", "0017_eventpromotionorder_paid_at_and_more"),
    ]

    operations = [
        # Stage 1: Add the field without uniqueness so existing rows
        # can be migrated safely.
        migrations.AddField(
            model_name="eventpromotionorder",
            name="public_token",
            field=models.UUIDField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),

        # Stage 2: Give every existing order its own UUID.
        migrations.RunPython(
            populate_public_tokens,
            migrations.RunPython.noop,
        ),

        # Stage 3: Enforce the final production definition.
        migrations.AlterField(
            model_name="eventpromotionorder",
            name="public_token",
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
            ),
        ),
    ]
