import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from uom_printer import __version__
from uom_printer.single_instance import INSTALL_MUTEX_NAME, SingleInstanceGuard


def test_release_version() -> None:
    assert __version__ == "1.2.56"


def test_windows_version_resource_matches_application_version() -> None:
    version_resource = Path(__file__).resolve().parents[1] / "windows" / "version_info.txt"
    text = version_resource.read_text(encoding="utf-8")
    assert "filevers=(1, 2, 56, 0)" in text
    assert "prodvers=(1, 2, 56, 0)" in text
    assert "StringStruct('FileVersion', '1.2.56.0')" in text
    assert "StringStruct('ProductVersion', '1.2.56')" in text


def test_second_instance_is_blocked_and_requests_activation(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    first = SingleInstanceGuard(tmp_path)
    activated: list[bool] = []
    first.activate_requested.connect(lambda: activated.append(True))
    assert first.acquire() is True

    second = SingleInstanceGuard(tmp_path)
    assert second.acquire() is False
    assert second.notified_existing_instance is True

    for _ in range(5):
        app.processEvents()
    assert activated
    first.close()


def test_windows_global_mutex_result_blocks_duplicate_even_if_lock_file_is_stale(tmp_path, monkeypatch) -> None:
    guard = SingleInstanceGuard(tmp_path)
    guard.install_mutex_already_exists = True
    monkeypatch.setattr(guard, "_notify_existing_instance", lambda: True)
    try:
        assert guard.acquire() is False
        assert guard.notified_existing_instance is True
    finally:
        guard.close()


def test_installer_is_chinese_and_desktop_shortcut_is_selected_by_default() -> None:
    installer = (Path(__file__).parents[1] / "windows" / "installer.iss").read_text(encoding="utf-8")
    assert 'Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"' in installer
    assert 'Name: "desktopicon"; Description: "创建桌面快捷方式"' in installer
    assert "UsePreviousTasks=no" in installer
    assert "Tasks: desktopicon" in installer
    assert "unchecked" not in installer


def test_installer_detects_the_running_application_before_installing() -> None:
    installer = (Path(__file__).parents[1] / "windows" / "installer.iss").read_text(encoding="utf-8")
    assert f'#define AppMutexName "{INSTALL_MUTEX_NAME}"' in installer
    assert "AppMutex={#AppMutexName}" in installer
    assert "CheckForMutexes('{#AppMutexName}')" in installer
    assert "IsProcessRunning('{#AppExeName}')" in installer
    assert "CloseApplications=no" in installer
    assert "请先在右下角托盘图标中选择“退出程序”" in installer
