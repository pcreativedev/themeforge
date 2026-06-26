"""Genera assets/pcreative-studio.ico multi-resolución desde los PNG fuente.
Lo usa build-windows.yml (PowerShell no soporta heredocs bash, así que el
script va en un archivo real). Requiere Pillow."""
from PIL import Image

srcs = [
    "assets/pcreative-studio-16.png",
    "assets/pcreative-studio-32.png",
    "assets/pcreative-studio-64.png",
    "assets/pcreative-studio-128.png",
    "assets/pcreative-studio-256.png",
]
base = Image.open(srcs[-1])
base.save(
    "assets/pcreative-studio.ico",
    format="ICO",
    sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("generated assets/pcreative-studio.ico")
