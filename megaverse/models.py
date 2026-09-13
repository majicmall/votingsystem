import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class MegaverseConnection(models.Model):
    """
    Connects an ATL's Hottest account to its identity in the
    broader MajicMall Megaverse without duplicating either system's data.

    This is an integration reference — not a copy of the Megaverse user,
    merchant, storefront, order, product, or delivery records.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="megaverse_connection",
    )

    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    megaverse_user_ref = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text="Stable external identifier for this user in MajicMall Megaverse.",
    )

    is_linked = models.BooleanField(default=False)

    linked_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Megaverse Connection"
        verbose_name_plural = "Megaverse Connections"
        constraints = [
            models.UniqueConstraint(
                fields=["megaverse_user_ref"],
                condition=~Q(megaverse_user_ref=""),
                name="uniq_nonblank_megaverse_user_ref",
            ),
        ]

    def __str__(self):
        return f"{self.user} — MajicMall Megaverse"


class MegaverseCommerceReference(models.Model):
    """
    References commerce objects owned by MajicMall Megaverse.

    ATL's Hottest can connect to shared storefronts, products, orders,
    and other commerce resources without creating duplicate commerce
    records in the ATL's Hottest database.
    """

    RESOURCE_STOREFRONT = "storefront"
    RESOURCE_PRODUCT = "product"
    RESOURCE_ORDER = "order"

    RESOURCE_CHOICES = [
        (RESOURCE_STOREFRONT, "Storefront"),
        (RESOURCE_PRODUCT, "Product"),
        (RESOURCE_ORDER, "Order"),
    ]

    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    resource_type = models.CharField(
        max_length=30,
        choices=RESOURCE_CHOICES,
        db_index=True,
    )

    external_ref = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Stable identifier of the resource in MajicMall Megaverse.",
    )

    atl_slug = models.SlugField(
        max_length=255,
        blank=True,
        help_text="Optional ATL's Hottest-facing destination slug.",
    )

    is_active = models.BooleanField(default=True)

    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Non-authoritative presentation/integration metadata only.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Megaverse Commerce Reference"
        verbose_name_plural = "Megaverse Commerce References"
        constraints = [
            models.UniqueConstraint(
                fields=["resource_type", "external_ref"],
                name="unique_megaverse_commerce_reference",
            ),
        ]

    def __str__(self):
        return f"{self.get_resource_type_display()} — {self.external_ref}"
