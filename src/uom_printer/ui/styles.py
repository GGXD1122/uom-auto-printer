APP_STYLE = """
QWidget {
    color: #182230;
    font-family: "Microsoft YaHei UI", "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}
QMainWindow { background: #f4f6f8; }
QDialog {
    background: #f4f6f8;
    border: 1px solid #dfe5ed;
    border-radius: 16px;
}
QDialog#LayoutEditorDialog { background: #f5f7fb; }
QWidget#LayoutEditorPage { background: #f5f7fb; }
QStackedWidget#MainPageStack { background: #f4f6f8; border: 0; }
QFrame#LayoutHeader, QFrame#PaperPresetPanel, QFrame#LayoutCanvasPanel {
    background: #ffffff;
    border: 1px solid #dfe5ed;
    border-radius: 14px;
}
QLabel#LayoutEditorTitle { color: #17233a; font-size: 20px; font-weight: 750; }
QPushButton#LayoutBackButton {
    min-width: 76px; min-height: 38px; border: 1px solid #d7e0eb;
    border-radius: 10px; background: #f8fafc; color: #344054;
    font-weight: 700; padding: 0 12px;
}
QPushButton#LayoutBackButton:hover { background: #eef3fb; border-color: #b9c8dd; }
QPushButton#LayoutBackButton:pressed { background: #e3ebf7; padding-top: 1px; }
QLabel#LayoutFieldLabel { color: #526173; font-size: 11px; font-weight: 650; }
QLabel#LayoutPresetFeedback {
    min-height: 28px; max-height: 28px; max-width: 300px;
    border-radius: 8px; padding: 0 9px;
    color: #315a46; background: #edf9f2; border: 1px solid #b9e5ca;
    font-size: 11px; font-weight: 650;
}
QLabel#LayoutPresetFeedback[state="working"] { color: #3157c8; background: #eef3ff; border-color: #c7d4fb; }
QLabel#LayoutPresetFeedback[state="info"] { color: #526173; background: #f4f6f8; border-color: #dce3eb; }
QLabel#LayoutPresetFeedback[state="error"] { color: #b42318; background: #fff1f0; border-color: #f3b7b2; }
QLabel#LayoutInlineFeedback { color: #7a8797; font-size: 10px; min-height: 16px; }
QLabel#LayoutInlineFeedback[state="success"] { color: #18845a; font-weight: 650; }
QLabel#LayoutInlineFeedback[state="warning"] { color: #b54708; font-weight: 650; }
QLabel#LayoutInlineFeedback[state="error"] { color: #b42318; font-weight: 650; }
QLabel#LayoutActionFeedback {
    min-height: 18px;
    color: #18845a;
    background: transparent;
    border: 0;
    font-size: 10px;
    font-weight: 650;
}
QLabel#LayoutActionFeedback[state="info"] { color: #667085; }
QLabel#LayoutActionFeedback[state="error"] { color: #b42318; }
QFrame#LayoutCustomSize, QFrame#LayoutCustomSizeBar, QFrame#LayoutSelectionCard, QFrame#LayoutNameCard {
    background: #f8faff;
    border: 1px solid #dfe7f3;
    border-radius: 11px;
}
QFrame#LayoutKindSwitch { background: #eef2f7; border: 1px solid #dce4ee; border-radius: 11px; }
QPushButton#LayoutKindButton {
    min-height: 34px; border: 0; border-bottom: 0; border-radius: 8px;
    background: transparent; color: #718096; padding: 0 12px;
}
QPushButton#LayoutKindButton:checked {
    color: #2e5ee8; background: #ffffff; border: 1px solid #aec2ff; font-weight: 750;
}
QLabel#LayoutSelectedTitle { color: #17233a; font-size: 13px; font-weight: 750; }
QScrollArea#LayoutInspectorScroll, QScrollArea#LayoutInspectorScroll > QWidget > QWidget { background: transparent; border: 0; }
QSplitter#LayoutColumns::handle { width: 10px; background: transparent; }
QListWidget#PaperPresetList { background: transparent; border: 0; outline: 0; padding: 0; }
QListWidget#PaperPresetList::item { min-height: 58px; border: 0; padding: 0; }
QListWidget#PaperPresetList::item:selected { background: transparent; }
QGraphicsView#LayoutCanvas {
    background: #e9eef5;
    border: 1px solid #dbe3ed;
    border-radius: 14px;
}
QWidget#LayoutInspector {
    background: #ffffff;
    border: 1px solid #dfe5ed;
    border-radius: 14px;
}
QFrame#LayoutInspector { background: #ffffff; border: 1px solid #dfe5ed; border-radius: 14px; }
QListWidget#LayoutElementList {
    color: #253044;
    background: #fbfcfe;
    border: 1px solid #d9e1eb;
    border-radius: 10px;
    padding: 5px;
    outline: 0;
}
QListWidget#LayoutElementList::item { min-height: 28px; border-radius: 7px; padding: 2px 8px; }
QListWidget#LayoutElementList::item:selected { color: #2548a8; background: #eaf1ff; }
QListWidget#NamedPresetPopup {
    color: #253044; background: transparent; border: 0; outline: 0; padding: 3px;
}
QListWidget#NamedPresetPopup::item {
    min-height: 32px; border-radius: 7px; padding: 0 10px;
}
QListWidget#NamedPresetPopup::item:hover { background: #f1f5fb; }
QListWidget#NamedPresetPopup::item:selected { color: #2548a8; background: #eaf1ff; }
QFrame#LayoutQuickControls, QFrame#LayoutAdvancedPanel {
    background: #f8faff;
    border: 1px solid #dfe7f3;
    border-radius: 11px;
}
QPushButton#LayoutQuickButton {
    min-height: 30px;
    max-height: 32px;
    border: 1px solid #ced8e5;
    border-bottom: 2px solid #b8c5d5;
    border-radius: 8px;
    padding: 0 9px 1px 9px;
    background: #ffffff;
    color: #3157c8;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#LayoutQuickButton:hover { background: #edf3ff; border-color: #a8bced; }
QPushButton#LayoutQuickButton:pressed { background: #dfe9ff; border-bottom-width: 1px; padding-top: 1px; }
QPushButton#LayoutQuickButton:disabled {
    color: #98a2b3;
    background: #f2f4f7;
    border-color: #e1e6ed;
    border-bottom-color: #d0d5dd;
}
QPushButton#LayoutPresetButton {
    min-height: 36px;
    border-bottom-width: 1px;
    background: #f7f9fc;
    color: #344054;
}
QPushButton#LayoutDangerButton {
    min-height: 34px; padding: 0 12px; border-radius: 9px;
    color: #b42318; background: #fff7f6; border: 1px solid #fecdca;
}
QPushButton#LayoutDangerButton:hover { background: #fff0ee; border-color: #fda29b; }
QPushButton#LayoutDangerButton:pressed { background: #fee4e2; }
QPushButton#LayoutDangerButton:disabled { color: #98a2b3; background: #f2f4f7; border-color: #e4e7ec; }
QPushButton#LayoutGridButton {
    min-height: 36px; min-width: 62px; border-radius: 9px;
    background: #f7f9fc; color: #526173; border: 1px solid #d7e0eb;
    font-weight: 650; padding: 0 10px;
}
QPushButton#LayoutGridButton:hover { background: #eef3fb; border-color: #b9c8dd; }
QPushButton#LayoutGridButton:checked { color: #2456d8; background: #eaf1ff; border-color: #9fb7fb; }
QPushButton#LayoutAdvancedToggle {
    min-height: 34px;
    border: 0;
    border-bottom: 0;
    background: transparent;
    color: #526173;
    text-align: left;
    padding: 0 8px;
}
QPushButton#LayoutAdvancedToggle:hover { background: #f2f5f9; border: 0; }
QDoubleSpinBox {
    min-height: 36px;
    color: #253044;
    background: #ffffff;
    border: 1px solid #cfd8e3;
    border-radius: 9px;
    padding: 0 8px;
}
QDoubleSpinBox:focus { border: 2px solid #6b8cff; padding-left: 7px; }
QDoubleSpinBox[invalid="true"] { color: #b42318; background: #fff7f6; border: 2px solid #e37870; padding-left: 7px; }

QFrame#Header {
    background: #ffffff;
    border-bottom: 1px solid #e6eaf0;
    border-bottom-left-radius: 14px;
    border-bottom-right-radius: 14px;
}
QFrame#PreviewToolbar, QFrame#SidebarPaperToolbar {
    background: #ffffff;
    border: 1px solid #dfe5ed;
    border-radius: 14px;
}
QLabel#PreviewPrinter {
    color: #526173; background: #f5f7fa; border: 1px solid #e1e6ed;
    border-radius: 9px; padding: 5px 10px; font-size: 11px;
}
QFrame#Card {
    background: #ffffff;
    border: 1px solid #e3e8ef;
    border-radius: 16px;
}
QFrame#SidebarCard, QFrame#LookupDropCard, QFrame#RegistrationCard, QFrame#WebCard {
    background: #ffffff;
    border: 1px solid #dfe6ef;
    border-radius: 14px;
}
QFrame#SidebarCard, QFrame#LookupDropCard, QFrame#RegistrationCard { background: #ffffff; }
QFrame#LookupDropCard[dropActive="true"] {
    background: #f3f7ff;
    border: 2px solid #5f7fe8;
}
QFrame#LookupDropCard[dropActive="true"] QLabel#SectionTitle { color: #2548a8; }
QFrame#SidebarDropOverlay {
    background: rgba(15, 23, 42, 42);
    border: 2px solid #53c995;
    border-radius: 15px;
}
QFrame#SidebarDropPrompt {
    background: rgba(255, 255, 255, 238);
    border: 1px solid #a7e8c9;
    border-radius: 14px;
}
QLabel#SidebarDropTitle {
    color: #116149;
    background: transparent;
    font-size: 18px;
    font-weight: 750;
}
QLabel#SidebarDropDetail {
    color: #667085;
    background: transparent;
    font-size: 11px;
    font-weight: 600;
}
QFrame#WebCard[fullscreen="true"] {
    border: 0;
    border-radius: 0;
}
QFrame#WebToolbar {
    background: #ffffff;
    border-bottom: 1px solid #e7ebf1;
    border-top-left-radius: 14px;
    border-top-right-radius: 14px;
}
QFrame#WebCard[fullscreen="true"] QFrame#WebToolbar {
    border-top-left-radius: 0;
    border-top-right-radius: 0;
}
QProgressBar#WebLoadProgress {
    border: 0;
    border-radius: 2px;
    background: #e9eef5;
    padding: 0;
    margin: 0;
}
QProgressBar#WebLoadProgress::chunk {
    border: 0;
    border-radius: 2px;
    background: #3563e9;
}
QScrollArea#SidebarScroll, QScrollArea#SidebarScroll > QWidget > QWidget,
QWidget#SidebarContent, QWidget#SidebarPage, QStackedWidget#SidebarPages {
    background: transparent;
    border: 0;
}
QFrame#SidebarModeSwitch {
    background: #e9eef5;
    border: 1px solid #dbe3ed;
    border-radius: 12px;
}
QFrame#LoginHeader, QWidget#SoftPanel {
    background: #f8faff;
    border: 1px solid #dfe7f5;
    border-radius: 12px;
}
QFrame#WineCompatPanel {
    background: #f8faff;
    border: 1px solid #dfe7f5;
    border-bottom-left-radius: 14px;
    border-bottom-right-radius: 14px;
}
QLabel#WineCompatTitle { color: #1d2939; font-size: 24px; font-weight: 700; }
QLabel#WineCompatDetail { color: #526173; font-size: 14px; }

QLabel#Title {
    color: #101828;
    font-size: 20px;
    font-weight: 700;
}
QLabel#BubbleTitle {
    color: #101828;
    font-size: 17px;
    font-weight: 750;
}
QLabel#BubbleSubtitle { color: #667085; font-size: 11px; }
QLabel#AvatarName { color: #465568; font-size: 8pt; font-weight: 650; }
QLabel#FloatAvatarName { color: #465568; font-size: 8pt; font-weight: 650; }
QLabel#FloatBubbleTitle { color: #172033; font-size: 9pt; font-weight: 700; }
QLabel#FloatBubbleSubtitle { color: #526173; font-size: 8pt; }
QLabel#FloatBubbleTitle[state="working"] { color: #2548a8; }
QLabel#FloatBubbleTitle[state="success"] { color: #067647; }
QLabel#FloatBubbleTitle[state="warning"] { color: #b54708; }
QLabel#FloatBubbleTitle[state="error"] { color: #b42318; }
QLabel#BubbleTitle[state="working"] { color: #2548a8; }
QLabel#BubbleTitle[state="success"] { color: #067647; }
QLabel#BubbleTitle[state="warning"] { color: #b54708; }
QLabel#BubbleTitle[state="error"] { color: #b42318; }
QLabel#DialogTitle {
    color: #101828;
    font-size: 17px;
    font-weight: 700;
}
QLabel#Subtitle { color: #667085; font-size: 12px; }
QLabel#SectionTitle { color: #1d2939; font-size: 15px; font-weight: 650; }
QLabel#MetaLabel { color: #8a94a6; font-size: 11px; }
QLabel#MetaValue { color: #182230; font-weight: 650; }
QLabel#CopySummary {
    color: #3157c8;
    background: #f2f6ff;
    border: 1px solid #dbe6ff;
    border-radius: 8px;
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 650;
}
QLabel#StatusDetail { color: #526173; font-size: 12px; }
QLabel#LookupState {
    color: #667085;
    background: #f7f9fc;
    border: 1px solid #e5eaf1;
    border-radius: 9px;
    padding: 8px 10px;
    font-size: 11px;
}
QLabel#LookupState[state="working"] { color: #3157c8; background: #edf3ff; border-color: #c7d7fe; }
QLabel#LookupState[state="success"] { color: #067647; background: #ecfdf3; border-color: #abefc6; }
QLabel#LookupState[state="warning"] { color: #b54708; background: #fffaeb; border-color: #fedf89; }
QLabel#LookupState[state="error"] { color: #b42318; background: #fff1f0; border-color: #fda29b; }
QLabel#RegistrationState {
    color: #667085;
    background: #f7f9fc;
    border: 1px solid #e5eaf1;
    border-radius: 9px;
    padding: 8px 10px;
    font-size: 11px;
}
QLabel#RegistrationState[state="working"] { color: #3157c8; background: #edf3ff; border-color: #c7d7fe; }
QLabel#RegistrationState[state="success"] { color: #067647; background: #ecfdf3; border-color: #abefc6; }
QLabel#RegistrationState[state="warning"] { color: #b54708; background: #fffaeb; border-color: #fedf89; }
QLabel#RegistrationState[state="error"] { color: #b42318; background: #fff1f0; border-color: #fda29b; }
QLabel#RegistrationPhotoState {
    color: #7a8797;
    background: #f8fafc;
    border: 1px solid #e6ebf2;
    border-radius: 8px;
    padding: 6px 7px;
    font-size: 10px;
}
QFrame#PhotoDropTile {
    background: #f8fafc;
    border: 1px dashed #bfcbd9;
    border-radius: 14px;
}
QFrame#PhotoDropTile:hover {
    background: #f3f7ff;
    border: 1px solid #9cb3ef;
}
QFrame#PhotoDropTile[dropActive="true"] {
    background: #ecfdf3;
    border: 2px solid #36b37e;
}
QFrame#PhotoDropTile[selected="true"] {
    background: #f0fdf5;
    border: 1px solid #75d9a7;
}
QLabel#PhotoDropPreview {
    color: #4566c7;
    background: #eaf0ff;
    border: 1px solid #cad8ff;
    border-radius: 9px;
    font-size: 24px;
    font-weight: 500;
}
QLabel#PhotoDropPreview[hasPreview="true"] {
    background: #e8edf3;
    border-color: #c6d1dc;
}
QFrame#PhotoDropTile[dropActive="true"] QLabel#PhotoDropPreview {
    color: #067647;
    background: #dcfae6;
    border-color: #75d9a7;
}
QLabel#PhotoDropTitle { color: #253044; font-size: 12px; font-weight: 700; }
QLabel#PhotoDropDetail { color: #7a8797; font-size: 9px; }
QFrame#PhotoDropTile[dropActive="true"] QLabel#PhotoDropDetail { color: #067647; font-weight: 700; }
QLabel#RegistrationFaceQr {
    color: #667085;
    background: #f7f9fc;
    border: 1px dashed #c7d2df;
    border-radius: 12px;
    padding: 6px;
    font-size: 11px;
    font-weight: 650;
}
QLabel#RegistrationSummary {
    color: #465568;
    background: #f8faff;
    border: 1px solid #dfe7f5;
    border-radius: 10px;
    padding: 9px 10px;
    font-size: 10px;
}
QFrame#DjiVerificationBar {
    background: #f7f9ff;
    border-top: 0;
    border-bottom: 1px solid #dfe7f5;
}
QFrame#DjiSidebarOverlay {
    background: #ffffff;
    border: 1px solid #d8e1ef;
    border-radius: 14px;
}
QLabel#DjiVerificationTitle {
    color: #182230;
    background: transparent;
    border: 0;
    font-size: 13px;
    font-weight: 750;
}
QProgressBar#DjiSidebarProgress {
    background: #edf1f8;
    border: 0;
    border-radius: 0;
}
QProgressBar#DjiSidebarProgress::chunk { background: #3157c8; }
QLabel#DjiVerificationBadge {
    color: #ffffff;
    background: #3157c8;
    border: 0;
    border-radius: 7px;
    font-size: 10px;
    font-weight: 800;
}
QLabel#DjiVerificationInlineStatus {
    color: #3157c8;
    background: transparent;
    border: 0;
    font-size: 11px;
    font-weight: 650;
}
QLabel#DjiVerificationInlineStatus[state="success"] { color: #067647; }
QLabel#DjiVerificationInlineStatus[state="warning"] { color: #b54708; }
QLabel#DjiVerificationInlineStatus[state="error"] { color: #b42318; }
QPushButton#DjiVerificationCancel {
    color: #526173;
    background: #ffffff;
    border: 1px solid #d5ddea;
    border-radius: 9px;
    padding: 6px 11px;
    font-size: 11px;
    font-weight: 650;
}
QPushButton#DjiVerificationCancel:hover { color: #2548a8; background: #edf3ff; border-color: #b9c8ef; }
QLabel#LookupCaption { color: #7a8699; font-size: 11px; min-width: 58px; }
QLabel#LookupValue { color: #182230; font-size: 12px; font-weight: 650; }
QFrame#LookupOwnedActions {
    background: #f4f7fb;
    border: 1px solid #dbe3ed;
    border-radius: 10px;
}
QPushButton#LookupPrint, QPushButton#LookupCancel, QPushButton#LookupCopy {
    min-height: 30px;
    max-height: 30px;
    padding: 0 10px;
    border-radius: 8px;
    border-bottom-width: 1px;
    font-size: 11px;
    font-weight: 700;
}
QPushButton#LookupPrint {
    color: #ffffff;
    background: #3157c8;
    border-color: #3157c8;
}
QPushButton#LookupPrint:hover { background: #2449b6; border-color: #2449b6; }
QPushButton#LookupCancel {
    color: #b42318;
    background: #fff7f6;
    border-color: #f7b4ae;
}
QPushButton#LookupCancel:hover { background: #fff0ee; border-color: #ef8f86; }
QPushButton#LookupCopy {
    color: #344054;
    background: #f8fafc;
    border-color: #d6dee8;
}
QPushButton#LookupCopy:hover { color: #3157c8; background: #eef3ff; border-color: #b8c8f3; }
QPushButton#LookupPrint:pressed, QPushButton#LookupCancel:pressed, QPushButton#LookupCopy:pressed { padding-top: 1px; }
QPushButton#LookupCopy:disabled { color: #98a2b3; background: #f2f4f7; border-color: #e1e6ed; }
QLabel#ProductImage {
    color: #7b8798;
    background: #f3f6fa;
    border: 1px dashed #c8d2df;
    border-radius: 12px;
}
QLabel#ProductTitle { color: #101828; font-size: 15px; font-weight: 700; }
QLabel#ProductSummary { color: #526173; font-size: 11px; }
QLabel#ModelCatalogStatus {
    color: #667085;
    background: #f7f9fc;
    border: 1px solid #e3e8ef;
    border-radius: 8px;
    padding: 6px 8px;
    font-size: 10px;
}
QLabel#ModelCatalogStatus[state="ready"] { color: #067647; background: #ecfdf3; border-color: #abefc6; }
QLabel#ModelCatalogStatus[state="working"] { color: #3157c8; background: #edf3ff; border-color: #c7d7fe; }
QLabel#ModelCatalogStatus[state="error"] { color: #b42318; background: #fff1f0; border-color: #fda29b; }
QPushButton#ModelCatalogUpdate {
    min-width: 58px; max-width: 58px; min-height: 30px; max-height: 30px;
    color: #3157c8; background: #f3f6ff; border: 1px solid #c7d4fb;
    border-radius: 8px; padding: 0; font-size: 11px; font-weight: 700;
}
QPushButton#ModelCatalogUpdate:hover { background: #e8efff; border-color: #9eb3ef; }
QPushButton#ModelCatalogUpdate:pressed { background: #dfe8ff; padding-top: 1px; }
QPushButton#ModelCatalogUpdate:disabled { color: #98a2b3; background: #f2f4f7; border-color: #e1e6ed; }
QFrame#ModelCandidateList {
    background: #f7f9ff;
    border: 1px solid #d8e2fb;
    border-radius: 11px;
}
QLabel#ModelCandidateHint {
    color: #40516a;
    font-size: 11px;
    font-weight: 650;
    border: 0;
    background: transparent;
}
QLineEdit#ModelCandidateSearch {
    min-height: 34px;
    border-radius: 8px;
    background: #ffffff;
    border: 1px solid #cfdaea;
    padding: 0 9px;
    font-size: 11px;
}
QFrame#ModelCandidateOptionCard {
    background: #ffffff;
    border: 1px solid #dce4f0;
    border-radius: 9px;
}
QFrame#ModelCandidateOptionCard:hover {
    background: #f4f7ff;
    border-color: #9db4f2;
}
QFrame#ModelCandidateOptionCard[selected="true"] {
    background: #edf3ff;
    border-color: #6f8fe8;
}
QRadioButton#ModelCandidateOption {
    min-height: 24px;
    color: #253044;
    background: transparent;
    border: 0;
    padding: 0;
    font-size: 12px;
    font-weight: 700;
}
QRadioButton#ModelCandidateOption:checked {
    color: #2149b8;
}
QRadioButton#ModelCandidateOption::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #98a2b3;
    border-radius: 8px;
    background: #ffffff;
}
QRadioButton#ModelCandidateOption::indicator:hover {
    border-color: #607ed1;
}
QRadioButton#ModelCandidateOption::indicator:checked {
    border: 1px solid #3563e9;
    background: #3563e9;
}
QLabel#ModelCandidateMeta {
    color: #667085;
    background: transparent;
    border: 0;
    padding-left: 24px;
    font-size: 12px;
}
QLabel#ModelCandidateCode {
    color: #344054;
    background: transparent;
    border: 0;
    padding-left: 24px;
    font-size: 11px;
    font-weight: 650;
}
QPushButton#ModelCandidateConfirm {
    min-width: 104px;
    min-height: 40px;
    max-width: 104px;
    color: #ffffff;
    background: #2f62e9;
    border: 1px solid #2f62e9;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 750;
}
QPushButton#ModelCandidateConfirm:hover { background: #2556d4; border-color: #2556d4; }
QPushButton#ModelCandidateConfirm:pressed { background: #1f49b8; padding-top: 1px; }
QPushButton#ModelCandidateConfirm:disabled {
    color: #98a2b3;
    background: #eef1f5;
    border-color: #dfe4ea;
}
QLabel#VersionChip {
    color: #526173;
    background: #f1f4f8;
    border: 1px solid #e2e7ee;
    border-radius: 10px;
    padding: 3px 8px;
    font-size: 10px;
    font-weight: 700;
}
QLabel#ModeChip {
    color: #3157c8;
    background: #edf3ff;
    border: 1px solid #d6e2ff;
    border-radius: 10px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 650;
}
QLabel#StatusChip {
    border-radius: 11px;
    padding: 4px 11px;
    font-size: 11px;
    font-weight: 650;
}
QLabel#StatusChip[state="idle"] {
    color: #667085;
    background: #f2f4f7;
    border: 1px solid #e4e7ec;
}
QLabel#StatusChip[state="success"] {
    color: #067647;
    background: #ecfdf3;
    border: 1px solid #abefc6;
}
QLabel#StatusChip[state="warning"] {
    color: #b54708;
    background: #fffaeb;
    border: 1px solid #fedf89;
}
QLabel#DjiLoginStatus {
    min-height: 27px;
    max-height: 29px;
    padding: 0 10px;
    border-radius: 10px;
    color: #667085;
    background: #f2f4f7;
    border: 1px solid #e4e7ec;
    border-bottom-width: 1px;
    font-size: 11px;
    font-weight: 650;
}
QLabel#DjiLoginStatus[loggedIn="true"] {
    color: #067647;
    background: #ecfdf3;
    border-color: #abefc6;
}
QPushButton#DjiOpenButton {
    min-height: 27px;
    max-height: 29px;
    padding: 0 10px 1px 10px;
    border-radius: 8px;
    color: #3157d5;
    background: #f7f9ff;
    border: 1px solid #d8e3ff;
    border-bottom: 2px solid #b9caff;
    font-size: 11px;
    font-weight: 650;
}
QPushButton#DjiOpenButton:hover { background: #edf3ff; border-color: #b9caff; }
QPushButton#DjiOpenButton:pressed, QPushButton#DjiOpenButton[feedback="clicked"] {
    border-bottom-width: 1px;
    padding-top: 1px;
    padding-bottom: 0;
}
QLabel#InfoNote {
    color: #465568;
    background: #f7f9fc;
    border: 1px solid #e6ebf2;
    border-radius: 10px;
    padding: 12px;
}

QPushButton {
    min-height: 34px;
    border-radius: 10px;
    padding: 0 15px 2px 15px;
    border: 1px solid #d5dce5;
    border-bottom: 3px solid #c2ccd8;
    background: #ffffff;
    color: #344054;
    font-weight: 600;
}
QPushButton:hover {
    background: #fbfcfe;
    border-color: #aebccc;
    border-bottom-color: #96a7ba;
    color: #1d2939;
}
QPushButton:pressed, QPushButton[feedback="clicked"] {
    background: #edf2f7;
    border-bottom-width: 1px;
    padding-top: 2px;
    padding-bottom: 0;
}
QPushButton[feedback="success"] {
    color: #067647;
    background: #ecfdf3;
    border-color: #75e0a7;
    border-bottom-color: #17b26a;
}
QPushButton[feedback="error"] {
    color: #b42318;
    background: #fff1f0;
    border-color: #fda29b;
    border-bottom-color: #f04438;
}
QPushButton:disabled {
    color: #98a2b3;
    background: #f2f4f7;
    border-color: #eaecf0;
    border-bottom-color: #e1e5ea;
}
QPushButton#SidebarModeButton {
    min-height: 34px;
    border: 0;
    border-bottom: 0;
    border-radius: 9px;
    padding: 0 9px;
    background: transparent;
    color: #667085;
    font-size: 12px;
    font-weight: 650;
}
QPushButton#SidebarModeButton:hover { background: rgba(255, 255, 255, 150); color: #344054; }
QPushButton#SidebarModeButton[active="true"] {
    color: #2548a8;
    background: #ffffff;
    border: 1px solid #dce5f2;
    border-bottom: 2px solid #b8c8e2;
    font-weight: 750;
}
QPushButton#SidebarModeButton[active="true"]:pressed,
QPushButton#SidebarModeButton[active="true"][feedback="clicked"] {
    border-bottom-width: 1px;
    padding-top: 1px;
}
QPushButton#Primary {
    background: #3563e9;
    border-color: #3563e9;
    border-bottom-color: #2446ad;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#Primary:hover {
    background: #2f5bda;
    border-color: #2f5bda;
    border-bottom-color: #1e3f9f;
    color: #ffffff;
}
QPushButton#Primary:pressed, QPushButton#Primary[feedback="clicked"] {
    background: #284fc4;
    border-bottom-width: 1px;
}
QPushButton#Primary[active="true"] {
    color: #b93815;
    background: #fff4ed;
    border-color: #ffd6ae;
    border-bottom-color: #f79009;
}
QPushButton#Primary[active="true"]:hover { background: #ffead5; color: #9c2a10; }
QPushButton#Primary[workflowState="waiting"] {
    color: #7d8998;
    background: #eef1f5;
    border-color: #dfe4ea;
    border-bottom-color: #d4dae2;
    font-weight: 650;
}
QPushButton#Accent {
    background: #f0fdf5;
    border-color: #abefc6;
    border-bottom-color: #32b978;
    color: #067647;
    font-weight: 700;
}
QPushButton#Accent:hover { background: #dcfae6; border-color: #75e0a7; border-bottom-color: #17b26a; }
QPushButton#Accent[workflowState="waiting"] {
    color: #667085;
    background: #f2f4f7;
    border-color: #d0d5dd;
    border-bottom-color: #b8c0cc;
}
QPushButton#Accent[workflowState="working"] {
    color: #175cd3;
    background: #eff4ff;
    border-color: #b2ccff;
    border-bottom-color: #84adff;
}
QPushButton#Ghost { background: #f8faff; color: #344054; border-color: #e1e7f0; }
QPushButton#GhostSmall {
    min-height: 26px;
    max-height: 28px;
    padding: 0 10px 1px 10px;
    border-radius: 7px;
    color: #3157d5;
    background: #f1f5ff;
    border-color: #d8e3ff;
    border-bottom: 2px solid #b9caff;
    font-size: 11px;
}
QPushButton#GhostSmall:hover { background: #e8efff; border-color: #b9caff; }
QPushButton#GhostSmall:pressed, QPushButton#GhostSmall[feedback="clicked"] {
    border-bottom-width: 1px;
    padding-top: 1px;
    padding-bottom: 0;
}
QPushButton#HeaderControlButton {
    min-width: 108px;
    max-width: 108px;
    min-height: 40px;
    max-height: 40px;
    padding: 0 10px 1px 10px;
    border-radius: 10px;
    color: #3157d5;
    background: #f1f5ff;
    border-color: #d8e3ff;
    border-bottom: 2px solid #b9caff;
    font-size: 11px;
    font-weight: 650;
}
QPushButton#HeaderControlButton:hover { background: #e8efff; border-color: #b9caff; }
QPushButton#HeaderControlButton:pressed, QPushButton#HeaderControlButton[feedback="clicked"] {
    border-bottom-width: 1px;
    padding-top: 1px;
    padding-bottom: 0;
}
QPushButton#PresetEditButton {
    min-width: 46px;
    max-width: 54px;
    min-height: 34px;
    max-height: 34px;
    padding: 0 8px 2px 8px;
    color: #3157d5;
    background: #f1f5ff;
    border-color: #cbd9ff;
    border-bottom-color: #9fb7fb;
    font-weight: 700;
}
QPushButton#PresetEditButton:hover {
    color: #244bbd;
    background: #e8efff;
    border-color: #aebff6;
}
QPushButton#PresetEditButton:pressed,
QPushButton#PresetEditButton[feedback="clicked"] {
    border-bottom-width: 3px;
    padding-top: 0;
    padding-bottom: 2px;
}
QPushButton#PresetEditButton[mode="confirm"] {
    color: #ffffff;
    background: #17a765;
    border-color: #17a765;
    border-bottom-color: #087443;
}
QPushButton#PresetEditButton[mode="confirm"]:hover {
    color: #ffffff;
    background: #128a55;
    border-color: #128a55;
}
QPushButton#SidebarToggle {
    min-height: 28px;
    max-height: 30px;
    padding: 0 11px 1px 11px;
    color: #344054;
    background: #f8fafc;
    border: 1px solid #dfe6ef;
    border-bottom: 2px solid #c6d0dc;
    border-radius: 8px;
    font-size: 11px;
}
QPushButton#SidebarToggle:hover { color: #3157d5; background: #edf3ff; border-color: #c9d8ff; }
QPushButton#SidebarToggle[collapsed="true"] {
    color: #ffffff;
    background: #3563e9;
    border-color: #3563e9;
    border-bottom-color: #2446ad;
}
QPushButton#Danger { color: #b42318; border-color: #fecdca; background: #fff7f6; }
QPushButton#Danger:hover { color: #912018; border-color: #fda29b; background: #fff1f0; }
QPushButton#Danger:disabled {
    color: #98a2b3;
    background: #f2f4f7;
    border-color: #eaecf0;
    border-bottom-color: #e1e5ea;
}
QPushButton#MenuButton {
    min-height: 32px;
    padding: 0 10px 2px 10px;
    background: #f8fafc;
    border-color: #e5eaf0;
    border-bottom-color: #cbd5e1;
    color: #526173;
    font-size: 12px;
}
QPushButton#MenuButton:hover { background: #eef3f8; color: #253044; }
QPushButton#MenuButton[dropActive="true"] {
    color: #2548a8;
    background: #e7efff;
    border: 2px dashed #6f8ff0;
    border-bottom: 2px dashed #6f8ff0;
    font-weight: 750;
}
QLineEdit, QSpinBox, QComboBox {
    min-height: 36px;
    border-radius: 9px;
    padding: 0 10px;
    background: #ffffff;
    border: 1px solid #d7dee8;
    selection-background-color: #3157d5;
}
QComboBox#PaperPresetCombo {
    min-height: 38px;
    color: #253044;
    background: #f8fafc;
    border: 1px solid #cfd8e3;
    border-radius: 10px;
    padding: 0 30px 0 11px;
    font-weight: 650;
}
QComboBox#PaperPresetCombo:hover { border-color: #9eb5f4; background: #ffffff; }
QComboBox#PaperPresetCombo:focus { border: 2px solid #6b8cff; padding-left: 10px; }
QComboBox#PaperPresetCombo:disabled {
    color: #667085;
    background: #f2f4f7;
    border-color: #d7dee8;
}
QFrame#PaperPresetPopupWindow {
    background: #ffffff;
    border: 1px solid #cfd8e3;
    border-radius: 14px;
}
QListView#PaperPresetPopup {
    min-width: 238px;
    color: #253044;
    background: transparent;
    border: 0;
    border-radius: 10px;
    padding: 0;
    outline: 0;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #6684e8;
    background: #ffffff;
}
QWidget#CopyCountSelector {
    background: #f6f8fc;
    border: 1px solid #d7dfeb;
    border-radius: 9px;
}
QLabel#CopyCountValue {
    color: #253044;
    font-size: 11px;
    font-weight: 700;
}
QPushButton#CopyStepButton {
    min-width: 27px;
    max-width: 27px;
    min-height: 27px;
    max-height: 27px;
    padding: 0;
    margin: 0;
    border: 0;
    border-bottom: 0;
    border-radius: 7px;
    background: transparent;
    color: #3157c8;
    font-size: 16px;
    font-weight: 700;
}
QPushButton#CopyStepButton:hover {
    background: #e7eeff;
    color: #2446ad;
}
QPushButton#CopyStepButton:pressed {
    background: #d6e2ff;
    padding: 1px 0 0 0;
}
QPushButton#CopyStepButton:disabled {
    color: #c6ced9;
    background: transparent;
    border: 0;
}
QPushButton#CopyStepButton[quiet="true"],
QPushButton#CopyStepButton[quiet="true"]:disabled {
    color: transparent;
    background: transparent;
    border: 0;
}
QComboBox::drop-down { border: 0; width: 28px; }
QComboBox QAbstractItemView {
    color: #253044;
    background: #ffffff;
    border: 1px solid #d7dee8;
    border-radius: 10px;
    padding: 5px;
    outline: 0;
    selection-color: #2548a8;
    selection-background-color: #edf3ff;
}
QComboBox QAbstractItemView::item {
    min-height: 28px;
    border-radius: 7px;
    padding: 2px 8px;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 20px;
    margin: 2px;
    border: 1px solid #e1e7ef;
    border-radius: 6px;
    background: #f8fafc;
}

QPlainTextEdit {
    border: 1px solid #202b3a;
    background: #111925;
    color: #d8e1ed;
    border-radius: 11px;
    padding: 11px;
    selection-background-color: #3157d5;
    font-family: "Cascadia Mono", "Microsoft YaHei UI";
    font-size: 11px;
}
/* Use Fusion's native indicator so checked items always retain a visible
   check mark on Windows. A custom solid fill looked like a blue square. */
QCheckBox { spacing: 9px; color: #344054; }

QMenu {
    color: #253044;
    background: #ffffff;
    border: 1px solid #dce3ec;
    border-radius: 11px;
    padding: 6px;
}
QMenu::item {
    min-height: 27px;
    border-radius: 7px;
    padding: 3px 22px 3px 10px;
}
QMenu::item:selected { color: #2548a8; background: #edf3ff; }
QMenu::separator { height: 1px; background: #e8edf3; margin: 5px 7px; }
QToolTip {
    color: #ffffff;
    background: #253044;
    border: 1px solid #34445a;
    border-radius: 7px;
    padding: 5px 8px;
}
QDialog#RoundedMessageDialog { background: transparent; border: 0; }
QDialog#FaceVerificationDialog { background: transparent; border: 0; }
QFrame#FaceVerificationCard { background: #ffffff; border: 1px solid #dce3ec; border-radius: 20px; }
QLabel#FaceVerificationTitle { color: #101828; font-size: 18px; font-weight: 750; }
QLabel#FaceVerificationDetail { color: #667085; font-size: 12px; }
QLabel#FaceVerificationQr {
    background: #ffffff;
    border: 1px solid #dfe6ef;
    border-radius: 14px;
    padding: 9px;
}
QLabel#FaceVerificationStatus {
    color: #3157c8;
    background: #edf3ff;
    border: 1px solid #c7d7fe;
    border-radius: 10px;
    padding: 9px 10px;
    font-size: 11px;
    font-weight: 650;
}
QLabel#FaceVerificationStatus[state="success"] { color: #067647; background: #ecfdf3; border-color: #abefc6; }
QLabel#FaceVerificationStatus[state="warning"] { color: #b54708; background: #fffaeb; border-color: #fedf89; }
QLabel#FaceVerificationStatus[state="error"] { color: #b42318; background: #fff1f0; border-color: #fda29b; }
QPushButton#FaceProviderSwitch {
    color: #3157c8;
    background: #f7f9ff;
    border: 1px solid #cbd8fb;
    border-bottom: 2px solid #aebff0;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 650;
}
QPushButton#FaceProviderSwitch:hover { background: #edf3ff; border-color: #aebff0; }
QPushButton#FaceProviderSwitch[recommended="true"] {
    color: #ffffff;
    background: #12a150;
    border-color: #0d8a43;
    border-bottom-color: #08753a;
}
QPushButton#FaceProviderSwitch[recommended="true"]:hover { background: #0f9148; }
QPushButton#FaceProviderSwitch:pressed {
    border-bottom-width: 1px;
    padding-top: 1px;
}
QFrame#RoundedDialogCard { background: #ffffff; border: 1px solid #dce3ec; border-radius: 18px; }
QLabel#RoundedDialogTitle { color: #101828; font-size: 16px; font-weight: 750; }
QLabel#RoundedDialogMessage { color: #526173; font-size: 13px; background: transparent; }
QLabel#RoundedDialogDetail { color: #667085; background: #f6f8fb; border: 1px solid #e4e9f0; border-radius: 9px; padding: 10px 12px; font-size: 12px; }
QLabel#RoundedDialogDetail[kind="success"] { color: #344054; background: #f8fafc; border-color: #d8e1ea; font-size: 14px; }
QLabel#RoundedDialogIcon { color: #3157c8; background: #edf3ff; border: 1px solid #c7d7fe; border-radius: 19px; font-size: 21px; font-weight: 800; }
QLabel#RoundedDialogIcon[kind="warning"] { color: #b54708; background: #fffaeb; border-color: #fedf89; }
QLabel#RoundedDialogIcon[kind="error"] { color: #b42318; background: #fff1f0; border-color: #fda29b; }
QLabel#RoundedDialogIcon[kind="success"] { color: #067647; background: #ecfdf3; border-color: #abefc6; }
QPushButton#RoundedDialogClose { min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0; border: 0; border-bottom: 0; background: transparent; color: #667085; font-size: 20px; }
QPushButton#RoundedDialogClose:hover { color: #b42318; background: #fff1f0; border: 0; }
QPushButton#RoundedDialogConfirm { color: #ffffff; background: #3157c8; border-color: #3157c8; border-bottom-color: #1f3f9f; }
QPushButton#RoundedDialogCancel { color: #475467; background: #ffffff; border-color: #cfd8e3; border-bottom-color: #b8c3d1; }
QPushButton#RoundedDialogCancel:hover { color: #344054; background: #f5f7fa; border-color: #b8c3d1; }
QPushButton#RoundedDialogSuccessConfirm { color: #ffffff; background: #12a150; border-color: #0d8a43; border-bottom-color: #08753a; }
QPushButton#RoundedDialogSuccessConfirm:hover { background: #0f9148; border-color: #0d8a43; }
QPushButton#RoundedDialogDangerConfirm { color: #ffffff; background: #d92d20; border-color: #d92d20; border-bottom-color: #912018; }
QPushButton#RoundedDialogDangerConfirm:hover { background: #b42318; border-color: #b42318; }
QPushButton#RoundedDialogDangerSecondary { color: #b42318; background: #ffffff; border-color: #fda29b; border-bottom-color: #e88982; }
QPushButton#RoundedDialogDangerSecondary:hover { color: #912018; background: #fff1f0; border-color: #f97066; }

QLabel#PreviewCanvas {
    background: #eef2f7;
    border: 1px dashed #aebac9;
    border-radius: 12px;
    color: #7b8798;
    font-size: 15px;
}
QLabel#PreviewCanvas[state="ready"] {
    background: #edf1f6;
    border: 1px solid #d8e0ea;
    color: #7b8798;
}
QLabel#PreviewCanvas[state="error"] {
    background: #fff7ed;
    border: 1px solid #fed7aa;
    color: #b45309;
}

QTabWidget::pane {
    border: 1px solid #e0e6ee;
    background: #ffffff;
    border-radius: 11px;
    top: -1px;
}
QTabBar::tab {
    min-width: 82px;
    padding: 10px 19px;
    margin-right: 4px;
    color: #667085;
    background: #e9eef5;
    border: 1px solid #dde4ed;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QTabBar::tab:hover { background: #f3f6fa; }
QTabBar::tab:selected {
    color: #3157c8;
    background: #ffffff;
    font-weight: 650;
    border-bottom-color: #ffffff;
}

QScrollBar:vertical {
    width: 6px;
    background: transparent;
    margin: 3px 0;
}
QScrollBar::handle:vertical {
    background: rgba(133, 148, 166, 105);
    border-radius: 3px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: rgba(102, 116, 135, 175); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; background: transparent; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal {
    height: 6px;
    background: transparent;
    margin: 0 3px;
}
QScrollBar::handle:horizontal {
    background: rgba(133, 148, 166, 105);
    border-radius: 3px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: rgba(102, 116, 135, 175); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; background: transparent; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

QFrame#FloatingCard {
    background: #ffffff;
    border: 1px solid #d7e0eb;
    border-radius: 13px;
}
QFrame#FloatAccent { background: #98a2b3; border-top-left-radius: 12px; border-bottom-left-radius: 12px; }
QFrame#FloatAccent[state="working"] { background: #3563e9; }
QFrame#FloatAccent[state="success"] { background: #17b26a; }
QFrame#FloatAccent[state="warning"] { background: #f79009; }
QFrame#FloatAccent[state="error"] { background: #f04438; }
QLabel#FloatTitle { color: #172033; font-size: 13px; font-weight: 700; }
QLabel#FloatDetail { color: #667085; font-size: 10px; }
QLabel#FloatTime { color: #98a2b3; font-size: 9px; }
QLabel#FloatDot { font-size: 13px; min-width: 10px; }
QLabel#FloatDot[state="idle"] { color: #98a2b3; }
QLabel#FloatDot[state="working"] { color: #3157d5; }
QLabel#FloatDot[state="success"] { color: #12b76a; }
QLabel#FloatDot[state="warning"] { color: #f79009; }
QLabel#FloatDot[state="error"] { color: #f04438; }
QLabel#FloatState {
    border-radius: 8px;
    padding: 2px 6px;
    color: #667085;
    background: #f2f4f7;
    font-size: 9px;
    font-weight: 650;
}
QLabel#FloatState[state="working"] { color: #3157c8; background: #edf3ff; }
QLabel#FloatState[state="success"] { color: #067647; background: #ecfdf3; }
QLabel#FloatState[state="warning"] { color: #b54708; background: #fffaeb; }
QLabel#FloatState[state="error"] { color: #b42318; background: #fff1f0; }
QPushButton#FloatOpen {
    min-height: 22px;
    max-height: 24px;
    padding: 0 7px 1px 7px;
    border-radius: 7px;
    color: #3157d5;
    background: #edf3ff;
    border: 1px solid #d6e2ff;
    border-bottom: 2px solid #b9caff;
    font-size: 10px;
}

QToolTip { background: #172033; color: #ffffff; border: 0; padding: 6px; }
"""
