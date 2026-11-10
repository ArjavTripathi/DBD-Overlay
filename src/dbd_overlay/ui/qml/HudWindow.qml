// Streak HUD: icon, category, current streak, attempt + best, optional prompt.
// Sizes itself to its content; edit mode allows dragging (size = hud.scale).
import QtQuick
import QtQuick.Window
import DbdPlatform

PlatformWindow {
    id: root

    // Set from Python.
    property string iconSource: ""
    property string title: "No streak yet"
    property int current: 0
    property int attempt: 1
    property int best: 0
    property string prompt: ""          // e.g. "Win or loss? (streak-win / streak-loss)"
    property bool active: true          // streak switched on? Off = dimmed numbers
    property real contentOpacity: 0.85
    property real uiScale: 1.0
    property bool editMode: false
    signal editDone()

    readonly property color accent: "#e0c040"
    function px(v) { return Math.round(v * uiScale) }

    scopeName: "dbd-overlay-hud"
    clickThrough: !editMode
    focusable: editMode
    width: card.width
    height: card.height

    function clampMove(dx, dy) {
        moveTo(Math.max(0, Math.min(Screen.width - width, posX + dx)),
               Math.max(0, Math.min(Screen.height - height, posY + dy)))
    }

    Rectangle {
        id: card
        width: row.implicitWidth + px(28)
        height: row.implicitHeight + px(20)
        radius: px(10)
        color: "#d0101014"
        opacity: root.editMode ? 1.0 : root.contentOpacity
        border.color: root.editMode ? root.accent : "#40ffffff"
        border.width: root.editMode ? 2 : 1
        focus: true
        Keys.onEscapePressed: if (root.editMode) root.editDone()

        Row {
            id: row
            anchors.centerIn: parent
            spacing: px(14)

            Image {
                id: icon
                opacity: root.active ? 1.0 : 0.4
                visible: root.iconSource !== ""
                source: root.iconSource
                width: px(64); height: px(64)
                anchors.verticalCenter: parent.verticalCenter
                fillMode: Image.PreserveAspectFit
                smooth: true; mipmap: true; cache: false
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: px(2)
                Text {
                    text: root.title + (root.active ? "" : "  (off)")
                    color: "#d8d8d8"
                    font.pixelSize: px(15)
                    font.weight: Font.DemiBold
                }
                Row {
                    spacing: px(10)
                    opacity: root.active ? 1.0 : 0.35
                    Text {
                        text: root.current
                        color: "white"
                        font.pixelSize: px(40)
                        font.weight: Font.Bold
                    }
                    Column {
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: px(6)
                        Text { text: "Attempt #" + root.attempt; color: "#bbbbbb"; font.pixelSize: px(14) }
                        Text { text: "Best " + root.best; color: "#888888"; font.pixelSize: px(13) }
                    }
                }
                Text {
                    visible: root.prompt !== ""
                    text: root.prompt
                    color: root.accent
                    font.pixelSize: px(13)
                }
                Text {
                    visible: root.editMode
                    text: "Drag to move · Esc or edit-hud to lock"
                    color: root.accent
                    font.pixelSize: px(12)
                }
            }
        }

        // Move: delta-based (the window moves under the cursor).
        MouseArea {
            anchors.fill: parent
            enabled: root.editMode
            cursorShape: Qt.SizeAllCursor
            property point press
            onPressed: (m) => { press = Qt.point(m.x, m.y); card.forceActiveFocus() }
            onPositionChanged: (m) => root.clampMove(m.x - press.x, m.y - press.y)
        }
    }
}
