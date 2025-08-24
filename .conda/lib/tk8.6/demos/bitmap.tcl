# bitmap.tcl --
#
# This demonstration script creates a toplevel window that displays
# all of Tk's built-in bitmaps.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

# bitmapRow --
# Create a row of bitmap items in a window.
#
# Arguments:
# w -		The window that is to contain the row.
# args -	The names of one or more bitmaps, which will be displayed
#		in a new row across the bottom of w along with their
#		names.

proc bitmapRow {w args} {
    frame $w
    pack $w -side top -fill both
    set i 0
    foreach bitmap $args {
	frame $w.$i
	pack $w.$i -side left -fill both -pady .25c -padx .25c
	label $w.$i.bitmap -bitmap $bitmap
	label $w.$i.label -text $bitmap -width 9
	pack $w.$i.label $w.$i.bitmap -side bottom
	incr i
    }
}

set w .bitmap
catch {destroy $w}
toplevel $w
wm title $w "Bitmap Demonstration"
wm iconname $w "bitmap"
positionWindow $w

label $w.msg -font $font -wraplength 4i -justify left -text "This window displays all of Tk's built-in bitmaps, along with the names you can use for them in Tcl scripts."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

frame $w.frame
bitmapRow $w.frame.0 error gray12 gray25 gray50 gray75
bitmapRow $w.frame.1 hourglass info question questhead warning
pack $w.frame -side top -expand yes -fill both
