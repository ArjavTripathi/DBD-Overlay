// Map overlay: the map image, click-through. In edit mode it gets a frame,
// can be dragged (anywhere) and resized (bottom-right grip).
import QtQuick
import QtQuick.Window
import DbdPlatform

PlatformWindow {
    id: root

    // Set from Python.
    property string imageSource: ""      // "image://maps/<n>" or "" for none
    property real contentOpacity: 0.85
    property bool editMode: false
    property string placeholder: "Map overlay"
    signal editDone()                     // user pressed Esc in edit mode

    readonly property int minSize: 120
    readonly property color accent: "#e0c040"

    scopeName: "dbd-overlay-map"
    clickThrough: !editMode
    focusable: editMode

    function clampMove(dx, dy) {
        moveTo(Math.max(0, Math.min(Screen.width - width, posX + dx)),
               Math.max(0, Math.min(Screen.height - height, posY + dy)))
    }

    Item {
        id: content
        anchors.fill: parent
        focus: true
        Keys.onEscapePressed: if (root.editMode) root.editDone()

        Image {
            id: img
            anchors.fill: parent
            source: root.imageSource
            visible: root.imageSource !== ""
            fillMode: Image.PreserveAspectFit
            horizontalAlignment: Image.AlignLeft
            verticalAlignment: Image.AlignTop
            smooth: true
            mipmap: true
            cache: false
            opacity: root.contentOpacity
        }

        // Edit-mode chrome: frame, hint, placeholder when there's no image.
        Rectangle {
            anchors.fill: parent
            visible: root.editMode
            color: img.visible ? "transparent" : "#99000000"
            border.color: root.accent
            border.width: 3

            Text {
                anchors.centerIn: parent
                visible: !img.visible
                text: root.placeholder
                color: "white"
                font.pixelSize: 22
            }
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 3 }
                height: hint.implicitHeight + 10
                color: "#cc000000"
                Text {
                    id: hint
                    anchors.centerIn: parent
                    width: parent.width - 10
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    text: "Drag to move · corner to resize · Esc or edit-hud to lock"
                    color: "white"
                    font.pixelSize: 13
                }
            }
        }

        // Move: delta-based, because the window moves under the cursor
        // (after each move the press point is back under the cursor).
        MouseArea {
            anchors.fill: parent
            enabled: root.editMode
            cursorShape: Qt.SizeAllCursor
            property point press
            onPressed: (m) => { press = Qt.point(m.x, m.y); content.forceActiveFocus() }
            onPositionChanged: (m) => root.clampMove(m.x - press.x, m.y - press.y)
        }

        // Resize grip.
        Rectangle {
            width: 26; height: 26
            anchors { right: parent.right; bottom: parent.bottom }
            visible: root.editMode
            color: root.accent
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.SizeFDiagCursor
                property point press
                onPressed: (m) => press = Qt.point(m.x, m.y)
                onPositionChanged: (m) => {
                    root.width = Math.max(root.minSize, Math.min(Screen.width - root.posX, root.width + m.x - press.x))
                    root.height = Math.max(root.minSize, Math.min(Screen.height - root.posY, root.height + m.y - press.y))
                }
            }
        }
    }
}
