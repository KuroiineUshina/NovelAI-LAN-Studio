from pathlib import Path

from PIL import Image


root = Path(__file__).resolve().parents[1]
source = root / "assets" / "app-icon.png"
destination = root / "assets" / "app-icon.ico"

with Image.open(source) as image:
    image.convert("RGBA").save(
        destination,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

print(destination)
