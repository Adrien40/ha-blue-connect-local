"""Profil Bluetooth GATT spécifique aux appareils BlueRiott.

Ce module isole les UUID propres au matériel BlueRiott afin de ne pas
mélanger leur gestion avec le profil Zodiac déjà supporté par l'intégration.

Le profil est détecté dynamiquement à partir des services GATT exposés
par le périphérique.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# Caractéristique utilisée pour l'authentification / l'activation du périphérique.
BLUERIOTT_CHAR_AUTH_UUID = "f3300002-f0a2-9b06-0c59-1bc4763b5c00"

# Caractéristique principale utilisée pour déclencher une mesure.
BLUERIOTT_CHAR_TRIGGER_UUID = "f3300005-f0a2-9b06-0c59-1bc4763b5c00"

# Plusieurs caractéristiques peuvent émettre la notification contenant
# la mesure. On s'abonne uniquement à celles réellement présentes.
BLUERIOTT_NOTIFY_UUIDS: tuple[str, ...] = (
    "f3300003-f0a2-9b06-0c59-1bc4763b5c00",
    "f3300006-f0a2-9b06-0c59-1bc4763b5c00",
    "f3300010-f0a2-9b06-0c59-1bc4763b5c00",
)

# Certaines variantes BlueRiott nécessitent l'écriture du déclencheur
# sur plusieurs caractéristiques. Les erreurs sur ces UUID supplémentaires
# ne doivent pas rendre la mesure principale bloquante.
BLUERIOTT_EXTRA_TRIGGER_UUIDS: tuple[str, ...] = (
    "f3300002-f0a2-9b06-0c59-1bc4763b5c00",
    "f3300007-f0a2-9b06-0c59-1bc4763b5c00",
    "f3300020-f0a2-9b06-0c59-1bc4763b5c00",
)


def _iter_characteristics(services: Iterable[Any]):
    """Parcourir toutes les caractéristiques GATT exposées."""
    for service in services:
        yield from service.characteristics


def is_blueriott_services(services: Iterable[Any]) -> bool:
    """Retourner True si les services correspondent au profil BlueRiott."""
    available = {
        str(characteristic.uuid).lower()
        for characteristic in _iter_characteristics(services)
    }
    required = {
        BLUERIOTT_CHAR_AUTH_UUID.lower(),
        BLUERIOTT_CHAR_TRIGGER_UUID.lower(),
    }
    return required.issubset(available)


def available_blueriott_notify_uuids(services: Iterable[Any]) -> list[str]:
    """Lister les caractéristiques BlueRiott disponibles avec propriété notify."""
    known = {uuid.lower() for uuid in BLUERIOTT_NOTIFY_UUIDS}
    result: list[str] = []

    for characteristic in _iter_characteristics(services):
        uuid = str(characteristic.uuid)
        if uuid.lower() in known and "notify" in characteristic.properties:
            result.append(uuid)

    return result
