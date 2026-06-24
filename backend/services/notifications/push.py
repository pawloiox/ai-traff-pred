import logging
import sqlite3
from typing import List
import firebase_admin
from firebase_admin import credentials, messaging

logger = logging.getLogger(__name__)

# Próba inicjalizacji Firebase (wymaga pliku firebase_credentials.json)
try:
    cred = credentials.Certificate("firebase_credentials.json")
    firebase_admin.initialize_app(cred)
    FIREBASE_INITIALIZED = True
except Exception as e:
    logger.warning(f"Brak lub zły klucz Firebase (firebase_credentials.json). Firebase wyłączony. Błąd: {e}")
    FIREBASE_INITIALIZED = False

def send_push_notification(title: str, body: str, port_id: str = "gdansk") -> None:
    """Wysyłka Firebase Push Notification do wszystkich w bazie."""
    from app.storage import storage
    
    if not FIREBASE_INITIALIZED:
        logger.info(f"MOCK [Push] (brak klucza FCM) -> {title} | {body}")
        return

    # Pobierz wszystkie tokeny
    tokens = []
    with storage._lock:
        cur = storage._conn.execute("SELECT token FROM push_subscriptions")
        tokens = [row["token"] for row in cur.fetchall()]

    if not tokens:
        logger.info("Brak zapisanych tokenów - powiadomienie nie wysłane.")
        return

    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        tokens=tokens,
    )
    
    try:
        response = messaging.send_each_for_multicast(message)
        logger.info(f"Wysłano powiadomienia (sukces: {response.success_count}, błędy: {response.failure_count})")
    except Exception as e:
        logger.error(f"Błąd wysyłki Firebase Push: {e}")
