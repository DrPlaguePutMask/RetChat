"""Application stylesheet (dark)."""

BG = "#0e1016"
PANEL = "#151821"
CARD = "#1b1f2b"
CARD_HI = "#232838"
BORDER = "#2a3042"
TEXT = "#e6e8ef"
MUTED = "#8b90a5"
ACCENT = "#7c5cff"
ACCENT_HI = "#9479ff"
GREEN = "#22c55e"
RED = "#ef4444"
AMBER = "#f59e0b"

STATUS_COLORS = {"live": GREEN, "connecting": AMBER, "error": RED, "stopped": "#4b5163"}

STYLE = f"""
* {{ font-family: 'Segoe UI', 'Vazirmatn', sans-serif; font-size: 13px; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QWidget#chatPane {{ background: {BG}; }}
QLabel#brand {{ font-size: 20px; font-weight: 700; color: {TEXT}; }}
QLabel#brandSub {{ color: {MUTED}; font-size: 11px; }}
QLabel#h2 {{ font-size: 14px; font-weight: 600; }}
QLabel#muted, QLabel[muted="true"] {{ color: {MUTED}; font-size: 12px; }}
QLabel#pill {{ background: {CARD_HI}; border: 1px solid {BORDER}; border-radius: 9px;
               padding: 2px 8px; font-size: 11px; color: {MUTED}; }}
QLabel#pillWarn {{ background: rgba(245,158,11,0.15); border: 1px solid {AMBER}; border-radius: 9px;
                   padding: 2px 8px; font-size: 11px; color: {AMBER}; }}
QLabel#pillOk {{ background: rgba(34,197,94,0.12); border: 1px solid {GREEN}; border-radius: 9px;
                 padding: 2px 8px; font-size: 11px; color: {GREEN}; }}
QLabel#keyChip {{ background: {CARD_HI}; border: 1px solid {BORDER}; border-bottom: 2px solid #3a4158;
                  border-radius: 6px; padding: 1px 7px; font-family: 'Consolas'; font-size: 12px; }}
QLabel#wordChip {{ font-weight: 600; font-size: 14px; }}
QLabel:disabled, QLabel#wordChip:disabled {{ color: #565c70; }}
QLabel#keyChip:disabled {{ color: #565c70; background: {CARD}; }}

QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#groupHead {{ background: {CARD_HI}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#groupHead[active="true"] {{ border-color: {ACCENT}; }}
QCheckBox#groupCheck {{ font-weight: 700; font-size: 14px; }}
QFrame#row {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#row:hover {{ border-color: #3a4158; }}
QFrame#row[selected="true"] {{ border-color: {ACCENT}; background: #1f2033; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QFontComboBox {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px;
    selection-background-color: {ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox#small {{ padding: 2px 8px; font-size: 12px; border-radius: 6px; min-height: 18px; }}
QComboBox::drop-down, QFontComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {BORDER};
    selection-background-color: {ACCENT}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button
    {{ width: 0; border: none; }}

QPushButton {{ background: {CARD_HI}; border: 1px solid {BORDER}; border-radius: 8px;
               padding: 7px 14px; font-weight: 500; }}
QPushButton:hover {{ background: #2b3145; border-color: #3a4158; }}
QPushButton:pressed {{ background: #20253a; }}
QPushButton:disabled {{ color: #565c70; background: {CARD}; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton#primary:hover {{ background: {ACCENT_HI}; }}
QPushButton#danger {{ color: #ff8a8a; }}
QPushButton#danger:hover {{ background: rgba(239,68,68,0.15); border-color: {RED}; }}
QPushButton#ghost {{ background: transparent; border: none; padding: 4px 6px; color: {MUTED}; }}
QPushButton#ghost:hover {{ color: {TEXT}; background: {CARD_HI}; }}
QPushButton#toggleOn {{ background: rgba(34,197,94,0.15); border-color: {GREEN}; color: {GREEN}; }}
QPushButton#iconBtn {{ padding: 0; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
                       font-size: 15px; }}
QPushButton#iconBtn[active="true"] {{ background: {ACCENT}; border-color: {ACCENT}; }}

QTabWidget::pane {{ border: none; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 14px; margin-right: 2px;
                border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #4b5163; border-radius: 4px;
                        background: {CARD}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT};
    }}

QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; height: 14px; margin: -5px 0;
                              border-radius: 7px; }}

QProgressBar {{ background: {CARD_HI}; border: none; border-radius: 4px; height: 8px;
                text-align: center; font-size: 10px; color: transparent; }}
QProgressBar::chunk {{ border-radius: 4px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                       stop:0 {ACCENT}, stop:1 #c084fc); }}
QProgressBar#big {{ height: 22px; border-radius: 8px; color: white; font-size: 12px;
                    font-weight: 600; background: rgba(20,22,32,0.75); }}
QProgressBar#big::chunk {{ border-radius: 8px; }}

QScrollArea {{ border: none; background: transparent; }}
QWidget#scrollInner {{ background: transparent; }}
QPushButton#adminBtn {{ background: rgba(245,158,11,0.12); border: 1px solid {AMBER}; color: {AMBER};
                        padding: 4px 10px; font-size: 12px; }}
QPushButton#adminBtn:hover {{ background: rgba(245,158,11,0.25); }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #343a50; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #454c66; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page
    {{ height: 0; background: none; }}
QScrollBar:horizontal {{ height: 0; }}

QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ border: none; padding: 0; }}
QListWidget::item:selected {{ background: transparent; }}
QToolTip {{ background: {CARD_HI}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 10px; margin-top: 14px; padding: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
"""


def checkbox_css() -> str:
    """Draw a white tick PNG once and point the checkbox indicator at it."""
    from pathlib import Path
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
    path = Path.home() / ".ret_chat_cache" / "check.png"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("white"), 4.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(8, 17), QPointF(14, 23), QPointF(24, 10)])
        p.end()
        pm.save(str(path))
        return "QCheckBox::indicator:checked { image: url(%s); }" % path.as_posix()
    except Exception:
        return ""
