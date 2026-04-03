import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Enum, Text
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Employee(Base):
    """Maps employee IDs to their phone extensions and UKG identifiers."""

    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    phone_extension = Column(String(20), index=True)
    caller_id = Column(String(20), index=True)
    ukg_employee_id = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class TimePunch(Base):
    """Records each clock-in/clock-out event with its UKG sync status."""

    __tablename__ = "time_punches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(String(50), nullable=False, index=True)
    punch_type = Column(
        Enum("clock_in", "clock_out", name="punch_type_enum"), nullable=False
    )
    punch_time = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    source_caller_id = Column(String(20))
    ukg_synced = Column(Enum("pending", "success", "failed", name="sync_status_enum"),
                        default="pending")
    ukg_response = Column(String(500))
    retry_count = Column(Integer, default=0)
    last_retry_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class SystemConfig(Base):
    """Stores runtime configuration for UKG and CUCM connections.

    Settings saved here override the environment-variable defaults,
    allowing admins to change connection parameters from the portal
    without restarting the application.
    """

    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(100), unique=True, nullable=False, index=True)
    config_value = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow,
                        onupdate=datetime.datetime.utcnow)


def init_db(database_url):
    """Initialize the database engine and create all tables."""
    engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)
