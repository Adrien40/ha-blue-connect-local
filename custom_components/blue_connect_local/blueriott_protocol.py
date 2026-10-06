"""Décodage d'une notification active BlueRiott.

Le périphérique BlueRiott utilisé pour les tests renvoie une trame de 12 octets
commençant par 0x33 lors d'une mesure active.

Format observé :
- octet 0      : marqueur 0x33
- octets 1..2  : température, little-endian, centièmes de degré
- octets 3..4  : valeur brute pH
- octets 5..6  : valeur brute ORP
- octets 7..8  : valeur brute conductivité
- octets 9..10 : tension batterie en mV
- octet 11     : valeur non exploitée ici

Le décodage est volontairement séparé du protocole Zodiac existant.
"""

from __future__ import annotations

from typing import Any

FRAME_LENGTH = 12
FRAME_MARKER = 0x33

BATTERY_EMPTY_MV = 3400
BATTERY_FULL_MV = 3640
CONDUCTIVITY_COEFFICIENT = 1.0615


def _battery_percent(voltage_mv: int) -> int:
    """Convertir la tension batterie en pourcentage borné entre 0 et 100."""
    span = BATTERY_FULL_MV - BATTERY_EMPTY_MV
    value = round((voltage_mv - BATTERY_EMPTY_MV) / span * 100)
    return max(0, min(100, value))


def parse_blueriott_frame(frame: bytes) -> dict[str, Any] | None:
    """Décoder une trame BlueRiott de 12 octets.

    Retourne un dictionnaire compatible avec les données du coordinator.
    Retourne None si la trame n'est pas au format BlueRiott attendu.
    """
    if len(frame) != FRAME_LENGTH or frame[0] != FRAME_MARKER:
        return None

    try:
        temperature_raw = int.from_bytes(frame[1:3], "little")
        ph_raw = int.from_bytes(frame[3:5], "little")
        orp_raw = int.from_bytes(frame[5:7], "little")
        conductivity_raw = int.from_bytes(frame[7:9], "little")
        battery_mv = int.from_bytes(frame[9:11], "little")

        temperature = temperature_raw / 100.0
        ph = (2048 - ph_raw) / 232.0 + 7.0
        orp = orp_raw / 4.0 - 5.0

        if conductivity_raw:
            conductivity = (
                1 / (conductivity_raw * 1e-6)
                * CONDUCTIVITY_COEFFICIENT
            )
            salinity = (
                1 / (conductivity_raw * 0.001)
                * CONDUCTIVITY_COEFFICIENT
                * 0.5
            )
        else:
            conductivity = 0.0
            salinity = 0.0

        return {
            "device_type": "blueriott",
            "temp_raw": temperature,
            "ph_raw": ph,
            "orp_raw": orp,
            "temperature": round(temperature, 2),
            "ph": round(ph, 2),
            "orp": round(orp, 1),
            "conductivity": round(conductivity, 1),
            "salinity": round(salinity, 2),
            "battery": battery_mv,
            "battery_percent": _battery_percent(battery_mv),
            "blueriott_data": frame.hex().upper(),
        }

    except (IndexError, TypeError, ValueError, ZeroDivisionError):
        return None
