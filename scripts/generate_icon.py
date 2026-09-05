from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def main() -> None:
    """Normalize the supplied app artwork and build the Windows multi-size icon."""
    ASSETS.mkdir(parents=True, exist_ok=True)
    png = ASSETS / "app-icon.png"
    ico = ASSETS / "app-icon.ico"
    if not png.exists():
        raise FileNotFoundError(f"缺少应用图标：{png}")
    image = Image.open(png).convert("RGBA").resize((1024, 1024), Image.Resampling.LANCZOS)
    image.save(png)
    image.save(
        ico,
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(png)
    print(ico)


if __name__ == "__main__":
    main()
