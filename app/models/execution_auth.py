"""Short-lived replay ledger for connector-signed execution requests."""
from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base


class ExecutionRequestNonce(Base):
    __tablename__ = "execution_request_nonce"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)
