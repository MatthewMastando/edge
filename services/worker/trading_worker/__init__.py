"""Worker process. Leases durable jobs from Postgres (FOR UPDATE SKIP LOCKED), runs workflow
stages with checkpoints, and never holds broker credentials."""

__version__ = "0.1.0"
