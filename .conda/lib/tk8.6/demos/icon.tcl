# icon.tcl --
#
# This demonstration script creates a toplevel window containing
# buttons that display bitmaps instead of text.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .icon
catch {destroy $w}
toplevel $w
wm title $w "Iconic Button Demonstration"
wm iconname $w "icon"
positionWindow $w

label $w.msg -font $font -wraplength 5i -justify left -text "This window shows three ways of using bitmaps or images in radiobuttons and checkbuttons.  On the left are two radiobuttons, each of which displays a bitmap and an indicator.  In the middle is a checkbutton that displays a different image depending on whether it is selected or not.  On the right is a checkbutton that displays a single bitmap but changes its background color to indicate whether or not it is selected."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

# Main widget program sets variable tk_demoDirectory
image create bitmap flagup \
	-file [file join $tk_demoDirectory images flagup.xbm] \
	-maskfile [file join $tk_demoDirectory images flagup.xbm]
image create bitmap flagdown \
	-file [file join $tk_demoDirectory images flagdown.xbm] \
	-maskfile [file join $tk_demoDirectory images flagdown.xbm]
frame $w.frame -borderwidth 10
pack $w.frame -side top

checkbutton $w.frame.b1 -image flagdown -selectimage flagup \
	-indicatoron 0
$w.frame.b1 configure -selectcolor [$w.frame.b1 cget -background]
checkbutton $w.frame.b2 \
	-bitmap @[file join $tk_demoDirectory images letters.xbm] \
	-indicatoron 0 -selectcolor SeaGreen1
frame $w.frame.left
pack $w.frame.left $w.frame.b1 $w.frame.b2 -side left -expand yes -padx 5m

radiobutton $w.frame.left.b3 \
	-bitmap @[file join $tk_demoDirectory images letters.xbm] \
	-variable letters -value full
radiobutton $w.frame.left.b4 \
	-bitmap @[file join $tk_demoDirectory images noletter.xbm] \
	-variable letters -value empty
pack $w.frame.left.b3 $w.frame.left.b4 -side top -expand yes
