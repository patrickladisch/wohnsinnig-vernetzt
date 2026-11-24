"""Media-Player-Entität für Wohnsinnig vernetzt."""

from __future__ import annotations

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BROWSER_TARGET, BROWSER_TARGET_LABEL, DOMAIN
from .coordinator import WohnsinnigVernetztCoordinator
from .entity import WohnsinnigVernetztEntity


def get_available_targets(
    hass: HomeAssistant, exclude_entity_id: str | None = None
) -> dict[str, str]:
    """Liefert Mapping {kompakter Anzeigename: entity_id} für Browser und HA-Lautsprecher."""
    targets: dict[str, str] = {BROWSER_TARGET_LABEL: BROWSER_TARGET}
    for state in sorted(
        hass.states.async_all("media_player"), key=lambda s: s.name.lower()
    ):
        if state.entity_id == exclude_entity_id:
            continue
        if state.entity_id.startswith(f"media_player.{DOMAIN}"):
            continue
        raw_name = (state.name or state.entity_id).strip()
        label = raw_name if len(raw_name) <= 26 else raw_name[:25].rstrip() + "…"
        if label in targets:
            suffix = f" ({len(targets)})"
            label = f"{label[: max(6, 26 - len(suffix))].rstrip()}{suffix}"
        targets[label] = state.entity_id
    return targets


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Erstellt die Podcast-Media-Player-Entität."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WohnsinnigVernetztMediaPlayer(coordinator, entry.entry_id)])


class WohnsinnigVernetztMediaPlayer(WohnsinnigVernetztEntity, MediaPlayerEntity):
    """Spielt Podcast-Folgen über den Browser oder einen HA-Lautsprecher ab."""

    _attr_name = "Podcast: Player"
    _attr_icon = "mdi:podcast"
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "media_player")

    @property
    def state(self) -> MediaPlayerState:
        if self.coordinator.target_entity != BROWSER_TARGET:
            target_state = self.hass.states.get(self.coordinator.target_entity)
            if target_state is not None:
                if target_state.state == MediaPlayerState.PLAYING:
                    return MediaPlayerState.PLAYING
                if target_state.state == MediaPlayerState.PAUSED:
                    return MediaPlayerState.PAUSED
                if target_state.state == MediaPlayerState.BUFFERING:
                    return MediaPlayerState.BUFFERING

        if self.coordinator.playback_state == "playing":
            return MediaPlayerState.PLAYING
        if self.coordinator.playback_state == "paused":
            return MediaPlayerState.PAUSED
        return MediaPlayerState.IDLE

    @property
    def media_content_type(self) -> MediaType:
        return MediaType.PODCAST

    @property
    def media_content_id(self) -> str | None:
        ep = self.coordinator.get_selected_episode()
        return ep["audio_url"] if ep else None

    @property
    def media_title(self) -> str | None:
        ep = self.coordinator.get_selected_episode()
        return ep["title"] if ep else "Wohnsinnig vernetzt"

    @property
    def media_artist(self) -> str | None:
        return (self.coordinator.data or {}).get("title", "Wohnsinnig vernetzt")

    @property
    def media_duration(self) -> int | None:
        ep = self.coordinator.get_selected_episode()
        return ep.get("duration_sec") if ep else None

    @property
    def media_image_url(self) -> str | None:
        ep = self.coordinator.get_selected_episode()
        if ep and ep.get("image"):
            return ep["image"]
        return (self.coordinator.data or {}).get("image") or None

    @property
    def source_list(self) -> list[str]:
        return list(get_available_targets(self.hass, self.entity_id).keys())

    @property
    def source(self) -> str | None:
        targets = get_available_targets(self.hass, self.entity_id)
        for label, entity_id in targets.items():
            if entity_id == self.coordinator.target_entity:
                return label
        return BROWSER_TARGET_LABEL

    @property
    def extra_state_attributes(self) -> dict:
        ep = self.coordinator.get_selected_episode() or {}
        return {
            "selected_guid": ep.get("guid"),
            "audio_url": ep.get("audio_url", ""),
            "pub_date": ep.get("pub_date", ""),
            "duration_formatted": ep.get("duration", ""),
            "target_entity": self.coordinator.target_entity,
            "play_command_id": self.coordinator.play_command_id,
            "last_command_action": self.coordinator.last_command_action,
            "spotify_show_id": self.coordinator.spotify_show_id,
        }

    async def async_select_source(self, source: str) -> None:
        targets = get_available_targets(self.hass, self.entity_id)
        target_id = targets.get(source, BROWSER_TARGET)
        await self.coordinator.async_set_target_entity(target_id)

    async def async_media_play(self) -> None:
        await self.coordinator.async_resume()

    async def async_media_pause(self) -> None:
        await self.coordinator.async_pause()

    async def async_media_stop(self) -> None:
        await self.coordinator.async_stop()

    async def async_media_next_track(self) -> None:
        await self.coordinator.async_next_episode()

    async def async_media_previous_track(self) -> None:
        await self.coordinator.async_previous_episode()

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs
    ) -> None:
        await self.coordinator.async_play_episode(media_id)

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Zeigt alle Podcast-Folgen direkt im Home-Assistant-Medienbrowser an."""
        data = self.coordinator.data or {}
        episodes = data.get("episodes", [])
        children = [
            BrowseMedia(
                title=f"{ep['title']} ({ep['pub_date']})"
                if ep.get("pub_date")
                else ep["title"],
                media_class=MediaClass.EPISODE,
                media_content_id=ep["guid"],
                media_content_type=MediaType.EPISODE,
                can_play=True,
                can_expand=False,
                thumbnail=ep.get("image") or data.get("image") or None,
            )
            for ep in episodes
        ]
        return BrowseMedia(
            title=data.get("title", "Wohnsinnig vernetzt"),
            media_class=MediaClass.PODCAST,
            media_content_id="root",
            media_content_type=MediaType.PODCAST,
            can_play=False,
            can_expand=True,
            thumbnail=data.get("image") or None,
            children=children,
        )
