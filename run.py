import os


def _configure_rendering_environment() -> None:
    if os.name != "nt":
        return

    running_under_wine = bool(
        os.environ.get("WINEPREFIX")
        or os.environ.get("WINELOADER")
        or os.environ.get("WINECONFIGDIR")
    )
    remote_desktop = os.environ.get("SESSIONNAME", "").upper().startswith("RDP-")
    force_software = os.environ.get("UOM_FORCE_SOFTWARE_RENDERING") == "1"
    if not (running_under_wine or remote_desktop or force_software):
        return

    os.environ["UOM_SOFTWARE_RENDERING"] = "1"
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    chromium_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    for flag in ("--disable-gpu", "--disable-gpu-compositing"):
        if flag not in chromium_flags:
            chromium_flags = f"{chromium_flags} {flag}".strip()
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = chromium_flags

    if running_under_wine:
        # Qt WebEngine's compositor cannot reliably import its graphics surface
        # through Wine on macOS. Keep the rest of the application usable for
        # compatibility testing; genuine Windows keeps the embedded UOM page.
        os.environ.setdefault("UOM_WINE_COMPAT", "1")
        os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")


_configure_rendering_environment()


from uom_printer.app import main


if __name__ == "__main__":
    raise SystemExit(main())
