# ballot/services.py
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import AssociationMembership, NominationCategoryRequest, Nominee


def clone_nominee_into_category(source, target_category):
    if source.category_id == target_category.pk:
        if not source.is_active:
            source.is_active = True
            source.save(update_fields=["is_active", "updated_at"])
        return source

    base = source.id or str(source.pk)
    suffix = f"-{target_category.slug}"
    max_len = 64
    new_id = base if len(base + suffix) <= max_len else base[: max_len - len(suffix)]
    new_id = f"{new_id}{suffix}"

    nominee, _created = Nominee.objects.get_or_create(
        id=new_id,
        defaults={
            "name": source.name,
            "category": target_category,
            "campaign": source.campaign,
            "photo": source.photo,
            "website": source.website,
            "social_link": source.social_link,
            "contact_email": source.contact_email,
            "is_active": True,
        },
    )

    # Campaign safety:
    # - New clones inherit source.campaign through defaults above.
    # - Legacy existing clones with no campaign inherit the source campaign.
    # - Existing clones already assigned to another campaign fail closed.
    if nominee.campaign_id is None and source.campaign_id is not None:
        nominee.campaign = source.campaign
    elif nominee.campaign_id != source.campaign_id:
        raise ValueError(
            "Cannot reuse nominee clone across awards campaigns."
        )

    updates = []

    if nominee.campaign_id != source.campaign_id:
        # This branch is intentionally unreachable after the guard above,
        # but keeps campaign mismatch handling explicit.
        raise ValueError(
            "Cannot reuse nominee clone across awards campaigns."
        )

    if nominee.category_id != target_category.pk:
        nominee.category = target_category
        updates.append("category")

    if not nominee.is_active:
        nominee.is_active = True
        updates.append("is_active")

    if nominee.campaign_id == source.campaign_id and nominee.campaign_id is not None:
        if not _created and "campaign" not in updates:
            # Persist only when this was a legacy NULL-campaign clone that
            # inherited the source campaign above.
            current_campaign_id = (
                Nominee.objects
                .filter(pk=nominee.pk)
                .values_list("campaign_id", flat=True)
                .first()
            )
            if current_campaign_id is None:
                updates.append("campaign")

    if updates:
        nominee.save(update_fields=updates)

    return nominee


@transaction.atomic
def approve_category_request(req):
    if req.status != NominationCategoryRequest.STATUS_PENDING:
        return req.source_nominee

    approved_nominee = clone_nominee_into_category(req.source_nominee, req.target_category)

    AssociationMembership.objects.update_or_create(
        user=req.requester,
        nominee=req.source_nominee,
        defaults={"is_active": True},
    )
    AssociationMembership.objects.update_or_create(
        user=req.requester,
        nominee=approved_nominee,
        defaults={"is_active": True},
    )

    req.status = NominationCategoryRequest.STATUS_APPROVED
    req.decided_at = timezone.now()
    req.save(update_fields=["status", "decided_at"])

    return approved_nominee


@transaction.atomic
def deny_category_request(req):
    if req.status != NominationCategoryRequest.STATUS_PENDING:
        return

    req.status = NominationCategoryRequest.STATUS_DENIED
    req.decided_at = timezone.now()
    req.save(update_fields=["status", "decided_at"])
