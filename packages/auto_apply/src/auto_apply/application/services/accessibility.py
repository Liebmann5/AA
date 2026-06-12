"""Accessibility infrastructure for AutoApply.

This module ensures AA is usable by people with disabilities, including
visual impairments, motor disabilities, and cognitive differences. Every
UI component in both GUI and CLI consults this module for accessibility
configuration.

Supported Features:
    - Screen reader compatibility (ARIA-equivalent labels for all controls)
    - High contrast mode (configurable color themes)
    - Keyboard-only navigation (full tab order, shortcuts)
    - Font size scaling (independent of OS settings)
    - Reduced motion mode (disables animations)
    - RTL text direction (for Arabic, Hebrew, Farsi, Urdu)

Design Philosophy:
    Accessibility is not a feature — it is a requirement. AA targets
    worst-case users, which includes users with disabilities using
    assistive technology on library computers. Every UI element must
    be operable via keyboard alone and describable by a screen reader.

Example:
    >>> from auto_apply.application.services.accessibility import get_a11y_config
    >>> config = get_a11y_config()
    >>> config.high_contrast
    False
    >>> config.font_scale
    1.0
"""

# Layer: application
# Depends on: domain

import logging
from dataclasses import dataclass, field
from enum import Enum, auto

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Color Theme Definitions
# ─────────────────────────────────────────────────────────────────────────────

class ColorTheme(Enum):
    """Available color themes for the UI."""
    DEFAULT = auto()
    HIGH_CONTRAST_DARK = auto()
    HIGH_CONTRAST_LIGHT = auto()
    DEUTERANOPIA = auto()     # Red-green color blindness (most common)
    PROTANOPIA = auto()       # Red color blindness
    TRITANOPIA = auto()       # Blue-yellow color blindness


@dataclass(frozen=True)
class ThemeColors:
    """Immutable set of UI colors for a single theme.

    All colors are 6-character hex strings (no # prefix).

    Attributes:
        bg_primary: Main background color.
        bg_secondary: Secondary/card background color.
        bg_accent: Accent background (e.g., selected row).
        text_primary: Main text color.
        text_secondary: Muted/secondary text color.
        text_on_accent: Text color when placed on accent backgrounds.
        border: Default border color.
        success: Color for success states.
        warning: Color for warning states.
        error: Color for error states.
        link: Color for interactive links.
        focus_ring: Color for keyboard focus indicator.
    """
    bg_primary:     str = "FFFFFF"
    bg_secondary:   str = "F7FAFC"
    bg_accent:      str = "EBF8FF"
    text_primary:   str = "1A202C"
    text_secondary: str = "718096"
    text_on_accent: str = "FFFFFF"
    border:         str = "E2E8F0"
    success:        str = "38A169"
    warning:        str = "DD6B20"
    error:          str = "E53E3E"
    link:           str = "2B6CB0"
    focus_ring:     str = "4299E1"


THEMES: dict[ColorTheme, ThemeColors] = {
    ColorTheme.DEFAULT: ThemeColors(),

    ColorTheme.HIGH_CONTRAST_DARK: ThemeColors(
        bg_primary="000000", bg_secondary="1A1A1A", bg_accent="003366",
        text_primary="FFFFFF", text_secondary="CCCCCC", text_on_accent="FFFFFF",
        border="FFFFFF", success="00FF00", warning="FFFF00", error="FF0000",
        link="00CCFF", focus_ring="FFFF00",
    ),

    ColorTheme.HIGH_CONTRAST_LIGHT: ThemeColors(
        bg_primary="FFFFFF", bg_secondary="F0F0F0", bg_accent="FFFFCC",
        text_primary="000000", text_secondary="333333", text_on_accent="000000",
        border="000000", success="006600", warning="CC6600", error="CC0000",
        link="0000CC", focus_ring="0000FF",
    ),

    ColorTheme.DEUTERANOPIA: ThemeColors(
        bg_primary="FFFFFF", bg_secondary="F5F5F5", bg_accent="E3F2FD",
        text_primary="212121", text_secondary="757575", text_on_accent="FFFFFF",
        border="BDBDBD", success="1565C0", warning="F57F17", error="B71C1C",
        link="0D47A1", focus_ring="FF6F00",
    ),

    ColorTheme.PROTANOPIA: ThemeColors(
        bg_primary="FFFFFF", bg_secondary="F5F5F5", bg_accent="E3F2FD",
        text_primary="212121", text_secondary="757575", text_on_accent="FFFFFF",
        border="BDBDBD", success="0277BD", warning="FF8F00", error="AD1457",
        link="01579B", focus_ring="FF6F00",
    ),

    ColorTheme.TRITANOPIA: ThemeColors(
        bg_primary="FFFFFF", bg_secondary="F5F5F5", bg_accent="FCE4EC",
        text_primary="212121", text_secondary="757575", text_on_accent="FFFFFF",
        border="BDBDBD", success="2E7D32", warning="E65100", error="C62828",
        link="1B5E20", focus_ring="BF360C",
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Keyboard Shortcuts
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class KeyboardShortcut:
    """A single keyboard shortcut definition.

    Attributes:
        key: The key combination (e.g., "Ctrl+S", "F5", "Alt+P").
        action: The action identifier this shortcut triggers.
        description: Human-readable description for the shortcuts dialog.
    """
    key: str
    action: str
    description: str


DEFAULT_SHORTCUTS = [
    KeyboardShortcut("Ctrl+S",     "session.start",   "Start job hunt session"),
    KeyboardShortcut("Ctrl+P",     "session.pause",   "Pause/Resume session"),
    KeyboardShortcut("Ctrl+Q",     "session.stop",    "Stop session"),
    KeyboardShortcut("Ctrl+R",     "results.show",    "Show session results"),
    KeyboardShortcut("Ctrl+,",     "settings.open",   "Open settings"),
    KeyboardShortcut("Ctrl+N",     "profile.new",     "Create new profile"),
    KeyboardShortcut("Ctrl+O",     "profile.switch",  "Switch profile"),
    KeyboardShortcut("Ctrl+E",     "data.export",     "Export session data"),
    KeyboardShortcut("F1",         "help.show",       "Show help"),
    KeyboardShortcut("F5",         "session.refresh",  "Refresh dashboard"),
    KeyboardShortcut("Escape",     "dialog.close",    "Close current dialog"),
    KeyboardShortcut("Tab",        "focus.next",      "Move to next control"),
    KeyboardShortcut("Shift+Tab",  "focus.prev",      "Move to previous control"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Accessibility Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AccessibilityConfig:
    """The active accessibility configuration for this session.

    Set via user settings or auto-detected from OS accessibility features.
    All UI components read from this to determine rendering behavior.

    Attributes:
        color_theme: The active color theme.
        high_contrast: Whether high contrast mode is active.
        font_scale: Font size multiplier (1.0 = default, 1.5 = 150%).
        reduced_motion: If True, disable all animations and transitions.
        screen_reader_mode: If True, add extra ARIA labels and descriptions.
        focus_visible: If True, always show keyboard focus indicators.
        is_rtl: If True, mirror the UI layout for right-to-left text.
        keyboard_shortcuts: The active set of keyboard shortcuts.
    """
    color_theme:        ColorTheme = ColorTheme.DEFAULT
    high_contrast:      bool = False
    font_scale:         float = 1.0
    reduced_motion:     bool = False
    screen_reader_mode: bool = False
    focus_visible:      bool = True
    is_rtl:             bool = False
    keyboard_shortcuts: list = field(default_factory=lambda: list(DEFAULT_SHORTCUTS))

    @property
    def colors(self) -> ThemeColors:
        """Returns the color set for the active theme."""
        return THEMES.get(self.color_theme, THEMES[ColorTheme.DEFAULT])

    def scaled_font_size(self, base_size: int) -> int:
        """Returns a font size scaled by the user's font_scale setting.

        Args:
            base_size: The design-time font size in points.

        Returns:
            The scaled font size, minimum 8pt.
        """
        return max(8, round(base_size * self.font_scale))

    def to_dict(self) -> dict:
        """Serializes the config for persistence in user settings."""
        return {
            "color_theme": self.color_theme.name,
            "high_contrast": self.high_contrast,
            "font_scale": self.font_scale,
            "reduced_motion": self.reduced_motion,
            "screen_reader_mode": self.screen_reader_mode,
            "focus_visible": self.focus_visible,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AccessibilityConfig":
        """Restores config from a serialized dict."""
        config = cls()
        if "color_theme" in data:
            try:
                config.color_theme = ColorTheme[data["color_theme"]]
            except KeyError:
                pass
        config.high_contrast = data.get("high_contrast", False)
        config.font_scale = data.get("font_scale", 1.0)
        config.reduced_motion = data.get("reduced_motion", False)
        config.screen_reader_mode = data.get("screen_reader_mode", False)
        config.focus_visible = data.get("focus_visible", True)
        if config.high_contrast and config.color_theme == ColorTheme.DEFAULT:
            config.color_theme = ColorTheme.HIGH_CONTRAST_DARK
        return config


# ─────────────────────────────────────────────────────────────────────────────
# Module-Level Singleton
# ─────────────────────────────────────────────────────────────────────────────

_config = AccessibilityConfig()


def configure_accessibility(
    settings: dict | None = None,
    is_rtl: bool = False,
) -> None:
    """Configures accessibility for this session. Called once at startup.

    Args:
        settings: Dict from user profile's accessibility settings.
        is_rtl: Whether the active language is right-to-left.
    """
    global _config  # noqa: PLW0603
    if settings:
        _config = AccessibilityConfig.from_dict(settings)
    else:
        _config = AccessibilityConfig()
    _config.is_rtl = is_rtl
    logger.info(
        "Accessibility configured | theme=%s scale=%.1f rtl=%s",
        _config.color_theme.name, _config.font_scale, _config.is_rtl,
    )


def get_a11y_config() -> AccessibilityConfig:
    """Returns the active accessibility configuration."""
    return _config


def get_theme_colors() -> ThemeColors:
    """Returns the active theme's color set."""
    return _config.colors


def get_shortcuts() -> list:
    """Returns the active keyboard shortcuts list."""
    return _config.keyboard_shortcuts
