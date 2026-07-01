# ballot/context_processors.py
from .models import BallotSettings


def ballot_status(request):
    settings = BallotSettings.get_solo()
    return {
        "BALLOT": {
            "is_active": settings.is_active(),
            "status": settings.status_label(),
            "start_at": settings.start_at,
            "end_at": settings.end_at,
            "announcement": settings.announcement,
        }
    }
