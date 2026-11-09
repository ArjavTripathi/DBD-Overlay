// Linux/Wayland: a wlr-layer-shell surface on the OVERLAY layer.
// Drawn above fullscreen windows, never takes focus unless `focusable`,
// positioned by margins from the top-left corner of the output.
// Verified on Hyprland 0.57 with layer-shell-qt 6.8.
import QtQuick
import QtQuick.Window
import org.kde.layershell as LayerShell

Window {
    property int posX: 0
    property int posY: 0
    property bool clickThrough: true
    property bool focusable: false
    property string scopeName: "dbd-overlay"

    color: "transparent"
    flags: Qt.FramelessWindowHint | (clickThrough ? Qt.WindowTransparentForInput : 0)

    LayerShell.Window.scope: scopeName
    LayerShell.Window.layer: LayerShell.Window.LayerOverlay
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft
    LayerShell.Window.margins.left: posX
    LayerShell.Window.margins.top: posY
    LayerShell.Window.exclusionZone: -1   // don't push other windows around
    LayerShell.Window.keyboardInteractivity: focusable
        ? LayerShell.Window.KeyboardInteractivityOnDemand
        : LayerShell.Window.KeyboardInteractivityNone

    // Margin changes only apply on the surface's next commit: force one.
    function moveTo(x, y) { posX = x; posY = y; requestUpdate() }
}
