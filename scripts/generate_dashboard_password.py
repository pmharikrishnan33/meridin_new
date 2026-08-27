from getpass import getpass

from app.core.dashboard_security import hash_password


def main() -> None:
    password = getpass(
        "Enter dashboard password: "
    )

    confirmation = getpass(
        "Confirm dashboard password: "
    )

    if password != confirmation:
        raise SystemExit(
            "Passwords do not match."
        )

    print()
    print("Password hash:")
    print(hash_password(password))


if __name__ == "__main__":
    main()
