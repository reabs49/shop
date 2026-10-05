from getpass import getpass

from werkzeug.security import generate_password_hash

from app import app
from extensions import db
from models import Admin


def main():
    print("=== Create Admin Account ===")

    username = input("Username: ").strip()

    if not username:
        print("Username cannot be empty.")
        return

    password = getpass("Password: ")
    password_confirmation = getpass("Confirm password: ")

    if password != password_confirmation:
        print("Passwords do not match.")
        return

    if len(password) < 12:
        print("Password must be at least 12 characters long.")
        return

    with app.app_context():

        existing_admin = Admin.query.filter_by(
            username=username
        ).first()

        if existing_admin:
            print("That username already exists.")
            return

        admin = Admin(
            username=username,
            password_hash=generate_password_hash(password)
        )

        db.session.add(admin)
        db.session.commit()

        print(f"Admin '{username}' created successfully.")


if __name__ == "__main__":
    main()