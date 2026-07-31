# scripts/create_worker.py
"""Creates a worker app login. No public self-registration — the owner runs
this to provision each account (tradie, sales, or their own owner login).

Usage: python scripts/create_worker.py <username> <name> [--role {tradie,sales,owner}]
(prompts for a password so it never lands in shell history)
"""

import argparse
import getpass

from app.auth import hash_password
from app.db import SessionLocal
from app.models import Worker, WorkerRole


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("name")
    parser.add_argument(
        "--role",
        choices=[r.value for r in WorkerRole],
        default=WorkerRole.tradie.value,
        help="account role — gates app/auth.py::require_owner / require_sales",
    )
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        print("passwords did not match")
        raise SystemExit(1)

    db = SessionLocal()
    try:
        worker = Worker(
            username=args.username, name=args.name, hashed_password=hash_password(password), role=WorkerRole(args.role)
        )
        db.add(worker)
        db.commit()
        print(f"created {args.role} {worker.id} ({args.username})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
