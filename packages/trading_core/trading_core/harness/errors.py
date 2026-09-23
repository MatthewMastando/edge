"""Workflow control-flow errors. These are not shown to the model."""


class LeaseLostError(RuntimeError):
    pass


class WorkflowPausedError(Exception):
    """The job was moved to ``partial`` and the lease was released."""


class SuspendWorkflowError(Exception):
    """Stop after the current stage and leave the job leasable in ``partial``."""

    def __init__(self, reason: str = "suspended") -> None:
        super().__init__(reason)
        self.reason = reason
