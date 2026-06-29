import json
import uuid
from datetime import datetime, timezone
from typing import Any

from google.cloud import pubsub_v1

from app.config import settings

_publisher: pubsub_v1.PublisherClient | None = None


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def publish_event(
    event_type: str,
    payload: dict[str, Any],
    actor_uid: str = "",
    actor_role: str = "",
) -> None:
    """Publica un evento al tópico de Pub/Sub de vivienda."""
    if settings.environment == "development":
        return

    publisher = _get_publisher()
    topic_path = publisher.topic_path(
        settings.gcp_project_id, settings.pubsub_topic_vivienda
    )
    message = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "service": settings.service_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": {"user_id": actor_uid, "role": actor_role},
        "payload": payload,
    }
    publisher.publish(topic_path, json.dumps(message).encode("utf-8"))
