from django.core.management.base import BaseCommand
from ballot.models import MembershipPlan, MembershipBenefit, MembershipReward


class Command(BaseCommand):
    help = "Seed ATL's Hottest membership packages, benefits, rewards, credits, and discounts."

    def handle(self, *args, **options):
        plans = [
            {
                "old_slugs": ["nominee-membership", "i-am-atls-hottest-association-yearly-support"],
                "slug": "i-am-atls-hottest-association-yearly-support",
                "name": "I Am ATL’s Hottest Association Yearly Support",
                "price": 39,
                "badge": "Association Support",
                "order": 2,
                "featured": False,
                "discount": "15% advertising discount",
                "credit": "Advertising credit eligibility after 3 months of paid monthly membership",
                "description": "One-time introductory yearly support package for ATL’s Hottest supporters, nominees, fans, creators, and community members who want association visibility and member benefits.",
            },
            {
                "old_slugs": ["atls-hottest-allstar"],
                "slug": "atls-hottest-allstar",
                "name": "ATL’s Hottest AllStar",
                "price": 59,
                "badge": "AllStar",
                "order": 3,
                "featured": True,
                "discount": "20% advertising discount",
                "credit": "$10 advertising credit",
                "description": "One-time introductory membership for ATL’s Hottest members who want stronger visibility, promotional positioning, seller opportunities, and access to advertising tools.",
            },
            {
                "old_slugs": ["professional-member"],
                "slug": "professional-member",
                "name": "Professional Member",
                "price": 99,
                "badge": "Professional",
                "order": 4,
                "featured": False,
                "discount": "30% advertising discount",
                "credit": "$25 advertising credit",
                "description": "Professional visibility package for members, creators, entrepreneurs, and businesses preparing to sell, promote, and grow inside ATL’s Hottest.",
            },
            {
                "old_slugs": ["vip-elite-member"],
                "slug": "vip-elite-member",
                "name": "VIP Elite Member",
                "price": 199,
                "badge": "VIP Elite",
                "order": 5,
                "featured": False,
                "discount": "40% advertising discount",
                "credit": "$50 advertising credit",
                "description": "Premium membership package for high-visibility members, brands, businesses, creators, and future merchants inside The ATL’s Hottest Zone of The MajicMall Megaverse inside the Majestic Megaverse.",
            },
        ]

        for item in plans:
            plan = None

            for old_slug in item["old_slugs"]:
                plan = MembershipPlan.objects.filter(slug=old_slug).first()
                if plan:
                    break

            if plan is None:
                plan = MembershipPlan(slug=item["slug"])

            plan.slug = item["slug"]
            plan.name = item["name"]
            plan.tagline = f"{item['credit']} · {item['discount']} · Seller visibility tools"
            plan.description = item["description"] + " Introductory prices are available for one year."
            plan.price = item["price"]
            plan.billing_period = "one_time"
            plan.badge_label = item["badge"]
            plan.display_order = item["order"]
            plan.is_featured = item["featured"]
            plan.is_active = True
            plan.save()

            benefits = [
                ("ATL’s Hottest Visibility", "Receive visibility as part of the ATL’s Hottest member, nominee, creator, supporter, business, or merchant ecosystem."),
                ("Seller & Product Promotion Tools", "Members are positioned to sell or promote products, services, offers, tickets, music, media, merchandise, or branded campaigns."),
                ("The ATL’s Hottest Zone Merchant Positioning", "Members are connected to future merchant opportunities in The ATL’s Hottest Zone of The MajicMall Megaverse inside the Majestic Megaverse."),
                ("Advertising Platform Access", "Access billboard, banner, ATL TV, category campaign, and sponsored visibility opportunities through The MajesticMall Megaverse Advertising Platform."),
                ("Introductory One-Year Pricing", "Membership prices are introductory for the first year as the ATL’s Hottest platform expands."),
            ]

            for index, (title, desc) in enumerate(benefits, 1):
                MembershipBenefit.objects.update_or_create(
                    plan=plan,
                    title=title,
                    defaults={
                        "description": desc,
                        "display_order": index,
                        "is_highlighted": index <= 3,
                    },
                )

            rewards = [
                ("Advertising Credit", item["credit"], "Credit may be used toward eligible billboard, banner, ATL TV, or campaign advertising. Monthly members receive advertising credit after 3 months of paid monthly membership.", "credit"),
                ("Advertising Discount", item["discount"], "Discount applies to eligible ATL’s Hottest advertising placements, billboard campaigns, banner promotions, and sponsored visibility opportunities.", "discount"),
                ("Merchant Visibility", "Seller positioning included", "Members are positioned as merchants in The ATL’s Hottest Zone of The MajicMall Megaverse inside the Majestic Megaverse.", "access"),
                ("Marketplace Access", "Benefits, add-ons, merch, badges, and advertising bundles", "Members can access ATL’s Hottest Marketplace options including T-shirts, badges, fans, ad bundles, and product promotion add-ons.", "access"),
            ]

            for index, (title, value, desc, reward_type) in enumerate(rewards, 1):
                MembershipReward.objects.update_or_create(
                    plan=plan,
                    title=title,
                    defaults={
                        "reward_type": reward_type,
                        "description": desc,
                        "value": value,
                        "display_order": index,
                        "is_active": True,
                    },
                )

            self.stdout.write(self.style.SUCCESS(f"Updated {plan.name}"))

        self.stdout.write(self.style.SUCCESS("ATL's Hottest membership packages seeded successfully."))
