"""Siren platform for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.siren import (
    ATTR_DURATION,
    ATTR_TONE,
    SirenEntity,
    SirenEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import SIGNAL_DEVICES_UPDATED, Z2MCoordinator
from .entity import Z2MEntity

_LOGGER = logging.getLogger(__name__)

# Required for HA 2025.4+ – 0 = no limit, coordinator handles all updates
PARALLEL_UPDATES = 0

# Zigbee2MQTT exposes the siren as a composite "warning" property with
# mode / duration / strobe / strobe_duty_cycle. HA's siren platform has no
# strobe, so it is expressed as a tone: "flash" = light only, no sound.
TONE_EMERGENCY = "emergency"
TONE_FLASH = "flash"

_STROBE_DUTY_SOUND = 8
_STROBE_DUTY_FLASH = 5


def _get_warning_expose(definition: dict | None) -> dict | None:
    """Return the writable `warning` expose of a device, if it has one."""
    if not definition:
        return None
    for expose in definition.get("exposes", []):
        if expose.get("type") == "composite" and expose.get("property") == "warning":
            if expose.get("access", 0) & 2:  # settable
                return expose
    return None


def _warning_modes(expose: dict) -> list[str]:
    """Return the sound modes the device itself supports."""
    for feature in expose.get("features", []):
        if feature.get("property") == "mode":
            return list(feature.get("values") or [])
    return [TONE_EMERGENCY]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Z2MCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    known: set[str] = set()

    @callback
    def _add_devices(devices: list[dict]) -> None:
        new_entities = []
        for device in devices:
            ieee = device.get("ieee_address")
            if not ieee or ieee in known:
                continue
            expose = _get_warning_expose(device.get("definition"))
            if expose is None:
                continue
            known.add(ieee)
            new_entities.append(Z2MSiren(coordinator, device, expose))
        if new_entities:
            _LOGGER.info("Adding %d new siren entities", len(new_entities))
            async_add_entities(new_entities)

    async_dispatcher_connect(hass, SIGNAL_DEVICES_UPDATED, _add_devices)
    if coordinator.devices:
        _add_devices(coordinator.devices)


class Z2MSiren(Z2MEntity, SirenEntity):
    """Representation of a Zigbee2MQTT siren driven by the `warning` property."""

    def __init__(
        self, coordinator: Z2MCoordinator, device: dict, expose: dict
    ) -> None:
        super().__init__(coordinator, device, feature={"property": "warning"})
        self._attr_name = None
        self._attr_is_on = False
        self._cancel_timer = None

        modes = _warning_modes(expose)
        tones = list(modes)
        if TONE_FLASH not in tones:
            # Only offer the silent strobe when the device can strobe at all.
            if any(f.get("property") == "strobe" for f in expose.get("features", [])):
                tones.append(TONE_FLASH)

        self._attr_available_tones = tones
        self._attr_supported_features = (
            SirenEntityFeature.TURN_ON
            | SirenEntityFeature.TURN_OFF
            | SirenEntityFeature.DURATION
            | SirenEntityFeature.TONES
        )
        # Zigbee2MQTT does not report the warning state back, so the entity
        # keeps its own on/off state and clears it when the duration is over.
        self._modes = modes or [TONE_EMERGENCY]

    @property
    def is_on(self) -> bool:
        return self._attr_is_on

    @callback
    def _clear_timer(self) -> None:
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None

    @callback
    def _finished(self, _now: Any) -> None:
        self._cancel_timer = None
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._clear_timer)

    async def async_turn_on(self, **kwargs: Any) -> None:
        tone = kwargs.get(ATTR_TONE) or TONE_EMERGENCY
        duration = kwargs.get(ATTR_DURATION)

        if tone == TONE_FLASH:
            mode = "stop"  # no sound
            strobe_duty = _STROBE_DUTY_FLASH
        else:
            mode = tone if tone in self._modes else TONE_EMERGENCY
            strobe_duty = _STROBE_DUTY_SOUND

        warning: dict[str, Any] = {
            "mode": mode,
            "strobe": True,
            "strobe_duty_cycle": strobe_duty,
        }
        if duration:
            warning["duration"] = int(duration)

        await self._publish_set({"warning": warning})

        self._clear_timer()
        self._attr_is_on = mode != "stop"
        self.async_write_ha_state()
        if duration:
            self._cancel_timer = async_call_later(
                self.hass, int(duration), self._finished
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._publish_set({"warning": {"mode": "stop"}})
        self._clear_timer()
        self._attr_is_on = False
        self.async_write_ha_state()
