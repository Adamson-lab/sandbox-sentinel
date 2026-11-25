from .base import Provider


class SimProvider(Provider):
    """In-memory cloud. Lets you rehearse the kill-switch with zero risk and zero cost."""

    def launch(self, sb, resource):
        pass

    def refresh(self, sb):
        pass

    def drain_usage(self, sb):
        if sb.credentials_revoked:     # revoked principal can't incur usage
            sb.pending_usage_usd = 0.0
            return 0.0
        v, sb.pending_usage_usd = sb.pending_usage_usd, 0.0
        return v

    def stop(self, sb):
        for r in sb.resources:
            if r.state == "running":
                r.state = "stopped"

    def revoke(self, sb):
        sb.credentials_revoked = True

    def terminate(self, sb):
        for r in sb.resources:
            r.state = "terminated"
        sb.credentials_revoked = True
