#!/usr/bin/env python3
"""Test database connection script."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from smart_investor.db.config import DatabaseConfig
from smart_investor.db.connection import DatabaseConnection


def main() -> int:
    """Test database connection."""
    print("Testing database connection...")

    try:
        config = DatabaseConfig.from_env()
        print(f"Configuration: {config}")

        with DatabaseConnection(config) as db:
            if db.test_connection():
                print("✅ Database connection successful!")
                return 0
            else:
                print("❌ Database connection failed!")
                return 1

    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("\nRequired environment variables:")
        print("  - DB_NAME: Database name")
        print("  - DB_USER: Database user")
        print("  - DB_PASSWORD: Database password")
        print("\nOptional environment variables:")
        print("  - DB_HOST: Database host (default: localhost)")
        print("  - DB_PORT: Database port (default: 3306)")
        return 1

    except Exception as e:
        print(f"❌ Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
