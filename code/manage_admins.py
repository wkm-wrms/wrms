"""
Emergency admin management CLI for WRMS.

Use this script when all admin accounts are locked out and you cannot log in
through the web interface. Requires direct shell access to the server.

Usage:
    python manage_admins.py list
    python manage_admins.py add    --username <name> --password <pw>
    python manage_admins.py reset  --username <name> --password <new_pw>
    python manage_admins.py remove --username <name>

The script connects directly to data/race_system.db (or the path set in
the WRMS_DB_PATH environment variable). No running server is required.
"""
import argparse
import os
import sys

# Ensure the code/ directory is on the path so database.py can be imported
sys.path.insert(0, os.path.dirname(__file__))

from database import RaceDatabase  # noqa: E402


def _get_db() -> RaceDatabase:
    db_path = os.environ.get("WRMS_DB_PATH", "data/race_system.db")
    return RaceDatabase(db_path=db_path)


def cmd_list(_args) -> int:
    """Print all admin accounts."""
    db = _get_db()
    admins = db.list_admins()
    if not admins:
        print("No admin accounts found.")
        return 0
    print(f"{'Username':<30}  Created at")
    print("-" * 55)
    for a in admins:
        print(f"{a['username']:<30}  {a['created_at']}")
    return 0


def cmd_add(args) -> int:
    """Create a new admin account."""
    db = _get_db()
    success = db.add_admin(args.username, args.password)
    if not success:
        print(f"Error: username '{args.username}' already exists.", file=sys.stderr)
        return 1
    print(f"Admin '{args.username}' created successfully.")
    return 0


def cmd_reset(args) -> int:
    """Reset an admin password."""
    db = _get_db()
    success = db.set_admin_password(args.username, args.password)
    if not success:
        print(f"Error: admin '{args.username}' not found.", file=sys.stderr)
        return 1
    print(f"Password for '{args.username}' updated successfully.")
    return 0


def cmd_remove(args) -> int:
    """Remove an admin account."""
    db = _get_db()
    confirm = input(
        f"Remove admin '{args.username}'? This cannot be undone. [y/N] "
    ).strip().lower()
    if confirm != "y":
        print("Aborted.")
        return 0
    success = db.remove_admin(args.username)
    if not success:
        print(f"Error: admin '{args.username}' not found.", file=sys.stderr)
        return 1
    print(f"Admin '{args.username}' removed.")
    return 0


def main():
    """Entry point — parse CLI arguments and dispatch to command functions."""
    parser = argparse.ArgumentParser(
        description="WRMS emergency admin management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List all admin accounts")

    p_add = sub.add_parser("add", help="Create a new admin account")
    p_add.add_argument("--username", required=True)
    p_add.add_argument("--password", required=True)

    p_reset = sub.add_parser("reset", help="Reset an admin password")
    p_reset.add_argument("--username", required=True)
    p_reset.add_argument("--password", required=True, metavar="NEW_PASSWORD")

    p_remove = sub.add_parser("remove", help="Remove an admin account")
    p_remove.add_argument("--username", required=True)

    args = parser.parse_args()

    commands = {
        "list": cmd_list,
        "add": cmd_add,
        "reset": cmd_reset,
        "remove": cmd_remove,
    }

    if args.command not in commands:
        parser.print_help()
        sys.exit(1)

    sys.exit(commands[args.command](args))


if __name__ == "__main__":
    main()
