"""Cover platform for Zigbee2MQTT WebSocket integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import SIGNAL_DEVICES_UPDATED, Z2MCoordinator
from .entity import Z2MEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def _get_cover_exposes(definition: dict | None) -> list[dict]:
    if not definition:
        return []
    return [e for e in definition.get("exposes", []) if e.get("type") == "cover"]


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
            if _get_cover_exposes(device.get("definition")):
                known.add(ieee)
                new_entities.append(Z2MCover(coordinator, device))
        if new_entities:
            async_add_entities(new_entities)

    async_dispatcher_connect(hass, SIGNAL_DEVICES_UPDATED, _add_devices)
    if coordinator.devices:
        _add_devices(coordinator.devices)


class Z2MCover(Z2MEntity, CoverEntity):
    """A Zigbee2MQTT cover (blind/shutter)."""

    _attr_device_class = CoverDeviceClass.BLIND
    _attr_name = None

    def __init__(self, coordinator: Z2MCoordinator, device: dict) -> None:
        super().__init__(coordinator, device, feature={"property": "cover", "label": "Cover"})

        exposes = _get_cover_exposes(device.get("definition"))
        feature_props: set[str] = set()
        for expose in exposes:
            for feat in expose.get("features", []):
                feature_props.add(feat.get("property", ""))

        features = CoverEntityFeature(0)
        if "state" in feature_props:
            features |= CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        if "position" in feature_props:
            features |= CoverEntityFeature.SET_POSITION
        if "tilt" in feature_props:
            features |= CoverEntityFeature.SET_TILT_POSITION
        self._attr_supported_features = features

    @property
    def is_closed(self) -> bool | None:
        state = self._get_state_value("state")
        if state is None:
            pos = self._get_state_value("position")
            return pos == 0 if pos is not None else None
        return str(state).upper() == "CLOSE"

    @property
    def current_cover_position(self) -> int | None:
        return self._get_state_value("position")

    @property
    def current_cover_tilt_position(self) -> int | None:
        return self._get_state_value("tilt")

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._publish_set({"state": "OPEN"})

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._publish_set({"state": "CLOSE"})

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._publish_set({"state": "STOP"})

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        await self._publish_set({"position": kwargs[ATTR_POSITION]})

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        await self._publish_set({"tilt": kwargs[ATTR_TILT_POSITION]})
