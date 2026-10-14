"""Database connection management."""

from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from smart_investor.db.config import DatabaseConfig


class DatabaseConnection:
    """Manages MySQL database connections using SQLAlchemy."""

    def __init__(self, config: DatabaseConfig) -> None:
        """Initialize database connection.

        Args:
            config: Database configuration
        """
        self.config = config
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker[Session]] = None

    @property
    def engine(self) -> Engine:
        """Get SQLAlchemy engine, creating if necessary.

        Returns:
            Engine: SQLAlchemy engine instance
        """
        if self._engine is None:
            self._engine = create_engine(
                self.config.get_connection_url(),
                pool_size=self.config.pool_size,
                pool_recycle=self.config.pool_recycle,
                pool_pre_ping=True,
                echo=self.config.echo,
            )
        return self._engine

    @property
    def session_factory(self) -> sessionmaker[Session]:
        """Get session factory, creating if necessary.

        Returns:
            sessionmaker: SQLAlchemy session factory
        """
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine, expire_on_commit=False
            )
        return self._session_factory

    def get_session(self) -> Session:
        """Create a new database session.

        Returns:
            Session: SQLAlchemy session for database operations

        Example:
            >>> db = DatabaseConnection(config)
            >>> with db.get_session() as session:
            ...     result = session.execute(text("SELECT 1"))
            ...     print(result.scalar())
        """
        return self.session_factory()

    def test_connection(self) -> bool:
        """Test database connection.

        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            with self.get_session() as session:
                result = session.execute(text("SELECT 1"))
                return result.scalar() == 1
        except Exception:
            return False

    def close(self) -> None:
        """Close database connection and dispose of engine."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None

    def __enter__(self) -> "DatabaseConnection":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Context manager exit."""
        self.close()

    def __repr__(self) -> str:
        """String representation."""
        return f"DatabaseConnection({self.config})"
