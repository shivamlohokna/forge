"""Generate high-resolution application icons for Forge Desktop."""

import sys
from pathlib import Path
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)


def generate_forge_icon(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ico_path = output_dir / "forge.ico"
    png_path = output_dir / "forge.png"

    app = QGuiApplication.instance()
    if not app:
        app = QGuiApplication(sys.argv + ["-platform", "offscreen"])

    size = 256
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    # 1. Background rounded card with deep dark slate gradient
    bg_gradient = QLinearGradient(0, 0, size, size)
    bg_gradient.setColorAt(0.0, QColor("#1E1B4B"))  # Deep Indigo
    bg_gradient.setColorAt(0.5, QColor("#0F172A"))  # Slate dark
    bg_gradient.setColorAt(1.0, QColor("#020617"))  # Night black

    bg_path = QPainterPath()
    bg_path.addRoundedRect(QRectF(12, 12, 232, 232), 48, 48)

    painter.fillPath(bg_path, QBrush(bg_gradient))

    # Border glow
    border_pen = QPen(QColor("#6366F1"), 3.0)
    painter.strokePath(bg_path, border_pen)

    # 2. Forge Anvil / Core Platform Geometry
    # Lower anvil base
    base_gradient = QLinearGradient(0, 150, size, 220)
    base_gradient.setColorAt(0.0, QColor("#64748B"))
    base_gradient.setColorAt(1.0, QColor("#334155"))

    anvil_path = QPainterPath()
    anvil_path.moveTo(56, 175)
    anvil_path.lineTo(200, 175)
    anvil_path.lineTo(185, 145)
    anvil_path.lineTo(155, 140)
    anvil_path.lineTo(155, 120)
    anvil_path.lineTo(210, 120)  # Anvil horn right
    anvil_path.quadTo(215, 128, 205, 135)
    anvil_path.lineTo(155, 140)
    anvil_path.lineTo(101, 140)
    anvil_path.lineTo(45, 120)   # Anvil horn left
    anvil_path.quadTo(40, 128, 50, 135)
    anvil_path.lineTo(101, 140)
    anvil_path.lineTo(101, 145)
    anvil_path.lineTo(71, 145)
    anvil_path.closeSubpath()

    painter.fillPath(anvil_path, QBrush(base_gradient))
    painter.strokePath(anvil_path, QPen(QColor("#94A3B8"), 2.0))

    # 3. Blazing Forge Flame & Sparks (Orchestration Energy)
    flame_grad = QLinearGradient(128, 140, 128, 50)
    flame_grad.setColorAt(0.0, QColor("#F59E0B"))  # Amber
    flame_grad.setColorAt(0.5, QColor("#EF4444"))  # Red flame
    flame_grad.setColorAt(1.0, QColor("#FDE047"))  # Bright yellow spark

    flame_path = QPainterPath()
    flame_path.moveTo(128, 48)
    flame_path.cubicTo(165, 80, 175, 115, 155, 142)
    flame_path.cubicTo(145, 130, 140, 118, 132, 105)
    flame_path.cubicTo(125, 120, 120, 132, 101, 142)
    flame_path.cubicTo(81, 115, 91, 80, 128, 48)
    flame_path.closeSubpath()

    painter.fillPath(flame_path, QBrush(flame_grad))

    # Inner hot core
    inner_flame = QPainterPath()
    inner_flame.moveTo(128, 85)
    inner_flame.cubicTo(145, 105, 150, 125, 138, 140)
    inner_flame.cubicTo(133, 132, 130, 124, 128, 118)
    inner_flame.cubicTo(126, 124, 123, 132, 118, 140)
    inner_flame.cubicTo(106, 125, 111, 105, 128, 85)
    inner_flame.closeSubpath()

    painter.fillPath(inner_flame, QBrush(QColor("#FEF08A")))

    # 4. Modern Letter "F" Monogram on lower base
    painter.setFont(QFont("Arial", 22, QFont.Weight.Bold))
    painter.setPen(QColor("#F8FAFC"))
    painter.drawText(QRectF(12, 180, 232, 45), Qt.AlignmentFlag.AlignCenter, "FORGE")

    painter.end()

    # Save PNG and ICO
    img.save(str(png_path), "PNG")
    img.save(str(ico_path), "ICO")

    return ico_path, png_path


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "forge" / "resources" / "icons"
    ico, png = generate_forge_icon(target)
    print(f"Generated icons:\n  ICO: {ico}\n  PNG: {png}")
