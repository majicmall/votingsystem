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
            "photo": source.photo,
            "website": source.website,
            "social_link": source.social_link,
            "contact_email": source.contact_email,
            "is_active": True,
        },
    )

    updates = []
    if nominee.category_id != target_category.pk:
        nominee.category = target_category
        updates.append("category")
    if not nominee.is_active:
        nominee.is_active = True
        updates.append("is_active")

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
