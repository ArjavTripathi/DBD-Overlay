// Streak HUD: icon, category, current streak, attempt + best, optional prompt.
// Sizes itself to its content; edit mode allows dragging (size = hud.scale).
// Every look property is set from Python (config [hud], Settings > HUD).
import QtQuick
import QtQuick.Window
import DbdPlatform

PlatformWindow {
    id: root

    // Content.
    property string iconSource: ""
    property string title: "No streak yet"
    property int current: 0
    property int attempt: 1
    property int best: 0
    property string prompt: ""          // e.g. "Hatch or gate? ..."
    property bool active: true          // streak switched on? Off = dimmed numbers
    property bool editMode: false
    signal editDone()

    // Look.
    property real contentOpacity: 0.85
    property real uiScale: 1.0
    property bool compact: false        // icon + big number only
    property bool showIcon: true
    property bool showTitle: true
    property bool showAttempt: true
    property bool showBest: true
    property int iconSize: 64
    property color accent: "#e0c040"
    property color textColor: "#ffffff"
    property color bgColor: "#101014"
    property real bgOpacity: 0.82
    property bool showBorder: true
    property int cornerRadius: 10
    property string fontFamily: ""

    function px(v) { return Math.max(1, Math.round(v * uiScale)) }
    function dim(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }
    readonly property string family: fontFamily !== "" ? fontFamily : Qt.application.font.family
    readonly property bool hasIcon: showIcon && iconSource !== ""
    readonly property bool hasSubline: !compact && (showAttempt || showBest)

    scopeName: "dbd-overlay-hud"
    clickThrough: !editMode
    focusable: editMode
    width: card.width
    height: card.height

    function clampMove(dx, dy) {
        moveTo(Math.max(0, Math.min(Screen.width - width, posX + dx)),
               Math.max(0, Math.min(Screen.height - height, posY + dy)))
    }

    Item {
        id: card
        width: row.implicitWidth + px(compact ? 18 : 28)
        height: row.implicitHeight + px(compact ? 12 : 20)
        opacity: root.editMode ? 1.0 : root.contentOpacity
        focus: true
        Keys.onEscapePressed: if (root.editMode) root.editDone()

        Rectangle {
            anchors.fill: parent
            radius: px(root.cornerRadius)
            color: root.dim(root.bgColor, root.editMode ? Math.max(root.bgOpacity, 0.6) : root.bgOpacity)
            border.color: root.editMode ? root.accent : root.dim(root.textColor, 0.25)
            border.width: root.editMode ? 2 : (root.showBorder ? 1 : 0)
        }

        Row {
            id: row
            anchors.centerIn: parent
            spacing: px(compact ? 10 : 14)

            Image {
                visible: root.hasIcon
                opacity: root.active ? 1.0 : 0.4
                source: root.iconSource
                width: px(compact ? root.iconSize * 0.75 : root.iconSize)
                height: width
                anchors.verticalCenter: parent.verticalCenter
                fillMode: Image.PreserveAspectFit
                smooth: true; mipmap: true; cache: false
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: px(2)
                Text {
                    visible: root.showTitle && !root.compact
                    text: root.title + (root.active ? "" : "  (off)")
                    color: root.dim(root.textColor, 0.85)
                    font.family: root.family
                    font.pixelSize: px(15)
                    font.weight: Font.DemiBold
                }
                Row {
                    spacing: px(10)
                    opacity: root.active ? 1.0 : 0.35
                    Text {
                        text: root.current
                        color: root.textColor
                        font.family: root.family
                        font.pixelSize: px(root.compact ? 34 : 40)
                        font.weight: Font.Bold
                    }
                    Column {
                        visible: root.hasSubline
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: px(6)
                        Text {
                            visible: root.showAttempt
                            text: "Attempt #" + root.attempt
                            color: root.dim(root.textColor, 0.72)
                            font.family: root.family
                            font.pixelSize: px(14)
                        }
                        Text {
                            visible: root.showBest
                            text: "Best " + root.best
                            color: root.dim(root.textColor, 0.52)
                            font.family: root.family
                            font.pixelSize: px(13)
                        }
                    }
                }
                Text {
                    visible: root.prompt !== ""
                    text: root.prompt
                    color: root.accent
                    font.family: root.family
                    font.pixelSize: px(13)
                }
                Text {
                    visible: root.editMode
                    text: "Drag to move · Esc or edit-hud to lock"
                    color: root.accent
                    font.family: root.family
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
