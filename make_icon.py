"""Rasterize the editable vector master into Windows' native multi-size icon."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QImage,QPainter
from PySide6.QtCore import Qt
from PIL import Image
root=Path(__file__).parent
app=QApplication.instance() or QApplication([])
renderer=QSvgRenderer(str(root/'assets/app-icon.svg'))
if not renderer.isValid(): raise RuntimeError('Invalid SVG')
canvas=QImage(1024,1024,QImage.Format_ARGB32); canvas.fill(Qt.transparent)
p=QPainter(canvas); renderer.render(p); p.end()
canvas.save(str(root/'assets/app-icon.png'))
with Image.open(root/'assets/app-icon.png') as image:
    image.save(root/'assets/app-icon.ico',sizes=[(n,n) for n in (16,20,24,32,40,48,64,96,128,256)])
