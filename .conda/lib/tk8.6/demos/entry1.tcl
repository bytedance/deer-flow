# entry1.tcl --
#
# This demonstration script creates several entry widgets without
# scrollbars.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .entry1
catch {destroy $w}
toplevel $w
wm title $w "Entry Demonstration (no scrollbars)"
wm iconname $w "entry1"
positionWindow $w

label $w.msg -font $font -wraplength 5i -justify left -text "Three different entries are displayed below.  You can add characters by pointing, clicking and typing.  The normal Motif editing characters are supported, along with many Emacs bindings.  For example, Backspace and Control-h delete the character to the left of the insertion cursor and Delete and Control-d delete the chararacter to the right of the insertion cursor.  For entries that are too large to fit in the window all at once, you can scan through the entries by dragging with mouse the middle mouse button pressed."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

entry $w.e1
entry $w.e2
entry $w.e3
pack $w.e1 $w.e2 $w.e3 -side top -pady 5 -padx 10 -fill x

$w.e1 insert 0 "Initial value"
$w.e2 insert end "This entry contains a long value, much too long "
$w.e2 insert end "to fit in the window at one time, so long in fact "
$w.e2 insert end "that you'll have to scan or scroll to see the end."
