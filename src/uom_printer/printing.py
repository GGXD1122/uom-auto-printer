from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

IS_WINDOWS = os.name == "nt"


class PrintingError(RuntimeError):
    pass


class DOCINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_int),
        ("lpszDocName", wintypes.LPCWSTR),
        ("lpszOutput", wintypes.LPCWSTR),
        ("lpszDatatype", wintypes.LPCWSTR),
        ("fwType", wintypes.DWORD),
    ]


def list_printers() -> list[str]:
    if not IS_WINDOWS:
        return []
    import win32print

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return sorted({item[2] for item in win32print.EnumPrinters(flags) if item[2]})


def print_label(image_path: Path, printer_name: str, copies: int = 1) -> None:
    if not IS_WINDOWS:
        raise PrintingError("实际打印仅在Windows系统上可用")
    if not printer_name:
        raise PrintingError("尚未选择打印机")

    import win32gui
    import win32print
    from PIL import Image, ImageOps, ImageWin

    handle = win32print.OpenPrinter(printer_name)
    try:
        info = win32print.GetPrinter(handle, 2)
        devmode = info["pDevMode"]
        if devmode is None:
            raise PrintingError("打印机驱动未返回纸张设置")
        devmode.PaperSize = 0
        image = Image.open(image_path)
        dpi_info = image.info.get("dpi", (600, 600))
        image_dpi = float(dpi_info[0] if isinstance(dpi_info, tuple) else dpi_info or 600)
        paper_width_mm = max(1.0, image.width / image_dpi * 25.4)
        paper_height_mm = max(1.0, image.height / image_dpi * 25.4)
        devmode.PaperWidth = round(paper_width_mm * 10)
        devmode.PaperLength = round(paper_height_mm * 10)
        devmode.Orientation = 1
        devmode.Copies = 1
        devmode.Fields |= 0x00000002 | 0x00000004 | 0x00000008 | 0x00000100

        hdc = int(win32gui.CreateDC("WINSPOOL", printer_name, devmode))
        gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]
        gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
        gdi32.GetDeviceCaps.restype = ctypes.c_int
        gdi32.StartDocW.argtypes = [wintypes.HDC, ctypes.POINTER(DOCINFOW)]
        gdi32.StartDocW.restype = ctypes.c_int
        gdi32.StartPage.argtypes = [wintypes.HDC]
        gdi32.StartPage.restype = ctypes.c_int
        gdi32.EndPage.argtypes = [wintypes.HDC]
        gdi32.EndPage.restype = ctypes.c_int
        gdi32.EndDoc.argtypes = [wintypes.HDC]
        gdi32.EndDoc.restype = ctypes.c_int
        gdi32.AbortDoc.argtypes = [wintypes.HDC]
        gdi32.AbortDoc.restype = ctypes.c_int
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        gdi32.DeleteDC.restype = wintypes.BOOL
        try:
            printable_width = gdi32.GetDeviceCaps(hdc, 8)  # HORZRES
            printable_height = gdi32.GetDeviceCaps(hdc, 10)  # VERTRES
            if printable_width <= 0 or printable_height <= 0:
                raise PrintingError("打印机驱动未返回有效可打印区域")
            image = image.convert("RGB")
            image = ImageOps.grayscale(image).convert("RGB")
            dib = ImageWin.Dib(image)
            for _ in range(max(1, copies)):
                docinfo = DOCINFOW(ctypes.sizeof(DOCINFOW), "UOM实名登记标识", None, None, 0)
                if gdi32.StartDocW(hdc, ctypes.byref(docinfo)) <= 0:
                    raise PrintingError("Windows无法创建打印任务")
                try:
                    if gdi32.StartPage(hdc) <= 0:
                        raise PrintingError("Windows无法启动标签页")
                    dib.draw(hdc, (0, 0, printable_width, printable_height))
                    if gdi32.EndPage(hdc) <= 0:
                        raise PrintingError("Windows无法完成标签页")
                    if gdi32.EndDoc(hdc) <= 0:
                        raise PrintingError("Windows无法提交打印任务")
                except Exception:
                    gdi32.AbortDoc(hdc)
                    raise
        finally:
            gdi32.DeleteDC(hdc)
    except PrintingError:
        raise
    except Exception as exc:
        raise PrintingError(f"提交Windows打印队列失败：{exc}") from exc
    finally:
        win32print.ClosePrinter(handle)
