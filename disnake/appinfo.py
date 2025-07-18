# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, cast

from . import utils
from .asset import Asset
from .flags import ApplicationFlags
from .permissions import Permissions

if TYPE_CHECKING:
    from .guild import Guild
    from .state import ConnectionState
    from .types.appinfo import (
        AppInfo as AppInfoPayload,
        ApplicationIntegrationType as ApplicationIntegrationTypeLiteral,
        ApplicationIntegrationTypeConfiguration as ApplicationIntegrationTypeConfigurationPayload,
        InstallParams as InstallParamsPayload,
        PartialAppInfo as PartialAppInfoPayload,
        Team as TeamPayload,
    )
    from .user import User

__all__ = (
    "AppInfo",
    "PartialAppInfo",
    "InstallParams",
    "InstallTypeConfiguration",
)


class InstallParams:
    """Represents the installation parameters for the application, provided by Discord.

    .. versionadded:: 2.5

    Attributes
    ----------
    scopes: List[:class:`str`]
        The scopes requested by the application.
    permissions: :class:`Permissions`
        The permissions requested for the bot role.
    """

    __slots__ = (
        "_app_id",
        "_install_type",
        "scopes",
        "permissions",
    )

    def __init__(
        self,
        data: InstallParamsPayload,
        parent: AppInfo,
        *,
        install_type: Optional[ApplicationIntegrationTypeLiteral] = None,
    ) -> None:
        self._app_id = parent.id
        self._install_type: Optional[ApplicationIntegrationTypeLiteral] = install_type
        self.scopes = data["scopes"]
        self.permissions = Permissions(int(data["permissions"]))

    def __repr__(self) -> str:
        return f"<InstallParams scopes={self.scopes!r} permissions={self.permissions!r}>"

    def to_url(self) -> str:
        """Returns a string that can be used to install this application.

        Returns
        -------
        :class:`str`
            The invite url.
        """
        return utils.oauth_url(
            self._app_id,
            scopes=self.scopes,
            permissions=self.permissions,
            integration_type=(
                self._install_type if self._install_type is not None else utils.MISSING
            ),
        )


class InstallTypeConfiguration:
    """Represents the configuration for a particular application installation type.

    .. versionadded:: 2.10

    Attributes
    ----------
    install_params: Optional[:class:`InstallParams`]
        The parameters for this installation type.
    """

    __slots__ = ("install_params",)

    def __init__(
        self,
        data: ApplicationIntegrationTypeConfigurationPayload,
        *,
        parent: AppInfo,
        install_type: ApplicationIntegrationTypeLiteral,
    ) -> None:
        self.install_params: Optional[InstallParams] = (
            InstallParams(install_params, parent=parent, install_type=install_type)
            if (install_params := data.get("oauth2_install_params"))
            else None
        )


class AppInfo:
    """Represents the application info for the bot provided by Discord.

    Attributes
    ----------
    id: :class:`int`
        The application's ID.
    name: :class:`str`
        The application's name.
    owner: :class:`User`
        The application's owner.
    team: Optional[:class:`Team`]
        The application's team.

        .. versionadded:: 1.3

    description: :class:`str`
        The application's description.
    bot_public: :class:`bool`
        Whether the bot can be invited by anyone or if it is locked
        to the application owner.
    bot_require_code_grant: :class:`bool`
        Whether the bot requires the completion of the full oauth2 code
        grant flow to join.
    rpc_origins: Optional[List[:class:`str`]]
        A list of RPC origin URLs, if RPC is enabled.
    verify_key: :class:`str`
        The hex encoded key for verification in interactions and the
        GameSDK's :ddocs:`GetTicket <game-sdk/applications#getticket>`.

        .. versionadded:: 1.3

    guild_id: Optional[:class:`int`]
        The ID of the guild associated with the application, if any.

        .. versionadded:: 1.3

    primary_sku_id: Optional[:class:`int`]
        If this application is a game sold on Discord,
        this field will be the ID of the "Game SKU" that is created,
        if it exists.

        .. versionadded:: 1.3

    slug: Optional[:class:`str`]
        If this application is a game sold on Discord,
        this field will be the URL slug that links to the store page.

        .. versionadded:: 1.3

    terms_of_service_url: Optional[:class:`str`]
        The application's terms of service URL, if set.

        .. versionadded:: 2.0

    privacy_policy_url: Optional[:class:`str`]
        The application's privacy policy URL, if set.

        .. versionadded:: 2.0

    flags: Optional[:class:`ApplicationFlags`]
        The application's public flags.

        .. versionadded:: 2.3

    tags: Optional[List[:class:`str`]]
        The application's tags.

        .. versionadded:: 2.5

    install_params: Optional[:class:`InstallParams`]
        The installation parameters for this application.

        See also :attr:`guild_install_type_config`/:attr:`user_install_type_config`
        for installation type-specific configuration.

        .. versionadded:: 2.5

    custom_install_url: Optional[:class:`str`]
        The custom installation url for this application.

        .. versionadded:: 2.5
    role_connections_verification_url: Optional[:class:`str`]
        The application's role connection verification entry point,
        which when configured will render the app as a verification method
        in the guild role verification configuration.

        .. versionadded:: 2.8
    approximate_guild_count: :class:`int`
        The approximate number of guilds the application is installed to.

        .. versionadded:: 2.10
    approximate_user_install_count: :class:`int`
        The approximate number of users that have installed the application
        (for user-installable apps).

        .. versionadded:: 2.10

    approximate_user_authorization_count: :class:`int`
        The approximate number of users that have authorized the app with OAuth2.

        .. versionadded:: 2.11
    """

    __slots__ = (
        "_state",
        "description",
        "id",
        "name",
        "rpc_origins",
        "bot_public",
        "bot_require_code_grant",
        "owner",
        "_icon",
        "_summary",
        "verify_key",
        "team",
        "guild_id",
        "primary_sku_id",
        "slug",
        "_cover_image",
        "terms_of_service_url",
        "privacy_policy_url",
        "flags",
        "tags",
        "install_params",
        "custom_install_url",
        "role_connections_verification_url",
        "approximate_guild_count",
        "approximate_user_install_count",
        "approximate_user_authorization_count",
        "_install_types_config",
    )

    def __init__(self, state: ConnectionState, data: AppInfoPayload) -> None:
        from .team import Team

        self._state: ConnectionState = state
        self.id: int = int(data["id"])
        self.name: str = data["name"]
        self.description: str = data["description"]
        self._icon: Optional[str] = data["icon"]
        self.rpc_origins: List[str] = data["rpc_origins"]
        self.bot_public: bool = data["bot_public"]
        self.bot_require_code_grant: bool = data["bot_require_code_grant"]
        self.owner: User = state.create_user(data["owner"])

        team: Optional[TeamPayload] = data.get("team")
        self.team: Optional[Team] = Team(state, team) if team else None

        self._summary: str = data.get("summary", "")
        self.verify_key: str = data["verify_key"]

        self.guild_id: Optional[int] = utils._get_as_snowflake(data, "guild_id")

        self.primary_sku_id: Optional[int] = utils._get_as_snowflake(data, "primary_sku_id")
        self.slug: Optional[str] = data.get("slug")
        self._cover_image: Optional[str] = data.get("cover_image")
        self.terms_of_service_url: Optional[str] = data.get("terms_of_service_url")
        self.privacy_policy_url: Optional[str] = data.get("privacy_policy_url")

        flags: Optional[int] = data.get("flags")
        self.flags: Optional[ApplicationFlags] = (
            ApplicationFlags._from_value(flags) if flags is not None else None
        )
        self.tags: Optional[List[str]] = data.get("tags")
        self.install_params: Optional[InstallParams] = (
            InstallParams(data["install_params"], parent=self) if "install_params" in data else None
        )
        self.custom_install_url: Optional[str] = data.get("custom_install_url")
        self.role_connections_verification_url: Optional[str] = data.get(
            "role_connections_verification_url"
        )
        self.approximate_guild_count: int = data.get("approximate_guild_count", 0)
        self.approximate_user_install_count: int = data.get("approximate_user_install_count", 0)
        self.approximate_user_authorization_count: int = data.get(
            "approximate_user_authorization_count", 0
        )

        # this is a bit of a mess, but there's no better way to expose this data for now
        self._install_types_config: Dict[
            ApplicationIntegrationTypeLiteral, InstallTypeConfiguration
        ] = {}
        for type_str, config in (data.get("integration_types_config") or {}).items():
            install_type = cast("ApplicationIntegrationTypeLiteral", int(type_str))
            self._install_types_config[install_type] = InstallTypeConfiguration(
                config or {},
                parent=self,
                install_type=install_type,
            )

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} id={self.id} name={self.name!r} "
            f"description={self.description!r} public={self.bot_public} "
            f"owner={self.owner!r}>"
        )

    @property
    def icon(self) -> Optional[Asset]:
        """Optional[:class:`.Asset`]: Retrieves the application's icon asset, if any."""
        if self._icon is None:
            return None
        return Asset._from_icon(self._state, self.id, self._icon, path="app")

    @property
    def cover_image(self) -> Optional[Asset]:
        """Optional[:class:`.Asset`]: Retrieves the cover image on a store embed, if any.

        This is only available if the application is a game sold on Discord.
        """
        if self._cover_image is None:
            return None
        return Asset._from_cover_image(self._state, self.id, self._cover_image)

    @property
    def guild(self) -> Optional[Guild]:
        """Optional[:class:`Guild`]: The guild associated with the application, if any.

        .. versionadded:: 1.3
        """
        return self._state._get_guild(self.guild_id)

    @property
    def summary(self) -> str:
        """:class:`str`: If this application is a game sold on Discord,
        this field will be the summary field for the store page of its primary SKU.

        .. versionadded:: 1.3

        .. deprecated:: 2.5

            This field is deprecated by discord and is now always blank. Consider using :attr:`.description` instead.
        """
        utils.warn_deprecated(
            "summary is deprecated and will be removed in a future version. Consider using description instead.",
            stacklevel=2,
        )
        return self._summary

    @property
    def guild_install_type_config(self) -> Optional[InstallTypeConfiguration]:
        """Optional[:class:`InstallTypeConfiguration`]: The guild installation parameters for
        this application. If this application cannot be installed to guilds, returns ``None``.

        .. versionadded:: 2.10
        """
        return self._install_types_config.get(0)

    @property
    def user_install_type_config(self) -> Optional[InstallTypeConfiguration]:
        """Optional[:class:`InstallTypeConfiguration`]: The user installation parameters for
        this application. If this application cannot be installed to users, returns ``None``.

        .. versionadded:: 2.10
        """
        return self._install_types_config.get(1)


class PartialAppInfo:
    """Represents a partial AppInfo given by :func:`~disnake.abc.GuildChannel.create_invite`.

    .. versionadded:: 2.0

    Attributes
    ----------
    id: :class:`int`
        The application's ID.
    name: :class:`str`
        The application's name.
    description: :class:`str`
        The application's description.
    rpc_origins: Optional[List[:class:`str`]]
        A list of RPC origin URLs, if RPC is enabled.
    verify_key: :class:`str`
        The hex encoded key for verification in interactions and the
        GameSDK's :ddocs:`GetTicket <game-sdk/applications#getticket>`.
    terms_of_service_url: Optional[:class:`str`]
        The application's terms of service URL, if set.
    privacy_policy_url: Optional[:class:`str`]
        The application's privacy policy URL, if set.
    """

    __slots__ = (
        "_state",
        "id",
        "name",
        "description",
        "rpc_origins",
        "_summary",
        "verify_key",
        "terms_of_service_url",
        "privacy_policy_url",
        "_icon",
    )

    def __init__(self, *, state: ConnectionState, data: PartialAppInfoPayload) -> None:
        self._state: ConnectionState = state
        self.id: int = int(data["id"])
        self.name: str = data["name"]
        self._icon: Optional[str] = data.get("icon")
        self.description: str = data["description"]
        self.rpc_origins: Optional[List[str]] = data.get("rpc_origins")
        self._summary: str = data.get("summary", "")
        self.verify_key: str = data["verify_key"]
        self.terms_of_service_url: Optional[str] = data.get("terms_of_service_url")
        self.privacy_policy_url: Optional[str] = data.get("privacy_policy_url")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id} name={self.name!r} description={self.description!r}>"

    @property
    def icon(self) -> Optional[Asset]:
        """Optional[:class:`.Asset`]: Retrieves the application's icon asset, if any."""
        if self._icon is None:
            return None
        return Asset._from_icon(self._state, self.id, self._icon, path="app")

    @property
    def summary(self) -> str:
        """:class:`str`: If this application is a game sold on Discord,
        this field will be the summary field for the store page of its primary SKU.

        .. deprecated:: 2.5

            This field is deprecated by discord and is now always blank. Consider using :attr:`.description` instead.
        """
        utils.warn_deprecated(
            "summary is deprecated and will be removed in a future version. Consider using description instead.",
            stacklevel=2,
        )
        return self._summary
