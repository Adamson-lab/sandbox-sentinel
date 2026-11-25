import json
import urllib.request


class Notifier:
    def __init__(self):
        self.messages = []

    def send(self, severity: str, sandbox_id: str, text: str):
        self.messages.append((severity, sandbox_id, text))
        print(f"  [{severity:<8}] {sandbox_id}: {text}")


class WebhookNotifier(Notifier):
    """Slack/Teams-compatible incoming webhook."""

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def send(self, severity, sandbox_id, text):
        super().send(severity, sandbox_id, text)
        body = json.dumps({"text": f"[{severity}] {sandbox_id}: {text}"}).encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:  # alerting must never break enforcement
            print(f"  (webhook failed: {e})")
