"""Deploy Center Core application"""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CoreConfig(AppConfig):
    """Configuration class for the deploy center core app."""

    name = "core"
    app_label = "core"
    verbose_name = _("deploy center core application")

    def ready(self):
        """Register signal handlers when the app is ready."""
        # Import signal handlers to register them

        # pylint: disable=unused-import, import-outside-toplevel
        import core.signals  # noqa
