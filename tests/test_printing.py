import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from uom_printer import printing


def test_windows_create_dc_uses_pywin32_three_argument_signature(monkeypatch, tmp_path: Path) -> None:
    devmode = SimpleNamespace(Fields=0)
    calls: list[tuple] = []

    win32print = ModuleType("win32print")
    win32print.OpenPrinter = lambda _name: object()
    win32print.GetPrinter = lambda _handle, _level: {"pDevMode": devmode}
    win32print.ClosePrinter = lambda _handle: None

    win32gui = ModuleType("win32gui")

    def create_dc(*args):
        calls.append(args)
        raise RuntimeError("test stop")

    win32gui.CreateDC = create_dc
    image_win = ModuleType("PIL.ImageWin")

    monkeypatch.setattr(printing, "IS_WINDOWS", True)
    monkeypatch.setitem(sys.modules, "win32print", win32print)
    monkeypatch.setitem(sys.modules, "win32gui", win32gui)
    monkeypatch.setitem(sys.modules, "PIL.ImageWin", image_win)

    image_path = tmp_path / "label.png"
    from PIL import Image

    Image.new("RGB", (1417, 945), "white").save(image_path, dpi=(600, 600))
    with pytest.raises(printing.PrintingError, match="test stop"):
        printing.print_label(image_path, "Deli DL-720W")

    assert calls == [("WINSPOOL", "Deli DL-720W", devmode)]
    assert devmode.PaperWidth == 600
    assert devmode.PaperLength == 400
