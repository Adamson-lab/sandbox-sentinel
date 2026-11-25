from abc import ABC, abstractmethod


class Provider(ABC):
    """Everything the engine needs from a cloud. Implementations MUST be idempotent."""

    @abstractmethod
    def launch(self, sb, resource): ...

    @abstractmethod
    def refresh(self, sb):
        """Reconcile sb.resources with reality (finds shadow resources)."""

    @abstractmethod
    def drain_usage(self, sb) -> float:
        """Return usage-based spend (egress, API calls, tokens) since last call."""

    @abstractmethod
    def stop(self, sb): ...

    @abstractmethod
    def revoke(self, sb): ...

    @abstractmethod
    def terminate(self, sb): ...
