# clrpick.tcl --
#
# This demonstration script prompts the user to select a color.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .clrpick
catch {destroy $w}
toplevel $w
wm title $w "Color Selection Dialog"
wm iconname $w "colors"
positionWindow $w

label $w.msg -font $font -wraplength 4i -justify left -text "Press the buttons below to choose the foreground and background colors for the widgets in this window."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

button $w.back -text "Set background color ..." \
    -command \
    "setColor $w $w.back background {-background -highlightbackground}"
button $w.fore -text "Set foreground color ..." \
    -command \
    "setColor $w $w.back foreground -foreground"

pack $w.back $w.fore -side top -anchor c -pady 2m

proc setColor {w button name options} {
    grab $w
    set initialColor [$button cget -$name]
    set color [tk_chooseColor -title "Choose a $name color" -parent $w \
	-initialcolor $initialColor]
    if {[string compare $color ""]} {
	setColor_helper $w $options $color
    }
    grab release $w
}

proc setColor_helper {w options color} {
    foreach option $options {
	catch {
	    $w config $option $color
	}
    }
    foreach child [winfo children $w] {
	setColor_helper $child $options $color
    }
}
