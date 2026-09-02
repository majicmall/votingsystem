from django.shortcuts import render


class VotingCampaignGateMiddleware:
    """
    Allows visitors to browse the ballot/nominees while voting is closed.
    Blocks only vote-casting actions until the active campaign opens voting.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""

        # Visitors may browse /ballot/ and /ballot/category/<slug>/.
        # These paths/actions should be blocked when voting is closed.
        blocked_vote_paths = (
            "/ballot/select/",
            "/ballot/review/",
            "/ballot/submit-final/",
            "/submit-votes/",
        )

        nominee_vote_action = path.startswith("/nominee/") and path.endswith("/vote/")

        should_block_vote_action = (
            any(path.startswith(prefix) for prefix in blocked_vote_paths)
            or nominee_vote_action
        )

        if should_block_vote_action:
            try:
                from .models import VotingCampaign

                campaign = (
                    VotingCampaign.objects
                    .filter(is_active_campaign=True)
                    .order_by("-created_at")
                    .first()
                )

                # If a campaign exists, campaign controls take over.
                # If no campaign exists, legacy voting behavior stays open.
                if campaign and not campaign.is_voting_open:
                    return render(request, "ballot/voting_closed.html", {
                        "campaign": campaign,
                    })

            except Exception:
                # SECURITY: fail closed for vote-changing actions.
                # If campaign state cannot be verified, do not allow voting through.
                return render(request, "ballot/voting_closed.html", {
                    "campaign": None,
                })

        return self.get_response(request)
