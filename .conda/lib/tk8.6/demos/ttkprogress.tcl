# ttkprogress.tcl --
#
# This demonstration script creates several progress bar widgets.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .ttkprogress
catch {destroy $w}
toplevel $w
wm title $w "Progress Bar Demonstration"
wm iconname $w "ttkprogress"
positionWindow $w

ttk::label $w.msg -font $font -wraplength 4i -justify left -text "Below are two progress bars. The top one is a \u201Cdeterminate\u201D progress bar, which is used for showing how far through a defined task the program has got. The bottom one is an \u201Cindeterminate\u201D progress bar, which is used to show that the program is busy but does not know how long for. Both are run here in self-animated mode, which can be turned on and off using the buttons underneath."
pack $w.msg -side top -fill x

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

ttk::frame $w.f
pack $w.f -fill both -expand 1
set w $w.f

proc doBars {op args} {
    foreach w $args {
	$w $op
    }
}
ttk::progressbar $w.p1 -mode determinate
ttk::progressbar $w.p2 -mode indeterminate
ttk::button $w.start -text "Start Progress" -command [list \
	doBars start $w.p1 $w.p2]
ttk::button $w.stop -text "Stop Progress" -command [list \
	doBars stop $w.p1 $w.p2]

grid $w.p1 - -pady 5 -padx 10
grid $w.p2 - -pady 5 -padx 10
grid $w.start $w.stop -padx 10 -pady 5
grid configure $w.start -sticky e
grid configure $w.stop -sticky w
grid columnconfigure $w all -weight 1
