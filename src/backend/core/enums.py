"""
Core application enums declaration
"""

from django.conf import global_settings

# In Django's code base, `LANGUAGES` is set by default with all supported languages.
# We can use it for the choice of languages which should not be limited to the few languages
# active in the app.
# pylint: disable=no-member
ALL_LANGUAGES = dict(global_settings.LANGUAGES)
