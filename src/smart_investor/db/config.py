"""Database configuration management."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def load_env() -> None:
    """Load .env file from project root.

    Shared by every component that reads configuration from the environment,
    so a collector constructed before any database call still sees ``.env``.
    """
    # Try to find .env file in current directory or parent directories
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        env_file = parent / ".env"
        if env_file.exists():
            load_dotenv(env_file)
            return
    # Fallback: try default load
    load_dotenv()


# Backwards-compatible alias for the previously private name.
_load_env = load_env


@dataclass
class DatabaseConfig:
    """MySQL database configuration."""

    host: str
    port: int
    database: str
    user: str
    password: str
    charset: str = "utf8mb4"
    pool_size: int = 5
    pool_recycle: int = 3600
    echo: bool = False

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Create configuration from environment variables.

        Expected environment variables:
        - DB_HOST: Database host (default: localhost)
        - DB_PORT: Database port (default: 3306)
        - DB_NAME: Database name (required)
        - DB_USER: Database user (required)
        - DB_PASSWORD: Database password (required)
        - DB_CHARSET: Character set (default: utf8mb4)
        - DB_POOL_SIZE: Connection pool size (default: 5)
        - DB_POOL_RECYCLE: Pool recycle time in seconds (default: 3600)
        - DB_ECHO: SQLAlchemy echo mode (default: False)

        Returns:
            DatabaseConfig: Configuration instance

        Raises:
            ValueError: If required environment variables are missing
        """
        # Auto-load .env file
        load_env()

        db_name = os.getenv("DB_NAME")
        db_user = os.getenv("DB_USER")
        db_password = os.getenv("DB_PASSWORD")

        if not db_name:
            raise ValueError("DB_NAME environment variable is required")
        if not db_user:
            raise ValueError("DB_USER environment variable is required")
        if not db_password:
            raise ValueError("DB_PASSWORD environment variable is required")

        return cls(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "3306")),
            database=db_name,
            user=db_user,
            password=db_password,
            charset=os.getenv("DB_CHARSET", "utf8mb4"),
            pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
            pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "3600")),
            echo=os.getenv("DB_ECHO", "").lower() in ("true", "1", "yes"),
        )

    def get_connection_url(self) -> str:
        """Get SQLAlchemy database connection URL.

        Returns:
            str: Database connection URL in format:
                mysql+pymysql://user:password@host:port/database?charset=charset
        """
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
            f"?charset={self.charset}"
        )

    def __repr__(self) -> str:
        """String representation with masked password."""
        return (
            f"DatabaseConfig(host='{self.host}', port={self.port}, "
            f"database='{self.database}', user='{self.user}', "
            f"password='***', charset='{self.charset}')"
        )
