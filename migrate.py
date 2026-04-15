"""
Database migration script for upgrading from v0.1.0 to v0.2.0 (SonarQube-like features).

This script adds new tables and columns required for:
- User management and authentication
- Quality gates and conditions
- Issue comments and resolution tracking
- Activity logging and audit trail
- Technical debt calculation
- CWE and column information

Usage:
    python migrate.py
"""

import sys
import os

# Add parent directory to path so we can import pvs_tracker
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlmodel import SQLModel, Session, select
from pvs_tracker.db import engine
from pvs_tracker.models import User, UserRole
from pvs_tracker.security import hash_password
from pvs_tracker.quality_gate import create_default_quality_gate


def run_migration():
    """Run the database migration."""
    print("Starting database migration...")

    # Create all new tables
    print("Creating new tables...")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        # Initialize default quality gate
        print("Creating default quality gate...")
        create_default_quality_gate(session)

        # Create default admin user if no users exist
        print("Checking for existing users...")
        existing_user = session.exec(select(User).limit(1)).first()
        if not existing_user:
            print("Creating default admin user (username: admin, password: admin)...")
            admin_user = User(
                username="admin",
                email="admin@localhost",
                password_hash=hash_password("admin"),
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(admin_user)
            session.commit()
            print("✓ Admin user created successfully")
        else:
            print("✓ Users already exist, skipping admin creation")

    print("\nMigration completed successfully!")
    print("\nNew features enabled:")
    print("  ✓ User authentication with JWT tokens")
    print("  ✓ Role-based access control (admin/user/viewer)")
    print("  ✓ Quality gates with custom thresholds")
    print("  ✓ Issue comments and resolution workflow")
    print("  ✓ Activity logging and audit trail")
    print("  ✓ Technical debt calculation")
    print("  ✓ CWE and column information tracking")
    print("  ✓ CSV export functionality")
    print("  ✓ Webhook integration for CI/CD")
    print("\nDefault admin credentials:")
    print("  Username: admin")
    print("  Password: admin")
    print("\n⚠️  Please change the admin password after first login!")


if __name__ == "__main__":
    try:
        run_migration()
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
