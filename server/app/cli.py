"""Admin commands. There is no public sign-up, so the first account starts here.

    python -m app.cli create-admin --email you@example.com --name "Jazz" [--household "Jazz"]

Prints a generated password once. Everyone else joins through household invites.
"""
import argparse
import secrets
import string
import sys

from sqlalchemy import select

from .db import Base, SessionLocal, engine
from .models import Household, Location, Membership, User
from .routers.households import DEFAULT_LOCATIONS
from .security import hash_password


def create_admin(email: str, name: str, household: str | None) -> None:
    Base.metadata.create_all(engine)
    email = email.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            sys.exit(f"{email} already has an account")
        alphabet = string.ascii_letters + string.digits
        password = "".join(secrets.choice(alphabet) for _ in range(20))
        user = User(email=email, name=name, password_hash=hash_password(password), is_admin=True)
        db.add(user)
        db.flush()
        if household:
            h = Household(name=household)
            db.add(h)
            db.flush()
            db.add(Membership(user_id=user.id, household_id=h.id, role="owner"))
            for loc, freezer in DEFAULT_LOCATIONS:
                db.add(Location(household_id=h.id, name=loc, is_freezer=freezer))
        db.commit()
    print(f"created admin {email}")
    print(f"password: {password}")


def digest(kind: str, dry_run: bool) -> None:
    """Send the expiry or weekly digest for every household (nothing when there is no news)."""
    from .services import digest as dg
    with SessionLocal() as db:
        for h in db.scalars(select(Household)):
            if kind == "expiry":
                msg = dg.expiry_message(dg.expiring(db, h.id))
                title, tags = f"{h.name}: use these soon", "hourglass_flowing_sand"
            else:
                msg = dg.weekly_message(dg.spending(db, h.id, days=7))
                title, tags = f"{h.name}: groceries this week", "shopping_cart"
            if not msg:
                print(f"{h.name}: nothing to send")
                continue
            print(f"{h.name}:\n{msg}")
            if not dry_run:
                dg.send(title, msg, tags)


def main() -> None:
    ap = argparse.ArgumentParser(prog="kasita")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-admin")
    c.add_argument("--email", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--household")
    d = sub.add_parser("digest", help="push the expiry or weekly digest to ntfy")
    d.add_argument("kind", choices=["expiry", "weekly"])
    d.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.cmd == "create-admin":
        create_admin(args.email, args.name, args.household)
    elif args.cmd == "digest":
        digest(args.kind, args.dry_run)


if __name__ == "__main__":
    main()
