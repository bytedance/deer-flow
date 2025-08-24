# states.tcl --
#
# This demonstration script creates a listbox widget that displays
# the names of the 50 states in the United States of America.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .states
catch {destroy $w}
toplevel $w
wm title $w "Listbox Demonstration (50 states)"
wm iconname $w "states"
positionWindow $w

label $w.msg -font $font -wraplength 4i -justify left -text "A listbox containing the 50 states is displayed below, along with a scrollbar.  You can scan the list either using the scrollbar or by scanning.  To scan, press button 2 in the widget and drag up or down."
pack $w.msg -side top

labelframe $w.justif -text Justification
foreach c {Left Center Right} {
    set lower [string tolower $c]
    radiobutton $w.justif.$lower -text $c -variable just \
        -relief flat -value $lower -anchor w \
        -command "$w.frame.list configure -justify \$just" \
        -tristatevalue "multi"
    pack $w.justif.$lower -side left -pady 2 -fill x
}
pack $w.justif

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

frame $w.frame -borderwidth .5c
pack $w.frame -side top -expand yes -fill y

ttk::scrollbar $w.frame.scroll -command "$w.frame.list yview"
listbox $w.frame.list -yscroll "$w.frame.scroll set" -setgrid 1 -height 12
pack $w.frame.scroll -side right -fill y
pack $w.frame.list -side left -expand 1 -fill both

$w.frame.list insert 0 Alabama Alaska Arizona Arkansas California \
    Colorado Connecticut Delaware Florida Georgia Hawaii Idaho Illinois \
    Indiana Iowa Kansas Kentucky Louisiana Maine Maryland \
    Massachusetts Michigan Minnesota Mississippi Missouri \
    Montana Nebraska Nevada "New Hampshire" "New Jersey" "New Mexico" \
    "New York" "North Carolina" "North Dakota" \
    Ohio Oklahoma Oregon Pennsylvania "Rhode Island" \
    "South Carolina" "South Dakota" \
    Tennessee Texas Utah Vermont Virginia Washington \
    "West Virginia" Wisconsin Wyoming
