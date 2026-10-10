"""Modern styling, theme tokens, and stylesheet definitions for Forge Desktop."""

from __future__ import annotations

# Color Palette Tokens
PRIMARY = "#6366F1"       # Indigo accent
PRIMARY_HOVER = "#4F46E5" # Deep indigo
PRIMARY_LIGHT = "#EEF2FF"
BACKGROUND_DARK = "#0F172A"  # Slate 900
SURFACE_DARK = "#1E293B"     # Slate 800
SURFACE_CARD = "#182234"     # Card background
SURFACE_HOVER = "#334155"    # Slate 700
BORDER_COLOR = "#334155"     # Border line
BORDER_LIGHT = "#475569"
TEXT_PRIMARY = "#F8FAFC"     # White high-contrast
TEXT_SECONDARY = "#94A3B8"   # Slate 400
TEXT_MUTED = "#64748B"       # Slate 500

SUCCESS = "#10B981"          # Emerald 500
SUCCESS_BG = "#064E3B"
WARNING = "#F59E0B"          # Amber 500
WARNING_BG = "#78350F"
DANGER = "#EF4444"           # Red 500
DANGER_HOVER = "#DC2626"
DANGER_BG = "#7F1D1D"
INFO = "#38BDF8"             # Sky 400
INFO_BG = "#0C4A6E"


MAIN_STYLESHEET = f"""
QMainWindow, QDialog {{
    background-color: {BACKGROUND_DARK};
    color: {TEXT_PRIMARY};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}}

QWidget {{
    color: {TEXT_PRIMARY};
}}

/* Top / Sidebar Navigation */
QFrame#sidebarFrame {{
    background-color: {SURFACE_DARK};
    border-right: 1px solid {BORDER_COLOR};
}}

QPushButton#navBtn {{
    background-color: transparent;
    color: {TEXT_SECONDARY};
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
}}

QPushButton#navBtn:hover {{
    background-color: {SURFACE_HOVER};
    color: {TEXT_PRIMARY};
}}

QPushButton#navBtn:checked {{
    background-color: {PRIMARY};
    color: #FFFFFF;
    font-weight: 600;
}}

/* Cards and Panels */
QFrame#cardFrame {{
    background-color: {SURFACE_CARD};
    border: 1px solid {BORDER_COLOR};
    border-radius: 10px;
    padding: 16px;
}}

QFrame#cardFrame:hover {{
    border: 1px solid {BORDER_LIGHT};
}}

/* Primary & Action Buttons */
QPushButton#primaryBtn {{
    background-color: {PRIMARY};
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}}

QPushButton#primaryBtn:hover {{
    background-color: {PRIMARY_HOVER};
}}

QPushButton#primaryBtn:disabled {{
    background-color: {SURFACE_HOVER};
    color: {TEXT_MUTED};
}}

QPushButton#secondaryBtn {{
    background-color: {SURFACE_DARK};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    padding: 7px 14px;
    font-size: 13px;
}}

QPushButton#secondaryBtn:hover {{
    background-color: {SURFACE_HOVER};
    border-color: {BORDER_LIGHT};
}}

QPushButton#dangerBtn {{
    background-color: {DANGER};
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 7px 14px;
    font-size: 13px;
    font-weight: 600;
}}

QPushButton#dangerBtn:hover {{
    background-color: {DANGER_HOVER};
}}

/* Form Controls & Inputs */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background-color: {SURFACE_DARK};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    selection-background-color: {PRIMARY};
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border: 1px solid {PRIMARY};
}}

QComboBox::drop-down {{
    border: none;
    padding-right: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: {SURFACE_DARK};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    selection-background-color: {PRIMARY};
}}

/* Tables and Tree Views */
QTableWidget, QTableView {{
    background-color: {SURFACE_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
    gridline-color: {BORDER_COLOR};
    selection-background-color: {SURFACE_HOVER};
    selection-color: {TEXT_PRIMARY};
}}

QHeaderView::section {{
    background-color: {SURFACE_DARK};
    color: {TEXT_SECONDARY};
    padding: 8px 12px;
    border: none;
    border-bottom: 1px solid {BORDER_COLOR};
    font-weight: 600;
    font-size: 12px;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background-color: {BACKGROUND_DARK};
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background-color: {SURFACE_HOVER};
    min-height: 20px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {BORDER_LIGHT};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

/* Tabs */
QTabWidget::pane {{
    border: 1px solid {BORDER_COLOR};
    background-color: {SURFACE_CARD};
    border-radius: 8px;
}}

QTabBar::tab {{
    background-color: {SURFACE_DARK};
    color: {TEXT_SECONDARY};
    padding: 8px 16px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}

QTabBar::tab:selected {{
    background-color: {SURFACE_CARD};
    color: {TEXT_PRIMARY};
    font-weight: 600;
}}

/* Status Badges */
QLabel#badgeSuccess {{
    background-color: {SUCCESS_BG};
    color: {SUCCESS};
    border-radius: 4px;
    padding: 2px 8px;
    font-weight: 600;
    font-size: 11px;
}}

QLabel#badgeFailed {{
    background-color: {DANGER_BG};
    color: {DANGER};
    border-radius: 4px;
    padding: 2px 8px;
    font-weight: 600;
    font-size: 11px;
}}

QLabel#badgeRunning {{
    background-color: {INFO_BG};
    color: {INFO};
    border-radius: 4px;
    padding: 2px 8px;
    font-weight: 600;
    font-size: 11px;
}}

QLabel#badgePending {{
    background-color: {SURFACE_HOVER};
    color: {TEXT_SECONDARY};
    border-radius: 4px;
    padding: 2px 8px;
    font-weight: 600;
    font-size: 11px;
}}
"""
