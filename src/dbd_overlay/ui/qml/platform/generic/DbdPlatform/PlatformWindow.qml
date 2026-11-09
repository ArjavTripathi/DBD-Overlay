// Fallback (Windows, X11): a frameless always-on-top tool window.
// UNTESTED so far; the Windows port (M9) will verify it.
import QtQuick
import QtQuick.Window

Window {
    property int posX: 0
    property int posY: 0
    property bool clickThrough: true
    property bool focusable: false
    property string scopeName: "dbd-overlay"

    x: posX
    y: posY
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
           | (clickThrough ? Qt.WindowTransparentForInput : 0)
           | (focusable ? 0 : Qt.WindowDoesNotAcceptFocus)

    function moveTo(x, y) { posX = x; posY = y }
}
