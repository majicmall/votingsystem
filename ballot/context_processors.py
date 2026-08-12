def voting_campaign_status(request):
    try:
        from .models import VotingCampaign

        campaign = (
            VotingCampaign.objects
            .filter(is_active_campaign=True)
            .order_by("-created_at")
            .first()
        )

        if campaign:
            return {
                "active_campaign": campaign,
                "voting_open": campaign.is_voting_open,
            }
    except Exception:
        pass

    return {
        "active_campaign": None,
        "voting_open": True,
    }
