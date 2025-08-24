# spin.tcl --
#
# This demonstration script creates several spinbox widgets.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .spin
catch {destroy $w}
toplevel $w
wm title $w "Spinbox Demonstration"
wm iconname $w "spin"
positionWindow $w

label $w.msg -font $font -wraplength 5i -justify left -text "Three different\
	spin-boxes are displayed below.  You can add characters by pointing,\
	clicking and typing.  The normal Motif editing characters are\
	supported, along with many Emacs bindings.  For example, Backspace\
	and Control-h delete the character to the left of the insertion\
	cursor and Delete and Control-d delete the chararacter to the right\
	of the insertion cursor.  For values that are too large to fit in the\
	window all at once, you can scan through the value by dragging with\
	mouse button2 pressed.  Note that the first spin-box will only permit\
	you to type in integers, and the third selects from a list of\
	Australian cities."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

set australianCities {
    Canberra Sydney Melbourne Perth Adelaide Brisbane
    Hobart Darwin "Alice Springs"
}

spinbox $w.s1 -from 1 -to 10 -width 10 -validate key \
	-validatecommand {string is integer %P}
spinbox $w.s2 -from 0 -to 3 -increment .5 -format %05.2f -width 10
spinbox $w.s3 -values $australianCities -width 10

pack $w.s1 $w.s2 $w.s3 -side top -pady 5 -padx 10
